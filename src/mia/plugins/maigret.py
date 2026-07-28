from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from mia.account_discovery import parse_public_profile_url
from mia.config import AppConfig
from mia.display import friendly_site_name
from mia.models import Finding, FindingStatus, PluginContext, ProcessResult, TargetType
from mia.plugin import ExternalCommandPlugin


class MaigretPlugin(ExternalCommandPlugin):
    plugin_id = "maigret"
    name = "Maigret"
    description = "Username account discovery and profile metadata"
    target_types = frozenset({TargetType.USERNAME})
    homepage = "https://github.com/soxoj/maigret"
    executable_candidates = ("maigret",)
    version_arguments = ("--version",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [
            *self.command_prefix(executable),
            context.target,
            "--json",
            "simple",
            "--folderoutput",
            str(context.raw_dir),
            *context.extra_args,
        ]

    def _iter_entries(
        self, data: Any, fallback_site: str | None = None
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        if isinstance(data, list):
            for item in data:
                yield from self._iter_entries(item, fallback_site)
            return
        if not isinstance(data, dict):
            return
        if isinstance(data.get("matches"), list):
            for item in data["matches"]:
                if isinstance(item, dict):
                    yield str(item.get("site") or item.get("name") or "Unknown site"), item
            return
        if any(key in data for key in ("url_user", "url", "status", "exists")):
            yield str(data.get("site") or data.get("name") or fallback_site or "Unknown site"), data
            return
        for key, value in data.items():
            if key in {"not_found", "disabled", "query_username", "maigret_version"}:
                continue
            yield from self._iter_entries(value, str(key))

    @staticmethod
    def _is_found(entry: dict[str, Any]) -> tuple[bool, FindingStatus]:
        status = entry.get("status", entry.get("exists"))
        if isinstance(status, dict):
            status = status.get("status") or status.get("value") or status.get("name")
        normalized = str(status).strip().lower()
        if status is True or normalized in {"found", "claimed", "exists", "true", "active"}:
            return True, FindingStatus.CONFIRMED
        if normalized in {"unknown", "possible", "maybe"}:
            return True, FindingStatus.POSSIBLE
        if not normalized and (entry.get("url_user") or entry.get("url")):
            return True, FindingStatus.POSSIBLE
        return False, FindingStatus.NEGATIVE

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        candidates = [
            path
            for path in context.raw_dir.rglob("*.json")
            if path.name
            not in {"command.json", "process.json", "parsed_findings.json", "plugin_error.json"}
        ]
        payloads: list[tuple[Path, Any]] = []
        for path in candidates:
            try:
                payloads.append((path, json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                continue
        if not payloads:
            try:
                payloads.append(
                    (Path(process.stdout_path or "stdout.txt"), json.loads(process.stdout))
                )
            except json.JSONDecodeError:
                return []

        findings: list[Finding] = []
        seen: set[str] = set()
        for path, payload in payloads:
            for site, entry in self._iter_entries(payload):
                found, status = self._is_found(entry)
                if not found:
                    continue
                url = entry.get("url_user") or entry.get("url") or entry.get("profile_url")
                if not url:
                    continue
                url = str(url)
                if url in seen:
                    continue
                seen.add(url)
                score = entry.get("score", entry.get("confidence", 0.82))
                try:
                    confidence = max(0.0, min(float(score), 1.0))
                except (TypeError, ValueError):
                    confidence = 0.82
                attributes: dict[str, Any] = {}
                for key in ("ids", "tags", "country", "username", "fullname", "bio"):
                    if entry.get(key) not in (None, "", [], {}):
                        attributes[key] = entry[key]
                reference = parse_public_profile_url(url)
                if reference:
                    attributes.setdefault("platform", reference.platform)
                    attributes.setdefault("username", reference.username)
                else:
                    attributes.setdefault("username", context.target)
                findings.append(
                    Finding(
                        plugin_id=self.plugin_id,
                        category="Profiles",
                        kind="profile",
                        title=friendly_site_name(site, entry=entry, url=url),
                        value=url,
                        url=url,
                        status=status,
                        source_confidence=confidence,
                        attributes=attributes,
                        evidence_path=str(path),
                    )
                )
        return findings


PLUGIN_CLASS = MaigretPlugin
