"""Minimal third-party MIA plugin example."""

from __future__ import annotations

from mia.config import AppConfig
from mia.models import Finding, PluginContext, ProcessResult, TargetType
from mia.plugin import ExternalCommandPlugin


class ExamplePlugin(ExternalCommandPlugin):
    plugin_id = "example"
    name = "Example tool"
    target_types = frozenset({TargetType.USERNAME})
    executable_candidates = ("example-tool",)

    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        return [*self.command_prefix(executable), "--json", context.target]

    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        # Parse process.stdout or files in context.raw_dir.
        return []
