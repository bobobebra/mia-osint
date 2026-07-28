from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from mia import __version__
from mia.cache import ResultCache
from mia.config import AppConfig
from mia.db import ScanDatabase
from mia.exceptions import PluginError
from mia.models import PluginContext, PluginRunResult, ScanProfile, ScanResult, TargetType
from mia.normalizer import merge_findings
from mia.plugin import ExternalCommandPlugin
from mia.process import ProcessRunner
from mia.registry import PluginRegistry
from mia.reports import ReportWriter
from mia.utils import create_scan_directory, new_scan_id, update_latest_symlink
from mia.workspace import CaseWorkspace

EventCallback = Callable[[str, str, str], None]


class Orchestrator:
    def __init__(
        self,
        config: AppConfig,
        registry: PluginRegistry,
        database: ScanDatabase,
        logger: logging.Logger,
        cache: ResultCache | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.database = database
        self.logger = logger
        self.runner = ProcessRunner(config.execution.max_capture_bytes)
        self.report_writer = ReportWriter(config.reports)
        self.cache = cache or ResultCache(config.paths.cache_database_path)

    def select_plugins(
        self,
        target_type: TargetType,
        profile: ScanProfile,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> list[object]:
        include_set = set(include or [])
        exclude_set = set(exclude or [])
        unknown = (include_set | exclude_set) - set(self.registry.ids())
        if unknown:
            raise PluginError(f"unknown plugin(s): {', '.join(sorted(unknown))}")
        selected = []
        for plugin in self.registry.all():
            if not plugin.supports(target_type):
                continue
            if plugin.plugin_id in exclude_set:
                continue
            tool = self.config.tool(plugin.plugin_id)
            if not tool.enabled:
                continue
            if include_set:
                if plugin.plugin_id not in include_set:
                    continue
            else:
                if not self.config.enabled_for_profile(plugin.plugin_id, profile):
                    continue
                # Optional integrations are skipped silently when unavailable.
                if isinstance(plugin, ExternalCommandPlugin):
                    if not plugin.resolve_executable(self.config):
                        continue
                elif not plugin.detect(self.config).available:
                    continue
            selected.append(plugin)
        return selected

    async def scan(
        self,
        target: str,
        target_type: TargetType,
        profile: ScanProfile,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        event_callback: EventCallback | None = None,
        *,
        workspace: CaseWorkspace | None = None,
        depth: int = 0,
        parent_scan_id: str | None = None,
        pivot_source_node_id: str | None = None,
        use_cache: bool | None = None,
    ) -> ScanResult:
        started = datetime.now(UTC)
        scan_id = new_scan_id()
        scan_dir = (
            workspace.scan_directory(scan_id)
            if workspace is not None
            else create_scan_directory(self.config.paths.output_dir, target, scan_id)
        )
        selected = self.select_plugins(target_type, profile, include, exclude)
        result = ScanResult(
            mia_version=__version__,
            scan_id=scan_id,
            target=target,
            target_type=target_type,
            profile=profile,
            started_at=started,
            output_dir=str(scan_dir),
            requested_plugins=[plugin.plugin_id for plugin in selected],
            case_id=workspace.record.case_id if workspace else None,
            case_name=workspace.record.name if workspace else None,
            depth=depth,
            parent_scan_id=parent_scan_id,
            pivot_source_node_id=pivot_source_node_id,
        )
        if not selected:
            result.warnings.append("No enabled plugins support this target and profile")

        semaphore = asyncio.Semaphore(self.config.execution.max_concurrency)
        cache_enabled = self.config.execution.cache.enabled if use_cache is None else use_cache

        async def run_plugin(plugin: object) -> PluginRunResult:
            plugin_id = plugin.plugin_id
            if event_callback:
                event_callback("start", plugin_id, plugin.name)
            tool_config = self.config.tool(plugin_id)
            timeout = tool_config.timeout or self.config.execution.default_timeout
            extra_args = tool_config.args_for(profile)
            context = PluginContext(
                scan_id=scan_id,
                target=target,
                target_type=target_type,
                profile=profile,
                scan_dir=scan_dir,
                raw_dir=scan_dir / "raw" / plugin_id,
                timeout_seconds=timeout,
                extra_args=extra_args,
            )
            cache_key = self.cache.key(plugin_id, target, target_type, profile, extra_args)
            if cache_enabled:
                ttl = (
                    self.config.execution.cache.api_ttl_seconds
                    if plugin_id.startswith("api-")
                    else self.config.execution.cache.ttl_seconds
                )
                cached = self.cache.get(
                    cache_key,
                    ttl,
                    reuse_failed=self.config.execution.cache.reuse_failed,
                )
                if cached is not None:
                    if event_callback:
                        event_callback("finish", plugin_id, "cached")
                    return cached
            async with semaphore:
                run = await plugin.execute(context, self.config, self.runner)
            if cache_enabled:
                self.cache.put(
                    cache_key,
                    scan_id,
                    run,
                    target=target,
                    target_type=target_type,
                    profile=profile,
                )
            if event_callback:
                event_callback("finish", plugin_id, run.status.value)
            return run

        plugin_runs = await asyncio.gather(*(run_plugin(plugin) for plugin in selected))
        result.plugin_runs = list(plugin_runs)
        all_findings = [finding for run in plugin_runs for finding in run.findings]
        result.findings = merge_findings(
            all_findings,
            self.config.confidence,
            keep_negative=self.config.execution.keep_negative_findings,
        )
        finished = datetime.now(UTC)
        result.finished_at = finished
        result.duration_seconds = (finished - started).total_seconds()
        self.report_writer.write(result)
        self.database.save(result)
        if workspace is not None:
            workspace.save_scan(result)
        elif self.config.reports.create_latest_symlink:
            update_latest_symlink(scan_dir)
        self.logger.info(
            "Scan %s completed with %d normalized findings", result.scan_id, len(result.findings)
        )
        return result
