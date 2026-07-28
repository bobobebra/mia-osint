from __future__ import annotations

import json
from typing import Any

from mia.config import AppConfig
from mia.models import Finding, PluginContext, ProcessResult, TargetType
from mia.plugin import ExternalCommandPlugin


class ExifToolPlugin(ExternalCommandPlugin):
    plugin_id = "exiftool"
    name = "ExifTool"
    description = "Read metadata from images and other files"
    target_types = frozenset({TargetType.FILE})
    network_required = False
    homepage = "https://exiftool.org/"
    executable_candidates = ("exiftool",)
    version_arguments = ("-ver",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [*self.command_prefix(executable), "-json", "-G1", "-n", context.target]

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value)

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            return []
        record = payload[0]
        findings: list[Finding] = []
        for key, raw_value in sorted(record.items()):
            if raw_value in (None, "", [], {}):
                continue
            value = self._stringify(raw_value)
            lowered = key.lower()
            category = (
                "Geolocation"
                if any(token in lowered for token in ("gps", "location", "latitude", "longitude"))
                else "File metadata"
            )
            findings.append(
                Finding(
                    plugin_id=self.plugin_id,
                    category=category,
                    kind="metadata",
                    title=key,
                    value=value,
                    source_confidence=0.96,
                    attributes={"source_file": context.target},
                    evidence_path=process.stdout_path,
                )
            )
        return findings


PLUGIN_CLASS = ExifToolPlugin
