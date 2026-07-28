from __future__ import annotations

import re
from urllib.parse import urlsplit

from mia.account_discovery import parse_public_profile_url
from mia.config import AppConfig
from mia.models import Finding, PluginContext, ProcessResult, TargetType
from mia.plugin import ExternalCommandPlugin
from mia.utils import strip_ansi

URL_RE = re.compile(r"https?://[^\s\]\[<>\"']+")


class SherlockPlugin(ExternalCommandPlugin):
    plugin_id = "sherlock"
    name = "Sherlock"
    description = "Username discovery across social networks"
    target_types = frozenset({TargetType.USERNAME})
    homepage = "https://github.com/sherlock-project/sherlock"
    executable_candidates = ("sherlock", "sherlock-project")
    version_arguments = ("--version",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        output_path = context.raw_dir / "sherlock.txt"
        return [
            *self.command_prefix(executable),
            context.target,
            "--output",
            str(output_path),
            "--print-found",
            "--no-color",
            *context.extra_args,
        ]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        text_parts = [process.stdout]
        output_file = context.raw_dir / "sherlock.txt"
        if output_file.exists():
            text_parts.append(output_file.read_text(encoding="utf-8", errors="replace"))
        text = strip_ansi("\n".join(text_parts))
        findings: list[Finding] = []
        seen: set[str] = set()
        for line in text.splitlines():
            for match in URL_RE.findall(line):
                url = match.rstrip(".,;:)")
                if url in seen:
                    continue
                seen.add(url)
                host = urlsplit(url).hostname or "Profile"
                site_hint = line.split(":", 1)[0].lstrip("[+] ").strip()
                title = site_hint if site_hint and len(site_hint) < 80 else host
                reference = parse_public_profile_url(url)
                attributes = {"host": host, "username": context.target}
                if reference:
                    attributes.update(
                        {"platform": reference.platform, "username": reference.username}
                    )
                findings.append(
                    Finding(
                        plugin_id=self.plugin_id,
                        category="Profiles",
                        kind="profile",
                        title=title,
                        value=url,
                        url=url,
                        source_confidence=0.78,
                        attributes=attributes,
                        evidence_path=str(
                            output_file if output_file.exists() else process.stdout_path
                        ),
                    )
                )
        return findings


PLUGIN_CLASS = SherlockPlugin
