from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from mia.config import AppConfig, ToolConfig
from mia.models import (
    Finding,
    PluginContext,
    PluginRunResult,
    PluginRunStatus,
    ProcessResult,
    TargetType,
    ToolStatus,
)
from mia.platform_support import (
    popen_platform_kwargs,
    prepare_subprocess_command,
    prepend_managed_bin,
)
from mia.process import ProcessRunner
from mia.utils import atomic_write_json


class BasePlugin(ABC):
    """Stable plugin contract for built-in and third-party adapters."""

    plugin_id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    target_types: ClassVar[frozenset[TargetType]] = frozenset()
    network_required: ClassVar[bool] = True
    homepage: ClassVar[str | None] = None

    def supports(self, target_type: TargetType) -> bool:
        return target_type in self.target_types

    def tool_config(self, config: AppConfig) -> ToolConfig:
        return config.tool(self.plugin_id)

    def detect(self, config: AppConfig) -> ToolStatus:
        tool = self.tool_config(config)
        return ToolStatus(
            plugin_id=self.plugin_id,
            name=self.name,
            available=tool.enabled,
            message="built-in plugin" if tool.enabled else "disabled in configuration",
            install_hint=tool.install_hint,
        )

    @abstractmethod
    async def execute(
        self, context: PluginContext, config: AppConfig, runner: ProcessRunner
    ) -> PluginRunResult:
        raise NotImplementedError


class ExternalCommandPlugin(BasePlugin):
    """Base class for adapters that invoke a separate executable."""

    executable_candidates: ClassVar[tuple[str, ...]] = ()
    version_arguments: ClassVar[tuple[str, ...]] = ("--version",)
    version_signatures: ClassVar[tuple[str, ...]] = ()

    def managed_executable(self, config: AppConfig) -> str | None:
        state_path = config.paths.state_dir / "package-state.json"
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            record = (payload.get("packages") or {}).get(self.plugin_id) or {}
            executable = record.get("executable")
            if executable:
                path = Path(str(executable)).expanduser()
                if path.is_file():
                    return str(path.resolve())
        except (OSError, ValueError, TypeError, AttributeError):
            return None
        return None

    def resolve_executable(self, config: AppConfig) -> str | None:
        configured = self.tool_config(config).executable
        managed = self.managed_executable(config)
        candidates = [configured] if configured else []
        if managed:
            candidates.append(managed)
        candidates.extend(self.executable_candidates)
        for candidate in candidates:
            if not candidate:
                continue
            expanded = str(Path(candidate).expanduser())
            if any(separator in expanded for separator in ("/", "\\")):
                path = Path(expanded)
                if path.exists() and path.is_file():
                    return str(path.resolve())
            found = shutil.which(expanded)
            if found:
                return found
        return None

    def command_prefix(self, executable: str) -> list[str]:
        return [sys.executable, executable] if executable.lower().endswith(".py") else [executable]

    def probe_version(self, executable: str) -> str | None:
        try:
            command = [*self.command_prefix(executable), *self.version_arguments]
            completed = subprocess.run(
                prepare_subprocess_command(command),
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                env={**prepend_managed_bin(), "NO_COLOR": "1", "TERM": "dumb"},
                **popen_platform_kwargs(hidden=True),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        return output[:1000] if output else None

    def executable_identity_ok(self, version: str | None) -> bool:
        if not self.version_signatures:
            return True
        if not version:
            return False
        return any(
            re.search(pattern, version, re.IGNORECASE) for pattern in self.version_signatures
        )

    def detect(self, config: AppConfig) -> ToolStatus:
        tool = self.tool_config(config)
        if not tool.enabled:
            return ToolStatus(
                plugin_id=self.plugin_id,
                name=self.name,
                available=False,
                message="disabled in configuration",
                install_hint=tool.install_hint,
            )
        executable = self.resolve_executable(config)
        if not executable:
            return ToolStatus(
                plugin_id=self.plugin_id,
                name=self.name,
                available=False,
                message="executable not found",
                install_hint=tool.install_hint,
            )
        version = self.probe_version(executable)
        if not self.executable_identity_ok(version):
            expected = ", ".join(self.version_signatures)
            return ToolStatus(
                plugin_id=self.plugin_id,
                name=self.name,
                available=False,
                executable=executable,
                version=version,
                message=(
                    f"unexpected executable identity; expected version output matching: {expected}"
                ),
                install_hint=tool.install_hint,
            )
        return ToolStatus(
            plugin_id=self.plugin_id,
            name=self.name,
            available=True,
            executable=executable,
            version=version,
            message="ready",
            install_hint=tool.install_hint,
        )

    @abstractmethod
    def build_command(
        self, context: PluginContext, config: AppConfig, executable: str
    ) -> list[str]:
        raise NotImplementedError

    def stdin_data(self, context: PluginContext) -> str | bytes | None:
        return None

    @abstractmethod
    def parse(self, context: PluginContext, process: ProcessResult) -> list[Finding]:
        raise NotImplementedError

    async def execute(
        self, context: PluginContext, config: AppConfig, runner: ProcessRunner
    ) -> PluginRunResult:
        detected = self.detect(config)
        started = datetime.now(UTC)
        context.raw_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not detected.available or not detected.executable:
            finished = datetime.now(UTC)
            return PluginRunResult(
                plugin_id=self.plugin_id,
                plugin_name=self.name,
                status=PluginRunStatus.UNAVAILABLE,
                started_at=started,
                finished_at=finished,
                duration_seconds=(finished - started).total_seconds(),
                raw_dir=str(context.raw_dir),
                error=detected.message,
            )

        command: list[str] = []
        try:
            command = self.build_command(context, config, detected.executable)
            process = await runner.run(
                command,
                context.raw_dir,
                context.timeout_seconds,
                stdin_data=self.stdin_data(context),
            )
            findings = self.parse(context, process)
            atomic_write_json(
                context.raw_dir / "parsed_findings.json",
                [finding.model_dump(mode="json") for finding in findings],
            )
            warnings: list[str] = []
            if process.return_code not in (0, None):
                warnings.append(f"tool exited with status {process.return_code}")
            if process.output_truncated:
                warnings.append(
                    "raw output exceeded the configured capture limit and was truncated"
                )

            if process.timed_out:
                status = PluginRunStatus.TIMED_OUT
            elif process.return_code == 0:
                status = PluginRunStatus.SUCCESS
            elif findings:
                status = PluginRunStatus.PARTIAL
            else:
                status = PluginRunStatus.FAILED
            return PluginRunResult(
                plugin_id=self.plugin_id,
                plugin_name=self.name,
                status=status,
                started_at=process.started_at,
                finished_at=process.finished_at,
                duration_seconds=process.duration_seconds,
                command=command,
                return_code=process.return_code,
                timed_out=process.timed_out,
                output_truncated=process.output_truncated,
                raw_dir=str(context.raw_dir),
                stdout_path=process.stdout_path,
                stderr_path=process.stderr_path,
                findings=findings,
                error="process timed out" if process.timed_out else None,
                warnings=warnings,
            )
        except Exception as exc:
            finished = datetime.now(UTC)
            atomic_write_json(
                context.raw_dir / "plugin_error.json",
                {"plugin": self.plugin_id, "error": f"{type(exc).__name__}: {exc}"},
            )
            return PluginRunResult(
                plugin_id=self.plugin_id,
                plugin_name=self.name,
                status=PluginRunStatus.FAILED,
                started_at=started,
                finished_at=finished,
                duration_seconds=(finished - started).total_seconds(),
                command=command,
                raw_dir=str(context.raw_dir),
                error=f"{type(exc).__name__}: {exc}",
            )


class PythonModulePlugin(ExternalCommandPlugin):
    """External plugin whose primary dependency is an importable Python package."""

    module_name: ClassVar[str]

    def module_available(self) -> bool:
        return importlib.util.find_spec(self.module_name) is not None

    def detect(self, config: AppConfig) -> ToolStatus:
        tool = self.tool_config(config)
        if not tool.enabled:
            return ToolStatus(
                plugin_id=self.plugin_id,
                name=self.name,
                available=False,
                message="disabled in configuration",
                install_hint=tool.install_hint,
            )
        if self.module_available():
            return ToolStatus(
                plugin_id=self.plugin_id,
                name=self.name,
                available=True,
                executable=sys.executable,
                message=f"Python module {self.module_name} is importable",
                install_hint=tool.install_hint,
            )
        return super().detect(config)
