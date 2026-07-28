from __future__ import annotations

import re

from mia.config import AppConfig
from mia.models import Finding, PluginContext, ProcessResult, TargetType
from mia.plugin import ExternalCommandPlugin
from mia.utils import strip_ansi

FIELD_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9 _./()-]{1,80}):\s*(.*)$")


class WhoisPlugin(ExternalCommandPlugin):
    plugin_id = "whois"
    name = "WHOIS"
    description = "Domain and IP registration records"
    target_types = frozenset({TargetType.DOMAIN, TargetType.IP})
    homepage = "https://github.com/rfc1036/whois"
    executable_candidates = ("whois",)
    version_arguments = ("--version",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [*self.command_prefix(executable), context.target]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        findings: list[Finding] = []
        current_key: str | None = None
        current_value: list[str] = []

        def flush() -> None:
            nonlocal current_key, current_value
            if not current_key:
                return
            value = " ".join(item.strip() for item in current_value if item.strip()).strip()
            if value and not value.lower().startswith(("terms of use", "notice:")):
                findings.append(
                    Finding(
                        plugin_id=self.plugin_id,
                        category="WHOIS",
                        kind="whois",
                        title=current_key,
                        value=value,
                        source_confidence=0.90,
                        evidence_path=process.stdout_path,
                    )
                )
            current_key = None
            current_value = []

        for raw_line in strip_ansi(process.stdout).splitlines():
            line = raw_line.rstrip()
            match = FIELD_RE.match(line)
            if match:
                flush()
                current_key, value = match.groups()
                current_value = [value]
            elif current_key and line[:1].isspace():
                current_value.append(line)
        flush()
        return findings


PLUGIN_CLASS = WhoisPlugin
