from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from mia.config import AppConfig
from mia.models import Finding, PluginContext, ProcessResult, TargetType
from mia.plugin import PythonModulePlugin
from mia.utils import strip_ansi

POSITIVE_RE = re.compile(r"^\[\+\]\s+([^\s]+)(?:\s+(.*))?$")


class HolehePlugin(PythonModulePlugin):
    plugin_id = "holehe"
    name = "Holehe"
    description = "Email registration checks with structured recovery hints"
    target_types = frozenset({TargetType.EMAIL})
    homepage = "https://github.com/megadose/holehe"
    module_name = "holehe"
    executable_candidates = ("mia-holehe-runner", "holehe")
    version_arguments = ("--version",)

    @staticmethod
    def _profile_timeout(extra_args: list[str]) -> str:
        for index, value in enumerate(extra_args):
            if value in {"--timeout", "-T"} and index + 1 < len(extra_args):
                return extra_args[index + 1]
        return "12"

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        timeout = self._profile_timeout(context.extra_args)
        if self.module_available():
            return [
                sys.executable,
                "-m",
                "mia.helpers.holehe_runner",
                context.target,
                "--timeout",
                timeout,
            ]
        if Path(executable).name == "mia-holehe-runner":
            return [executable, context.target, "--timeout", timeout]
        return [
            *self.command_prefix(executable),
            context.target,
            "--only-used",
            "--no-color",
            "--no-clear",
            "--timeout",
            timeout,
        ]

    def _from_record(self, record: dict[str, Any], evidence: str | None) -> Finding | None:
        if not record.get("exists"):
            return None
        domain = str(record.get("domain") or record.get("name") or "unknown service")
        attributes = {
            key: record[key]
            for key in ("emailrecovery", "phoneNumber", "others", "rateLimit")
            if record.get(key) not in (None, "", False)
        }
        return Finding(
            plugin_id=self.plugin_id,
            category="Registered accounts",
            kind="email_account",
            title=domain,
            value=domain,
            url=f"https://{domain}" if "." in domain else None,
            source_confidence=0.80,
            attributes=attributes,
            evidence_path=evidence,
        )

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError:
            payload = None
        findings: list[Finding] = []
        if isinstance(payload, list):
            for record in payload:
                if isinstance(record, dict):
                    finding = self._from_record(record, process.stdout_path)
                    if finding:
                        findings.append(finding)
            return findings

        for line in strip_ansi(process.stdout).splitlines():
            match = POSITIVE_RE.match(line.strip())
            if not match:
                continue
            domain, detail = match.groups()
            findings.append(
                Finding(
                    plugin_id=self.plugin_id,
                    category="Registered accounts",
                    kind="email_account",
                    title=domain,
                    value=domain,
                    url=f"https://{domain}" if "." in domain else None,
                    source_confidence=0.74,
                    attributes={"detail": detail} if detail else {},
                    evidence_path=process.stdout_path,
                )
            )
        return findings


PLUGIN_CLASS = HolehePlugin
