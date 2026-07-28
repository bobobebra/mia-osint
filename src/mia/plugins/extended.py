from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from mia.config import AppConfig
from mia.models import Finding, PluginContext, ProcessResult, TargetType
from mia.plugin import ExternalCommandPlugin
from mia.utils import strip_ansi

URL_RE = re.compile(r"https?://[^\s\]\[<>\"']+")
EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.I)
DOMAIN_RE = re.compile(
    r"(?<![@\w-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?![\w-])",
    re.I,
)


def _evidence(process: ProcessResult) -> str | None:
    return process.stdout_path


def _url_findings(
    plugin_id: str, text: str, evidence: str | None, confidence: float = 0.62
) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for raw in URL_RE.findall(strip_ansi(text)):
        url = raw.rstrip(".,;:)")
        if url in seen:
            continue
        seen.add(url)
        host = urlsplit(url).hostname or "Web result"
        findings.append(
            Finding(
                plugin_id=plugin_id,
                category="Profiles"
                if any(x in host for x in ("github", "reddit", "social", "instagram", "youtube"))
                else "URLs",
                kind="profile" if "@" in url or "/user" in url or "/u/" in url else "url",
                title=host,
                value=url,
                url=url,
                source_confidence=confidence,
                attributes={"host": host},
                evidence_path=evidence,
            )
        )
    return findings


def _domain_finding(
    plugin_id: str, domain: str, evidence: str | None, **attributes: Any
) -> Finding:
    return Finding(
        plugin_id=plugin_id,
        category="Subdomains",
        kind="domain",
        title=domain,
        value=domain,
        url=f"https://{domain}",
        source_confidence=0.72,
        attributes=attributes,
        evidence_path=evidence,
    )


class SubfinderPlugin(ExternalCommandPlugin):
    plugin_id = "subfinder"
    name = "Subfinder"
    description = "Passive subdomain enumeration"
    target_types = frozenset({TargetType.DOMAIN})
    homepage = "https://github.com/projectdiscovery/subfinder"
    executable_candidates = ("subfinder",)
    version_arguments = ("-version",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [executable, "-d", context.target, "-silent", "-json", *context.extra_args]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        findings: list[Finding] = []
        seen: set[str] = set()
        for line in process.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            host = ""
            attributes: dict[str, Any] = {}
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                host = line
            else:
                if isinstance(record, dict):
                    host = str(record.get("host") or record.get("domain") or "")
                    attributes = {k: v for k, v in record.items() if k not in {"host", "domain"}}
            host = host.strip().lower().rstrip(".")
            if not host or host in seen or not host.endswith(context.target.lower()):
                continue
            seen.add(host)
            findings.append(_domain_finding(self.plugin_id, host, _evidence(process), **attributes))
        return findings


class AssetfinderPlugin(ExternalCommandPlugin):
    plugin_id = "assetfinder"
    name = "Assetfinder"
    description = "Related domain and subdomain discovery"
    target_types = frozenset({TargetType.DOMAIN})
    homepage = "https://github.com/tomnomnom/assetfinder"
    executable_candidates = ("assetfinder",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [executable, "--subs-only", context.target, *context.extra_args]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        seen: set[str] = set()
        findings: list[Finding] = []
        for line in process.stdout.splitlines():
            domain = line.strip().lower().rstrip(".")
            if domain and domain.endswith(context.target.lower()) and domain not in seen:
                seen.add(domain)
                findings.append(_domain_finding(self.plugin_id, domain, _evidence(process)))
        return findings


class GauPlugin(ExternalCommandPlugin):
    plugin_id = "gau"
    name = "gau"
    description = "Known URL collection from public archives and indexes"
    target_types = frozenset({TargetType.DOMAIN})
    homepage = "https://github.com/lc/gau"
    executable_candidates = ("gau",)
    version_arguments = ("--version",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [executable, "--json", *context.extra_args, context.target]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        findings: list[Finding] = []
        seen: set[str] = set()
        for line in process.stdout.splitlines():
            url = ""
            attributes: dict[str, Any] = {}
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                url = line.strip()
            else:
                if isinstance(record, dict):
                    url = str(record.get("url") or "")
                    attributes = {k: v for k, v in record.items() if k != "url"}
            if not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            findings.append(
                Finding(
                    plugin_id=self.plugin_id,
                    category="Archived URLs",
                    kind="url",
                    title=urlsplit(url).hostname or "Archived URL",
                    value=url,
                    url=url,
                    source_confidence=0.68,
                    attributes=attributes,
                    evidence_path=_evidence(process),
                )
            )
        return findings


class HttpxPlugin(ExternalCommandPlugin):
    plugin_id = "httpx"
    name = "httpx"
    description = "HTTP metadata and technology probing"
    target_types = frozenset({TargetType.DOMAIN, TargetType.IP})
    homepage = "https://github.com/projectdiscovery/httpx"
    executable_candidates = ("httpx",)
    version_arguments = ("-version",)
    version_signatures = (r"projectdiscovery", r"current version", r"httpx(?:\s+|[-_])?version")

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [
            executable,
            "-u",
            context.target,
            "-silent",
            "-json",
            "-status-code",
            "-title",
            "-tech-detect",
            "-follow-redirects",
            *context.extra_args,
        ]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        findings: list[Finding] = []
        for line in process.stdout.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            url = str(record.get("url") or record.get("input") or "")
            if not url:
                continue
            title = str(record.get("title") or urlsplit(url).hostname or "HTTP endpoint")
            attributes = {
                key: record.get(key)
                for key in ("status_code", "webserver", "tech", "host", "ip", "port", "location")
                if record.get(key) not in (None, "", [], {})
            }
            findings.append(
                Finding(
                    plugin_id=self.plugin_id,
                    category="Web endpoints",
                    kind="web_endpoint",
                    title=title[:160],
                    value=url,
                    url=url if url.startswith(("http://", "https://")) else None,
                    source_confidence=0.82,
                    attributes=attributes,
                    evidence_path=_evidence(process),
                )
            )
        return findings


class DnstwistPlugin(ExternalCommandPlugin):
    plugin_id = "dnstwist"
    name = "dnstwist"
    description = "Lookalike-domain and brand-impersonation discovery"
    target_types = frozenset({TargetType.DOMAIN})
    homepage = "https://github.com/elceef/dnstwist"
    executable_candidates = ("dnstwist",)
    version_arguments = ("--version",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [executable, "--registered", "--format", "json", *context.extra_args, context.target]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        findings: list[Finding] = []
        for record in payload:
            if not isinstance(record, dict):
                continue
            domain = str(record.get("domain-name") or record.get("domain") or "").lower()
            if not domain or domain == context.target.lower():
                continue
            attributes = {k: v for k, v in record.items() if k not in {"domain-name", "domain"}}
            findings.append(
                Finding(
                    plugin_id=self.plugin_id,
                    category="Lookalike domains",
                    kind="lookalike_domain",
                    title=domain,
                    value=domain,
                    url=f"https://{domain}",
                    source_confidence=0.70,
                    attributes=attributes,
                    evidence_path=_evidence(process),
                )
            )
        return findings


class BlackbirdPlugin(ExternalCommandPlugin):
    plugin_id = "blackbird"
    name = "Blackbird"
    description = "Username and email account discovery"
    target_types = frozenset({TargetType.USERNAME, TargetType.EMAIL})
    homepage = "https://github.com/p1ngul1n0/blackbird"
    executable_candidates = ("blackbird",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        flag = "--email" if context.target_type is TargetType.EMAIL else "--username"
        return [executable, flag, context.target, *context.extra_args]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        return _url_findings(self.plugin_id, process.stdout, _evidence(process), 0.70)


class SocialAnalyzerPlugin(ExternalCommandPlugin):
    plugin_id = "social-analyzer"
    name = "Social Analyzer"
    description = "Social profile discovery and metadata analysis"
    target_types = frozenset({TargetType.USERNAME})
    homepage = "https://github.com/qeeqbox/social-analyzer"
    executable_candidates = ("social-analyzer",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [executable, "--username", context.target, "--metadata", *context.extra_args]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        return _url_findings(self.plugin_id, process.stdout, _evidence(process), 0.64)


class TheHarvesterPlugin(ExternalCommandPlugin):
    plugin_id = "theharvester"
    name = "theHarvester"
    description = "Public-source domain, host, and email collection"
    target_types = frozenset({TargetType.DOMAIN})
    homepage = "https://github.com/laramies/theHarvester"
    executable_candidates = ("theHarvester", "theharvester")
    version_arguments = ("--help",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [executable, "-d", context.target, *context.extra_args]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        text = strip_ansi(process.stdout)
        evidence = _evidence(process)
        findings = _url_findings(self.plugin_id, text, evidence, 0.66)
        seen_email: set[str] = set()
        for email in EMAIL_RE.findall(text):
            email = email.lower()
            if email in seen_email:
                continue
            seen_email.add(email)
            findings.append(
                Finding(
                    plugin_id=self.plugin_id,
                    category="Email addresses",
                    kind="email",
                    title=email,
                    value=email,
                    source_confidence=0.68,
                    evidence_path=evidence,
                )
            )
        seen_domain: set[str] = set()
        for domain in DOMAIN_RE.findall(text):
            domain = domain.lower().rstrip(".")
            if domain in seen_domain or domain == context.target.lower():
                continue
            if not domain.endswith(context.target.lower()):
                continue
            seen_domain.add(domain)
            findings.append(_domain_finding(self.plugin_id, domain, evidence))
        return findings


class PhoneInfogaPlugin(ExternalCommandPlugin):
    plugin_id = "phoneinfoga"
    name = "PhoneInfoga"
    description = "Phone-number formatting and OSINT helpers"
    target_types = frozenset({TargetType.PHONE})
    homepage = "https://github.com/sundowndev/phoneinfoga"
    executable_candidates = ("phoneinfoga",)
    version_arguments = ("version",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [executable, "scan", "-n", context.target, *context.extra_args]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        findings = _url_findings(self.plugin_id, process.stdout, _evidence(process), 0.58)
        clean = strip_ansi(process.stdout).strip()
        if clean:
            findings.append(
                Finding(
                    plugin_id=self.plugin_id,
                    category="Phone intelligence",
                    kind="phone_summary",
                    title="PhoneInfoga summary",
                    value=clean[:4000],
                    source_confidence=0.55,
                    attributes={"output_truncated_for_finding": len(clean) > 4000},
                    evidence_path=_evidence(process),
                )
            )
        return findings


PLUGIN_CLASSES = [
    SubfinderPlugin,
    AssetfinderPlugin,
    GauPlugin,
    HttpxPlugin,
    DnstwistPlugin,
    BlackbirdPlugin,
    SocialAnalyzerPlugin,
    TheHarvesterPlugin,
    PhoneInfogaPlugin,
]
