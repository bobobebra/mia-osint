from __future__ import annotations

import asyncio
from abc import abstractmethod
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import quote

from mia.config import AppConfig
from mia.http import AsyncJsonClient, HttpApiError
from mia.models import (
    Finding,
    FindingStatus,
    PluginContext,
    PluginRunResult,
    PluginRunStatus,
    TargetType,
    ToolStatus,
)
from mia.plugin import BasePlugin
from mia.process import ProcessRunner
from mia.secrets import SecretStore
from mia.utils import atomic_write_json


class PassiveApiPlugin(BasePlugin):
    service: ClassVar[str]
    network_required = True

    def detect(self, config: AppConfig) -> ToolStatus:
        api = config.api(self.service)
        if not api.enabled:
            return ToolStatus(
                plugin_id=self.plugin_id,
                name=self.name,
                available=False,
                message=f"API integration disabled (set apis.{self.service}.enabled: true)",
                install_hint=f"mia api set {self.service}",
            )
        source = SecretStore(config).source(self.service)
        available = source != "not configured"
        return ToolStatus(
            plugin_id=self.plugin_id,
            name=self.name,
            available=available,
            message=f"API key from {source}" if available else "API key not configured",
            install_hint=f"mia api set {self.service}",
        )

    @abstractmethod
    async def fetch(self, context: PluginContext, config: AppConfig, key: str) -> Any:
        raise NotImplementedError

    @abstractmethod
    def parse_payload(self, context: PluginContext, payload: Any) -> list[Finding]:
        raise NotImplementedError

    def handle_http_error(
        self, context: PluginContext, error: HttpApiError
    ) -> list[Finding] | None:
        if error.status == 404:
            return []
        return None

    def raw_payload(self, payload: Any) -> Any:
        """Return the provider-safe payload that may be persisted as raw evidence."""
        return payload

    def raw_error_body(self, body: str) -> str:
        """Return a bounded provider-safe HTTP error excerpt for raw evidence."""
        return body[:2000]

    async def execute(
        self, context: PluginContext, config: AppConfig, runner: ProcessRunner
    ) -> PluginRunResult:
        del runner
        started = datetime.now(UTC)
        context.raw_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        status = self.detect(config)
        if not status.available:
            finished = datetime.now(UTC)
            return PluginRunResult(
                plugin_id=self.plugin_id,
                plugin_name=self.name,
                status=PluginRunStatus.UNAVAILABLE,
                started_at=started,
                finished_at=finished,
                duration_seconds=(finished - started).total_seconds(),
                raw_dir=str(context.raw_dir),
                error=status.message,
            )
        key = SecretStore(config).get(self.service)
        if not key:
            finished = datetime.now(UTC)
            return PluginRunResult(
                plugin_id=self.plugin_id,
                plugin_name=self.name,
                status=PluginRunStatus.UNAVAILABLE,
                started_at=started,
                finished_at=finished,
                duration_seconds=(finished - started).total_seconds(),
                raw_dir=str(context.raw_dir),
                error="API key disappeared after detection",
            )
        try:
            payload = await self.fetch(context, config, key)
            atomic_write_json(context.raw_dir / "response.json", self.raw_payload(payload))
            findings = self.parse_payload(context, payload)
            atomic_write_json(
                context.raw_dir / "parsed_findings.json",
                [finding.model_dump(mode="json") for finding in findings],
            )
            finished = datetime.now(UTC)
            return PluginRunResult(
                plugin_id=self.plugin_id,
                plugin_name=self.name,
                status=PluginRunStatus.SUCCESS,
                started_at=started,
                finished_at=finished,
                duration_seconds=(finished - started).total_seconds(),
                raw_dir=str(context.raw_dir),
                findings=findings,
            )
        except HttpApiError as exc:
            handled = self.handle_http_error(context, exc)
            finished = datetime.now(UTC)
            if handled is not None:
                atomic_write_json(
                    context.raw_dir / "response.json", {"status": exc.status, "message": str(exc)}
                )
                return PluginRunResult(
                    plugin_id=self.plugin_id,
                    plugin_name=self.name,
                    status=PluginRunStatus.SUCCESS,
                    started_at=started,
                    finished_at=finished,
                    duration_seconds=(finished - started).total_seconds(),
                    raw_dir=str(context.raw_dir),
                    findings=handled,
                    warnings=[f"API returned HTTP {exc.status}; interpreted as no result"],
                )
            atomic_write_json(
                context.raw_dir / "api_error.json",
                {
                    "status": exc.status,
                    "message": str(exc),
                    "body_excerpt": self.raw_error_body(exc.body),
                },
            )
            return PluginRunResult(
                plugin_id=self.plugin_id,
                plugin_name=self.name,
                status=PluginRunStatus.FAILED,
                started_at=started,
                finished_at=finished,
                duration_seconds=(finished - started).total_seconds(),
                raw_dir=str(context.raw_dir),
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception as exc:
            finished = datetime.now(UTC)
            atomic_write_json(
                context.raw_dir / "api_error.json",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
            return PluginRunResult(
                plugin_id=self.plugin_id,
                plugin_name=self.name,
                status=PluginRunStatus.FAILED,
                started_at=started,
                finished_at=finished,
                duration_seconds=(finished - started).total_seconds(),
                raw_dir=str(context.raw_dir),
                error=f"{type(exc).__name__}: {exc}",
            )


def _evidence(context: PluginContext) -> str:
    return str(context.raw_dir / "response.json")


class ShodanApiPlugin(PassiveApiPlugin):
    plugin_id = "api-shodan"
    service = "shodan"
    name = "Shodan API"
    description = "Passive Shodan host enrichment"
    target_types = frozenset({TargetType.IP})
    homepage = "https://developer.shodan.io/api"

    async def fetch(self, context: PluginContext, config: AppConfig, key: str) -> Any:
        api = config.api(self.service)
        client = AsyncJsonClient(api.timeout)
        return (
            await client.request(
                "GET",
                f"{api.endpoint.rstrip('/')}/shodan/host/{quote(context.target)}",
                query={"key": key},
            )
        ).data

    def parse_payload(self, context: PluginContext, payload: Any) -> list[Finding]:
        if not isinstance(payload, dict):
            return []
        evidence = _evidence(context)
        findings = [
            Finding(
                plugin_id=self.plugin_id,
                category="Host intelligence",
                kind="ip",
                title=str(payload.get("ip_str") or context.target),
                value=str(payload.get("ip_str") or context.target),
                source_confidence=0.92,
                attributes={
                    key: payload.get(key)
                    for key in (
                        "org",
                        "isp",
                        "asn",
                        "country_name",
                        "city",
                        "latitude",
                        "longitude",
                        "last_update",
                        "ports",
                        "vulns",
                    )
                    if payload.get(key) not in (None, "", [], {})
                },
                evidence_path=evidence,
            )
        ]
        for hostname in payload.get("hostnames") or []:
            findings.append(
                Finding(
                    plugin_id=self.plugin_id,
                    category="Domains",
                    kind="domain",
                    title=str(hostname),
                    value=str(hostname),
                    source_confidence=0.88,
                    attributes={"ip": context.target},
                    evidence_path=evidence,
                )
            )
        return findings


class VirusTotalApiPlugin(PassiveApiPlugin):
    plugin_id = "api-virustotal"
    service = "virustotal"
    name = "VirusTotal API"
    description = "Passive reputation and relationship enrichment"
    target_types = frozenset({TargetType.DOMAIN, TargetType.IP, TargetType.HASH})
    homepage = "https://docs.virustotal.com/reference/overview"

    async def fetch(self, context: PluginContext, config: AppConfig, key: str) -> Any:
        api = config.api(self.service)
        collection = {
            TargetType.DOMAIN: "domains",
            TargetType.IP: "ip_addresses",
            TargetType.HASH: "files",
        }[context.target_type]
        client = AsyncJsonClient(api.timeout)
        return (
            await client.request(
                "GET",
                f"{api.endpoint.rstrip('/')}/{collection}/{quote(context.target)}",
                headers={"x-apikey": key},
            )
        ).data

    def parse_payload(self, context: PluginContext, payload: Any) -> list[Finding]:
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return []
        attrs = data.get("attributes") or {}
        kind = context.target_type.value
        return [
            Finding(
                plugin_id=self.plugin_id,
                category="Reputation",
                kind=kind,
                title=f"VirusTotal report for {context.target}",
                value=context.target,
                source_confidence=0.90,
                attributes={
                    key: attrs.get(key)
                    for key in (
                        "last_analysis_stats",
                        "reputation",
                        "categories",
                        "registrar",
                        "creation_date",
                        "last_modification_date",
                        "meaningful_name",
                        "type_description",
                        "tags",
                    )
                    if attrs.get(key) not in (None, "", [], {})
                },
                evidence_path=_evidence(context),
            )
        ]


class HibpApiPlugin(PassiveApiPlugin):
    plugin_id = "api-hibp"
    service = "hibp"
    name = "Have I Been Pwned API"
    description = "Breach-name and breach-date metadata for an email address"
    target_types = frozenset({TargetType.EMAIL})
    homepage = "https://haveibeenpwned.com/API/v3"

    async def fetch(self, context: PluginContext, config: AppConfig, key: str) -> Any:
        api = config.api(self.service)
        client = AsyncJsonClient(api.timeout)
        return (
            await client.request(
                "GET",
                f"{api.endpoint.rstrip('/')}/breachedaccount/{quote(context.target)}",
                headers={"hibp-api-key": key},
                query={"truncateResponse": "false"},
            )
        ).data

    def parse_payload(self, context: PluginContext, payload: Any) -> list[Finding]:
        if not isinstance(payload, list):
            return []
        findings: list[Finding] = []
        for breach in payload:
            if not isinstance(breach, dict):
                continue
            name = str(breach.get("Name") or breach.get("Title") or "Breach")
            findings.append(
                Finding(
                    plugin_id=self.plugin_id,
                    category="Breach metadata",
                    kind="breach",
                    title=name,
                    value=name,
                    url=breach.get("Domain") and f"https://{breach['Domain']}",
                    status=FindingStatus.POSSIBLE,
                    source_confidence=0.92,
                    attributes={
                        "breach_date": breach.get("BreachDate"),
                        "added_date": breach.get("AddedDate"),
                        "modified_at": breach.get("ModifiedDate"),
                        "domain": breach.get("Domain"),
                        "data_classes": breach.get("DataClasses") or [],
                        "verified": breach.get("IsVerified"),
                        "sensitive": breach.get("IsSensitive"),
                        "email": context.target,
                    },
                    evidence_path=_evidence(context),
                )
            )
        return findings


class SecurityTrailsApiPlugin(PassiveApiPlugin):
    plugin_id = "api-securitytrails"
    service = "securitytrails"
    name = "SecurityTrails API"
    description = "Passive current DNS and domain intelligence"
    target_types = frozenset({TargetType.DOMAIN})
    homepage = "https://docs.securitytrails.com/docs/overview"

    async def fetch(self, context: PluginContext, config: AppConfig, key: str) -> Any:
        api = config.api(self.service)
        client = AsyncJsonClient(api.timeout)
        return (
            await client.request(
                "GET",
                f"{api.endpoint.rstrip('/')}/domain/{quote(context.target)}",
                headers={"APIKEY": key},
            )
        ).data

    def parse_payload(self, context: PluginContext, payload: Any) -> list[Finding]:
        if not isinstance(payload, dict):
            return []
        evidence = _evidence(context)
        findings = [
            Finding(
                plugin_id=self.plugin_id,
                category="Domain intelligence",
                kind="domain",
                title=context.target,
                value=context.target,
                source_confidence=0.90,
                attributes={
                    key: payload.get(key)
                    for key in (
                        "apex_domain",
                        "hostname",
                        "current_dns",
                        "alexa_rank",
                        "host_provider",
                        "mail_provider",
                    )
                    if payload.get(key) not in (None, "", [], {})
                },
                evidence_path=evidence,
            )
        ]
        current_dns = payload.get("current_dns") or {}
        if isinstance(current_dns, dict):
            for record_type, block in current_dns.items():
                values = block.get("values") if isinstance(block, dict) else None
                if not isinstance(values, list):
                    continue
                for value in values[:200]:
                    if not isinstance(value, dict):
                        continue
                    data = value.get("ip") or value.get("hostname") or value.get("value")
                    if not data:
                        continue
                    kind = "ip" if value.get("ip") else "domain" if value.get("hostname") else "dns"
                    findings.append(
                        Finding(
                            plugin_id=self.plugin_id,
                            category="DNS records",
                            kind=kind,
                            title=f"{record_type.upper()} {data}",
                            value=str(data),
                            source_confidence=0.88,
                            attributes={"record_type": record_type, **value},
                            evidence_path=evidence,
                        )
                    )
        return findings


class CensysApiPlugin(PassiveApiPlugin):
    plugin_id = "api-censys"
    service = "censys"
    name = "Censys Platform API"
    description = "Passive Censys host enrichment"
    target_types = frozenset({TargetType.IP})
    homepage = "https://docs.censys.com/reference/get-started"

    async def fetch(self, context: PluginContext, config: AppConfig, key: str) -> Any:
        api = config.api(self.service)
        headers = {
            "Authorization": f"Bearer {key}",
            "Accept": "application/vnd.censys.api.v3.host.v1+json",
            **api.extra_headers,
        }
        if api.organization_id:
            headers["X-Organization-ID"] = api.organization_id
        client = AsyncJsonClient(api.timeout)
        return (
            await client.request(
                "GET",
                f"{api.endpoint.rstrip('/')}/global/asset/host/{quote(context.target)}",
                headers=headers,
            )
        ).data

    def parse_payload(self, context: PluginContext, payload: Any) -> list[Finding]:
        resource = payload
        if isinstance(payload, dict):
            resource = (
                (payload.get("result") or {}).get("resource") or payload.get("result") or payload
            )
        if not isinstance(resource, dict):
            return []
        return [
            Finding(
                plugin_id=self.plugin_id,
                category="Host intelligence",
                kind="ip",
                title=f"Censys host {context.target}",
                value=context.target,
                source_confidence=0.90,
                attributes={
                    key: resource.get(key)
                    for key in (
                        "ip",
                        "location",
                        "autonomous_system",
                        "dns",
                        "services",
                        "last_updated_at",
                    )
                    if resource.get(key) not in (None, "", [], {})
                },
                evidence_path=_evidence(context),
            )
        ]


class IntelXApiPlugin(PassiveApiPlugin):
    plugin_id = "api-intelx"
    service = "intelx"
    name = "Intelligence X API"
    description = "Metadata-only Intelligence X search; document contents are not downloaded"
    target_types = frozenset(
        {TargetType.EMAIL, TargetType.DOMAIN, TargetType.IP, TargetType.PHONE, TargetType.URL}
    )
    homepage = "https://github.com/IntelligenceX/SDK"

    async def fetch(self, context: PluginContext, config: AppConfig, key: str) -> Any:
        api = config.api(self.service)
        client = AsyncJsonClient(api.timeout)
        search = await client.request(
            "POST",
            f"{api.endpoint.rstrip('/')}/intelligent/search",
            headers={"X-Key": key},
            query={
                "term": context.target,
                "maxresults": 25,
                "timeout": min(api.timeout, 30),
                "sort": 4,
                "media": 0,
            },
        )
        search_id = search.data.get("id") if isinstance(search.data, dict) else None
        if not search_id:
            return {"search": search.data, "records": []}
        await asyncio.sleep(1.0)
        result = await client.request(
            "GET",
            f"{api.endpoint.rstrip('/')}/intelligent/search/result",
            headers={"X-Key": key},
            query={"id": search_id, "limit": 25, "media": 0, "statistics": 1},
        )
        return {"search": search.data, "records": result.data}

    @staticmethod
    def _safe_record(record: dict[str, Any]) -> dict[str, Any]:
        allowed = (
            "name",
            "date",
            "bucket",
            "media",
            "contenttype",
            "size",
            "systemid",
            "storageid",
        )
        return {
            key: record.get(key) for key in allowed if record.get(key) not in (None, "", [], {})
        }

    def raw_payload(self, payload: Any) -> Any:
        if not isinstance(payload, dict):
            return {"records": []}
        search = payload.get("search")
        safe_search = {}
        if isinstance(search, dict):
            safe_search = {
                key: search.get(key)
                for key in ("id", "status", "records", "buckets", "media")
                if search.get(key) not in (None, "", [], {})
            }
        records_payload = payload.get("records")
        if isinstance(records_payload, dict):
            source_records = records_payload.get("records") or records_payload.get("items") or []
        elif isinstance(records_payload, list):
            source_records = records_payload
        else:
            source_records = []
        safe_records = [
            self._safe_record(record) for record in source_records[:25] if isinstance(record, dict)
        ]
        return {"search": safe_search, "records": {"records": safe_records}}

    def raw_error_body(self, body: str) -> str:
        # Intelligence X error bodies may include search previews. Persist status/message only.
        return "[provider response body redacted by MIA metadata-only policy]" if body else ""

    def parse_payload(self, context: PluginContext, payload: Any) -> list[Finding]:
        records_payload = payload.get("records") if isinstance(payload, dict) else None
        records = []
        if isinstance(records_payload, dict):
            records = records_payload.get("records") or records_payload.get("items") or []
        elif isinstance(records_payload, list):
            records = records_payload
        findings: list[Finding] = []
        for record in records[:25]:
            if not isinstance(record, dict):
                continue
            # Intentionally exclude previews and content. MIA stores only source metadata.
            safe = self._safe_record(record)
            title = str(safe.get("name") or safe.get("bucket") or "Intelligence X record")
            findings.append(
                Finding(
                    plugin_id=self.plugin_id,
                    category="Intelligence X metadata",
                    kind="intelx_record",
                    title=title[:180],
                    value=str(safe.get("systemid") or title),
                    url=f"https://intelx.io/?s={quote(context.target)}",
                    status=FindingStatus.POSSIBLE,
                    source_confidence=0.62,
                    attributes={**safe, "query": context.target, "content_downloaded": False},
                    evidence_path=_evidence(context),
                )
            )
        return findings


PLUGIN_CLASSES = [
    ShodanApiPlugin,
    VirusTotalApiPlugin,
    HibpApiPlugin,
    SecurityTrailsApiPlugin,
    CensysApiPlugin,
    IntelXApiPlugin,
]
