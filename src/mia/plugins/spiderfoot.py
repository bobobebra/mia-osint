from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from mia.config import AppConfig
from mia.models import Finding, FindingStatus, PluginContext, ProcessResult, TargetType
from mia.plugin import ExternalCommandPlugin

URL_RE = re.compile(r"^https?://", re.I)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class SpiderFootPlugin(ExternalCommandPlugin):
    plugin_id = "spiderfoot"
    name = "SpiderFoot"
    description = "Broad OSINT automation through SpiderFoot CLI"
    target_types = frozenset(
        {
            TargetType.USERNAME,
            TargetType.EMAIL,
            TargetType.DOMAIN,
            TargetType.IP,
            TargetType.PHONE,
            TargetType.PERSON,
        }
    )
    homepage = "https://github.com/smicallef/spiderfoot"
    executable_candidates = ("mia-spiderfoot", "~/spiderfoot/sf.py", "sf.py", "spiderfoot")
    version_arguments = ("-V",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [
            *self.command_prefix(executable),
            "-s",
            context.target,
            "-o",
            "json",
            *context.extra_args,
        ]

    @staticmethod
    def _decode_payload(text: str) -> Any:
        stripped = text.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            for opener, closer in (("[", "]"), ("{", "}")):
                start = stripped.find(opener)
                end = stripped.rfind(closer)
                if start >= 0 and end > start:
                    try:
                        return json.loads(stripped[start : end + 1])
                    except json.JSONDecodeError:
                        continue
        return []

    @staticmethod
    def _records(payload: Any) -> Iterable[dict[str, Any]]:
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    yield item
        elif isinstance(payload, dict):
            for key in ("data", "results", "events"):
                if isinstance(payload.get(key), list):
                    yield from SpiderFootPlugin._records(payload[key])
                    return
            yield payload

    @staticmethod
    def _kind_and_category(event_type: str, value: str) -> tuple[str, str, str | None]:
        upper = event_type.upper()
        if "URL" in upper or URL_RE.match(value):
            return "url", "URLs", value if URL_RE.match(value) else None
        if "EMAIL" in upper or EMAIL_RE.match(value):
            return "email", "Email addresses", None
        if any(token in upper for token in ("INTERNET_NAME", "DOMAIN", "HOSTNAME")):
            return "domain", "Domains and hosts", None
        if "IP_ADDRESS" in upper or upper == "IP":
            return "ip", "IP addresses", None
        if "PHONE" in upper:
            return "phone", "Phone numbers", None
        if "USERNAME" in upper or "ACCOUNT" in upper:
            return "username", "Usernames", None
        if "HUMAN_NAME" in upper or "PERSON" in upper:
            return "person", "People", None
        return "spiderfoot_event", "SpiderFoot events", None

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        payload = self._decode_payload(process.stdout)
        findings: list[Finding] = []
        seen: set[tuple[str, str]] = set()
        for index, record in enumerate(self._records(payload)):
            if index >= 5000:
                break
            value = record.get("data") or record.get("value") or record.get("eventData")
            if value in (None, ""):
                continue
            value = str(value).strip()
            event_type = str(record.get("type") or record.get("eventType") or "EVENT")
            key = (event_type, value)
            if key in seen:
                continue
            seen.add(key)
            kind, category, url = self._kind_and_category(event_type, value)
            confidence_raw = record.get("confidence", 0.68)
            try:
                confidence = float(confidence_raw)
                if confidence > 1:
                    confidence /= 100
                confidence = max(0.0, min(confidence, 1.0))
            except (TypeError, ValueError):
                confidence = 0.68
            findings.append(
                Finding(
                    plugin_id=self.plugin_id,
                    category=category,
                    kind=kind,
                    title=event_type.replace("_", " ").title(),
                    value=value,
                    url=url,
                    status=FindingStatus.CONFIRMED,
                    source_confidence=confidence,
                    attributes={
                        key: record[key]
                        for key in ("module", "source", "generated", "scanId")
                        if record.get(key) not in (None, "")
                    },
                    evidence_path=process.stdout_path,
                )
            )
        return findings


PLUGIN_CLASS = SpiderFootPlugin
