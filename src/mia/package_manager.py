from __future__ import annotations

import contextlib
import os
import platform
import queue
import shlex
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from mia.exceptions import MIAError
from mia.platform_support import (
    is_windows,
    managed_command_path,
    platform_paths,
    popen_platform_kwargs,
    prepare_subprocess_command,
    resolve_venv_command,
    subprocess_creationflags,
    subprocess_startupinfo,
    terminate_process_tree,
    venv_python,
)
from mia.utils import atomic_write_json


class PackageError(MIAError):
    """Raised when an optional OSINT package operation fails."""


InstallKind = Literal[
    "python",
    "go",
    "cargo",
    "system",
    "git_python_script",
    "uv_project",
    "holehe",
    "spiderfoot",
    "download_archive",
    "git_script",
]
IntegrationLevel = Literal["full", "raw", "managed-only"]
RiskLevel = Literal["local", "passive", "mixed"]
EventKind = Literal["command_start", "output", "heartbeat", "command_end"]


class InstallSpec(BaseModel):
    kind: InstallKind
    package: str | None = None
    python: str | None = None
    executable: str
    module: str | None = None
    crate: str | None = None
    repo: str | None = None
    ref: str | None = None
    script: str | None = None
    requirements: str | None = None
    packages: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    urls: dict[str, str] = Field(default_factory=dict)
    archive: str | None = None
    binary_path: str | None = None
    runtime: str | None = None
    runtime_packages: dict[str, str] = Field(default_factory=dict)


class ToolPackage(BaseModel):
    tool_id: str
    name: str
    description: str
    homepage: str
    license: str
    categories: list[str] = Field(default_factory=list)
    target_types: list[str] = Field(default_factory=list)
    integration: IntegrationLevel = "managed-only"
    risk: RiskLevel = "passive"
    api_keys: list[str] = Field(default_factory=list)
    setup_required: bool = False
    unmaintained: bool = False
    detect_args: list[str] = Field(default_factory=lambda: ["--version"])
    detect_signatures: list[str] = Field(default_factory=list)
    install: InstallSpec

    @field_validator("categories", "target_types", "api_keys")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class PackageCatalog(BaseModel):
    schema_version: int
    notes: str = ""
    groups: dict[str, list[str]] = Field(default_factory=dict)
    tools: dict[str, ToolPackage]


class InstalledPackage(BaseModel):
    tool_id: str
    method: str
    installed_at: datetime
    updated_at: datetime
    executable: str | None = None
    managed_root: str | None = None
    system_manager: str | None = None
    system_package: str | None = None
    source: str | None = None


class PackageState(BaseModel):
    schema_version: int = 1
    packages: dict[str, InstalledPackage] = Field(default_factory=dict)


class OperationResult(BaseModel):
    tool_id: str
    action: str
    success: bool
    message: str
    commands: list[list[str]] = Field(default_factory=list)
    outcome: str = "completed"
    duration_seconds: float = 0.0
    log_path: str | None = None


@dataclass(frozen=True, slots=True)
class PackageEvent:
    """A progress event emitted while a package command is running."""

    kind: EventKind
    tool_id: str | None
    action: str | None
    message: str = ""
    command: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0
    return_code: int | None = None
    log_path: str | None = None


CommandRunner = Callable[[list[str], dict[str, str] | None], subprocess.CompletedProcess[str]]
EventHandler = Callable[[PackageEvent], None]


def load_catalog() -> PackageCatalog:
    path = files("mia.data").joinpath("tool_catalog.yaml")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_tools = payload.get("tools", {})
    payload["tools"] = {
        tool_id: {"tool_id": tool_id, **spec} for tool_id, spec in raw_tools.items()
    }
    return PackageCatalog.model_validate(payload)


def default_state_dir() -> Path:
    explicit = os.getenv("MIA_STATE_DIR")
    return Path(explicit).expanduser() if explicit else platform_paths().state_dir


def default_bin_dir() -> Path:
    explicit = os.getenv("MIA_BIN_DIR")
    if explicit:
        return Path(explicit).expanduser()
    if is_windows():
        return platform_paths().bin_dir
    local_bin = Path("~/.local/bin").expanduser()
    home_bin = Path("~/bin").expanduser()
    path_parts = os.getenv("PATH", "").split(os.pathsep)
    if str(local_bin) not in path_parts and str(home_bin) in path_parts:
        return home_bin
    return local_bin


SUPPORTED_PACKAGE_MANAGERS = frozenset(
    {"apt", "dnf", "pacman", "zypper", "apk", "brew", "winget", "none"}
)


def normalize_package_manager(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "manual":
        normalized = "none"
    if normalized not in SUPPORTED_PACKAGE_MANAGERS:
        supported = ", ".join(sorted(SUPPORTED_PACKAGE_MANAGERS | {"manual"}))
        raise PackageError(f"unsupported package manager {value!r}; choose one of: {supported}")
    return normalized


def detect_package_manager() -> str:
    forced = os.getenv("MIA_PACKAGE_MANAGER")
    if forced and forced != "auto":
        return normalize_package_manager(forced)
    immutable = shutil.which("rpm-ostree") is not None
    if immutable and shutil.which("brew"):
        return "brew"
    candidates = (
        ("winget", "winget"),
        ("apt-get", "apt"),
        ("dnf", "dnf"),
        ("pacman", "pacman"),
        ("zypper", "zypper"),
        ("apk", "apk"),
        ("brew", "brew"),
    )
    for executable, manager in candidates:
        if shutil.which(executable):
            return manager
    return "none"


class PackageManager:
    """Install isolated optional OSINT tools from a reviewed static catalog.

    Catalog entries are data, never arbitrary shell snippets. Every command is
    executed without a shell, and tool-owned files are kept under one state root.
    """

    def __init__(
        self,
        *,
        catalog: PackageCatalog | None = None,
        state_dir: Path | None = None,
        bin_dir: Path | None = None,
        package_manager: str | None = None,
        dry_run: bool = False,
        allow_system: bool = True,
        runner: CommandRunner | None = None,
        event_handler: EventHandler | None = None,
        heartbeat_seconds: float = 3.0,
    ) -> None:
        self.catalog = catalog or load_catalog()
        self.state_dir = (state_dir or default_state_dir()).expanduser()
        self.tools_dir = self.state_dir / "packages"
        self.bin_dir = (bin_dir or default_bin_dir()).expanduser()
        self.state_path = self.state_dir / "package-state.json"
        self.package_manager = normalize_package_manager(
            package_manager or detect_package_manager()
        )
        self.dry_run = dry_run
        self.allow_system = allow_system
        self._runner = runner or self._default_runner
        self._uses_default_runner = runner is None
        self._event_handler = event_handler
        self.heartbeat_seconds = max(0.5, heartbeat_seconds)
        self._commands: list[list[str]] = []
        self._active_tool_id: str | None = None
        self._active_action: str | None = None
        self.operation_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        self.log_dir = self.state_dir / "package-logs" / self.operation_id

    @staticmethod
    def _default_runner(
        command: list[str], env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            prepare_subprocess_command(command),
            check=False,
            capture_output=True,
            text=True,
            env=env,
            creationflags=subprocess_creationflags(hidden=True),
            startupinfo=subprocess_startupinfo(hidden=True),
        )

    def _emit(
        self,
        kind: EventKind,
        *,
        message: str = "",
        command: list[str] | tuple[str, ...] = (),
        elapsed_seconds: float = 0.0,
        return_code: int | None = None,
        log_path: Path | None = None,
    ) -> None:
        if self._event_handler is None:
            return
        self._event_handler(
            PackageEvent(
                kind=kind,
                tool_id=self._active_tool_id,
                action=self._active_action,
                message=message,
                command=tuple(command),
                elapsed_seconds=elapsed_seconds,
                return_code=return_code,
                log_path=str(log_path) if log_path else None,
            )
        )

    def _tool_log_path(self) -> Path | None:
        if self.dry_run or not self._active_tool_id:
            return None
        self.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.log_dir / f"{self._active_tool_id}.log"
        if not path.exists():
            path.touch(mode=0o600)
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        return path

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        terminate_process_tree(process)

    def _stream_command(
        self,
        command: list[str],
        env: dict[str, str] | None,
        log_path: Path | None,
    ) -> subprocess.CompletedProcess[str]:
        started = time.monotonic()
        output_queue: queue.Queue[str | None] = queue.Queue()
        captured_tail = ""
        try:
            process = subprocess.Popen(
                prepare_subprocess_command(command),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                **popen_platform_kwargs(hidden=True),
            )
        except OSError as exc:
            raise PackageError(f"could not start {command[0]!r}: {exc}") from exc

        def read_output() -> None:
            assert process.stdout is not None
            try:
                for line in iter(process.stdout.readline, ""):
                    output_queue.put(line)
            finally:
                process.stdout.close()
                output_queue.put(None)

        reader = threading.Thread(target=read_output, name="mia-package-output", daemon=True)
        reader.start()
        last_activity = time.monotonic()
        stream_finished = False
        log_handle = log_path.open("a", encoding="utf-8") if log_path else None

        try:
            while not stream_finished or process.poll() is None:
                try:
                    item = output_queue.get(timeout=0.2)
                except queue.Empty:
                    item = ""
                now = time.monotonic()
                if item is None:
                    stream_finished = True
                elif item:
                    captured_tail = (captured_tail + item)[-12000:]
                    if log_handle:
                        log_handle.write(item)
                        log_handle.flush()
                    self._emit(
                        "output",
                        message=item.rstrip("\r\n"),
                        elapsed_seconds=now - started,
                        log_path=log_path,
                    )
                    last_activity = now
                elif now - last_activity >= self.heartbeat_seconds:
                    self._emit(
                        "heartbeat",
                        message="Still working…",
                        elapsed_seconds=now - started,
                        log_path=log_path,
                    )
                    last_activity = now
                if process.poll() is not None and stream_finished:
                    break
        except KeyboardInterrupt:
            self._terminate_process(process)
            elapsed = time.monotonic() - started
            self._emit(
                "command_end",
                message="Interrupted by user",
                command=command,
                elapsed_seconds=elapsed,
                return_code=130,
                log_path=log_path,
            )
            raise
        finally:
            reader.join(timeout=1)
            if log_handle:
                log_handle.close()

        return_code = process.wait()
        return subprocess.CompletedProcess(command, return_code, captured_tail, "")

    def load_state(self) -> PackageState:
        if not self.state_path.exists():
            return PackageState()
        try:
            return PackageState.model_validate_json(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PackageError(f"invalid package state file: {self.state_path}: {exc}") from exc

    def set_event_handler(self, handler: EventHandler | None) -> None:
        self._event_handler = handler

    @property
    def active_log_path(self) -> Path | None:
        return self._tool_log_path()

    def save_state(self, state: PackageState) -> None:
        if self.dry_run:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write_json(self.state_path, state.model_dump(mode="json"))
        with contextlib.suppress(OSError):
            self.state_path.chmod(0o600)

    def resolve(self, names: Iterable[str] = (), groups: Iterable[str] = ()) -> list[ToolPackage]:
        selected: list[str] = []
        for group in groups:
            try:
                selected.extend(self.catalog.groups[group])
            except KeyError as exc:
                available = ", ".join(sorted(self.catalog.groups))
                raise PackageError(
                    f"unknown package group {group!r}; choose from: {available}"
                ) from exc
        selected.extend(names)
        if not selected:
            raise PackageError("select at least one tool or package group")
        resolved: list[ToolPackage] = []
        for tool_id in dict.fromkeys(selected):
            try:
                resolved.append(self.catalog.tools[tool_id])
            except KeyError as exc:
                raise PackageError(f"unknown OSINT tool package: {tool_id}") from exc
        return resolved

    def all_tools(self, *, include_mixed: bool = False) -> list[ToolPackage]:
        return [
            tool for tool in self.catalog.tools.values() if include_mixed or tool.risk != "mixed"
        ]

    def platform_compatibility(self, tool: ToolPackage) -> tuple[bool, str]:
        """Return whether MIA can manage this tool on the current host."""

        if not is_windows():
            return True, "native"
        spec = tool.install
        if spec.kind == "system":
            return (
                (True, "winget")
                if spec.packages.get("winget")
                else (False, "no reviewed Windows package mapping")
            )
        if spec.kind == "download_archive":
            key = self._platform_key()
            return (
                (True, "native Windows release")
                if spec.urls.get(key)
                else (False, "upstream does not publish a matching Windows asset")
            )
        if spec.kind == "git_script" and spec.runtime:
            if shutil.which(spec.runtime) or spec.runtime_packages.get("winget"):
                return True, "requires an external runtime"
            return False, f"required runtime {spec.runtime!r} has no reviewed Windows installer"
        if spec.kind in {
            "python",
            "holehe",
            "spiderfoot",
            "git_python_script",
            "uv_project",
            "go",
            "cargo",
        }:
            return True, "managed Windows environment"
        return False, "installation recipe has not been validated on Windows"

    @staticmethod
    def _identity_matches(tool: ToolPackage, executable: str) -> bool:
        if not tool.detect_signatures:
            return True
        try:
            command = [executable, *tool.detect_args]
            completed = subprocess.run(
                prepare_subprocess_command(command),
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
                env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"},
                creationflags=subprocess_creationflags(hidden=True),
                startupinfo=subprocess_startupinfo(hidden=True),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        return any(signature.lower() in output.lower() for signature in tool.detect_signatures)

    def status(self, tool: ToolPackage) -> tuple[bool, str | None, str]:
        state = self.load_state()
        record = state.packages.get(tool.tool_id)
        if record and record.executable:
            expanded = Path(record.executable).expanduser()
            if expanded.exists():
                if self._identity_matches(tool, str(expanded)):
                    return True, str(expanded), "managed"
                return False, str(expanded), "managed executable identity mismatch"
        candidate = tool.install.executable
        expanded = Path(candidate).expanduser()
        if expanded.is_absolute() and expanded.exists():
            executable = str(expanded)
        else:
            executable = shutil.which(candidate)
        if executable and self._identity_matches(tool, executable):
            return True, executable, "PATH"
        if executable:
            return False, executable, "wrong executable identity"
        return False, None, "not found"

    def _run(self, command: list[str], *, env: dict[str, str] | None = None) -> None:
        display_command = command
        if env is not None:
            changes = [
                f"{key}={value}"
                for key, value in sorted(env.items())
                if os.environ.get(key) != value
            ]
            if changes:
                display_command = ["env", *changes, *command]
        self._commands.append(display_command)
        if self.dry_run:
            return
        log_path = self._tool_log_path()
        if log_path:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"\n[{datetime.now(UTC).isoformat()}] $ {shlex.join(display_command)}\n"
                )
        started = time.monotonic()
        self._emit(
            "command_start",
            message=f"Running {command[0]}",
            command=display_command,
            log_path=log_path,
        )
        try:
            if self._uses_default_runner:
                completed = self._stream_command(command, env, log_path)
            else:
                completed = self._runner(command, env)
                combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
                if combined:
                    if log_path:
                        with log_path.open("a", encoding="utf-8") as handle:
                            handle.write(combined)
                            if not combined.endswith("\n"):
                                handle.write("\n")
                    for line in combined.splitlines():
                        self._emit(
                            "output",
                            message=line,
                            elapsed_seconds=time.monotonic() - started,
                            log_path=log_path,
                        )
        except PackageError as exc:
            self._emit(
                "command_end",
                message=str(exc),
                command=display_command,
                elapsed_seconds=time.monotonic() - started,
                return_code=127,
                log_path=log_path,
            )
            raise
        except OSError as exc:
            self._emit(
                "command_end",
                message=str(exc),
                command=display_command,
                elapsed_seconds=time.monotonic() - started,
                return_code=127,
                log_path=log_path,
            )
            raise PackageError(f"could not execute {command[0]!r}: {exc}") from exc
        elapsed = time.monotonic() - started
        self._emit(
            "command_end",
            message=("Command completed" if completed.returncode == 0 else "Command failed"),
            command=display_command,
            elapsed_seconds=elapsed,
            return_code=completed.returncode,
            log_path=log_path,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            if len(detail) > 1200:
                detail = detail[-1200:]
            raise PackageError(
                f"command failed ({completed.returncode}): {' '.join(command)}"
                + (f"\n{detail}" if detail else "")
            )

    def _sudo_prefix(self) -> list[str]:
        if is_windows():
            return []
        if os.geteuid() == 0:
            return []
        sudo = shutil.which("sudo")
        if not sudo:
            if self.dry_run:
                return ["sudo"]
            raise PackageError(
                "this package requires a system package manager, but sudo is unavailable"
            )
        return [sudo]

    def _system_install_command(self, package: str) -> list[str]:
        prefix = self._sudo_prefix() if self.package_manager != "brew" else []
        commands = {
            "apt": [*prefix, "apt-get", "install", "-y", package],
            "dnf": [*prefix, "dnf", "install", "-y", package],
            "pacman": [*prefix, "pacman", "-S", "--needed", "--noconfirm", package],
            "zypper": [*prefix, "zypper", "--non-interactive", "install", package],
            "apk": [*prefix, "apk", "add", "--no-cache", package],
            "brew": ["brew", "install", package],
            "winget": [
                "winget",
                "install",
                "--id",
                package,
                "--exact",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
        }
        try:
            return commands[self.package_manager]
        except KeyError as exc:
            raise PackageError(
                "no supported system package manager was detected; install the prerequisite manually"
            ) from exc

    def _system_remove_command(self, package: str) -> list[str]:
        prefix = self._sudo_prefix() if self.package_manager != "brew" else []
        commands = {
            "apt": [*prefix, "apt-get", "remove", "-y", package],
            "dnf": [*prefix, "dnf", "remove", "-y", package],
            "pacman": [*prefix, "pacman", "-R", "--noconfirm", package],
            "zypper": [*prefix, "zypper", "--non-interactive", "remove", package],
            "apk": [*prefix, "apk", "del", package],
            "brew": ["brew", "uninstall", package],
            "winget": [
                "winget",
                "uninstall",
                "--id",
                package,
                "--exact",
                "--disable-interactivity",
            ],
        }
        try:
            return commands[self.package_manager]
        except KeyError as exc:
            raise PackageError("cannot remove system package without a supported manager") from exc

    def _ensure_command(self, executable: str, package_map: dict[str, str]) -> None:
        if shutil.which(executable):
            return
        if self.dry_run and (not self.allow_system or not package_map.get(self.package_manager)):
            self._commands.append(["manual-prerequisite", executable])
            return
        if not self.allow_system:
            raise PackageError(f"required command {executable!r} is missing (--no-system was used)")
        package = package_map.get(self.package_manager)
        if not package:
            raise PackageError(
                f"required command {executable!r} is missing and no package is known for {self.package_manager}"
            )
        self._run(self._system_install_command(package))

    def _uv(self) -> str:
        executable_dir = Path(sys.executable).resolve().parent
        candidates = [
            shutil.which("uv"),
            str(executable_dir / ("uv.exe" if is_windows() else "uv")),
            str(executable_dir / "uv"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return str(candidate)
        if self.dry_run:
            return "uv"
        raise PackageError("uv is unavailable; reinstall MIA or install uv first")

    def _require_created(self, path: Path, label: str) -> None:
        if self.dry_run:
            return
        if not path.exists():
            raise PackageError(f"{label} was not created at expected path: {path}")

    def _link(self, source: Path, destination: Path) -> Path:
        destination = (
            managed_command_path(self.bin_dir, destination.name) if is_windows() else destination
        )
        if self.dry_run:
            if is_windows():
                self._commands.append(["create-command-shim", str(source), str(destination)])
            else:
                self._commands.append(["ln", "-sfn", str(source), str(destination)])
            return destination
        self.bin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() and destination.resolve() == source.resolve():
                return destination
            backup = (
                self.state_dir / "package-backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            )
            backup.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.move(str(destination), backup / destination.name)
        if is_windows():
            destination.write_text(
                '@echo off\r\nREM Managed by MIA package manager. Do not edit in place.\r\n"'
                + str(source)
                + '" %*\r\n',
                encoding="utf-8",
            )
        else:
            destination.symlink_to(source)
        return destination

    def _write_wrapper(
        self,
        destination: Path,
        lines: list[str],
        *,
        windows_command: list[str] | None = None,
        working_directory: Path | None = None,
    ) -> Path:
        destination = (
            managed_command_path(self.bin_dir, destination.name) if is_windows() else destination
        )
        if is_windows():
            if windows_command is None:
                raise PackageError("catalog installer did not provide a Windows command wrapper")
            command_line = subprocess.list2cmdline(windows_command) + " %*"
            content_lines = [
                "@echo off",
                "REM Managed by MIA package manager. Do not edit in place.",
            ]
            if working_directory is not None:
                content_lines.append(f'cd /d "{working_directory}"')
            content_lines.append(command_line)
            content = "\r\n".join(content_lines) + "\r\n"
        else:
            content = (
                "#!/usr/bin/env bash\n"
                "# Managed by MIA package manager. Do not edit in place.\n"
                "set -euo pipefail\n" + "\n".join(lines) + "\n"
            )
        if self.dry_run:
            self._commands.append(["write-wrapper", str(destination)])
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination.write_text(content, encoding="utf-8")
        if not is_windows():
            destination.chmod(0o755)
        return destination

    def _python_install(self, tool: ToolPackage, root: Path) -> Path:
        spec = tool.install
        if not spec.package or not spec.python:
            raise PackageError(f"catalog error for {tool.tool_id}: Python package/version missing")
        uv = self._uv()
        venv = root / "venv"
        self._run([uv, "venv", "--python", spec.python, str(venv)])
        self._run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(venv_python(venv)),
                "--upgrade",
                spec.package,
            ]
        )
        executable = resolve_venv_command(venv, spec.executable)
        self._require_created(executable, f"{tool.name} executable")
        return self._link(executable, self.bin_dir / spec.executable)

    def _go_install(self, tool: ToolPackage, root: Path) -> Path:
        spec = tool.install
        if not spec.module:
            raise PackageError(f"catalog error for {tool.tool_id}: Go module missing")
        self._ensure_command(
            "go",
            {
                "apt": "golang-go",
                "dnf": "golang",
                "pacman": "go",
                "zypper": "go",
                "apk": "go",
                "brew": "go",
                "winget": "GoLang.Go",
            },
        )
        output_bin = root / "bin"
        if not self.dry_run:
            output_bin.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = {**os.environ, **spec.env, "GOBIN": str(output_bin)}
        self._run(["go", "install", spec.module], env=env)
        executable = output_bin / (f"{spec.executable}.exe" if is_windows() else spec.executable)
        self._require_created(executable, f"{tool.name} executable")
        return self._link(executable, self.bin_dir / spec.executable)

    def _cargo_install(self, tool: ToolPackage, root: Path) -> Path:
        spec = tool.install
        if not spec.crate:
            raise PackageError(f"catalog error for {tool.tool_id}: Cargo crate missing")
        self._ensure_command(
            "cargo",
            {
                "apt": "cargo",
                "dnf": "cargo",
                "pacman": "rust",
                "zypper": "cargo",
                "apk": "cargo",
                "brew": "rust",
                "winget": "Rustlang.Rustup",
            },
        )
        cargo_root = root / "cargo"
        env = {**os.environ, "CARGO_INSTALL_ROOT": str(cargo_root)}
        self._run(["cargo", "install", "--locked", spec.crate], env=env)
        executable = (
            cargo_root / "bin" / (f"{spec.executable}.exe" if is_windows() else spec.executable)
        )
        self._require_created(executable, f"{tool.name} executable")
        return self._link(executable, self.bin_dir / spec.executable)

    def _git_clone(self, repo: str, ref: str | None, destination: Path) -> None:
        self._ensure_command(
            "git",
            {
                "apt": "git",
                "dnf": "git",
                "pacman": "git",
                "zypper": "git",
                "apk": "git",
                "brew": "git",
                "winget": "Git.Git",
            },
        )
        command = ["git", "clone", "--depth", "1"]
        if ref:
            command.extend(["--branch", ref])
        command.extend([repo, str(destination)])
        self._run(command)

    def _git_python_script_install(self, tool: ToolPackage, root: Path) -> Path:
        spec = tool.install
        if not all((spec.repo, spec.python, spec.script)):
            raise PackageError(f"catalog error for {tool.tool_id}: incomplete Git/Python recipe")
        source = root / "source"
        self._git_clone(spec.repo, spec.ref, source)
        uv = self._uv()
        venv = root / "venv"
        self._run([uv, "venv", "--python", spec.python, str(venv)])
        if spec.requirements:
            self._run(
                [
                    uv,
                    "pip",
                    "install",
                    "--python",
                    str(venv_python(venv)),
                    "-r",
                    str(source / spec.requirements),
                ]
            )
        script = source / spec.script
        self._require_created(script, f"{tool.name} script")
        return self._write_wrapper(
            self.bin_dir / spec.executable,
            [f'exec "{venv_python(venv)}" "{script}" "$@"'],
            windows_command=[str(venv_python(venv)), str(script)],
        )

    def _uv_project_install(self, tool: ToolPackage, root: Path) -> Path:
        spec = tool.install
        if not all((spec.repo, spec.python)):
            raise PackageError(f"catalog error for {tool.tool_id}: incomplete uv project recipe")
        source = root / "source"
        self._git_clone(spec.repo, spec.ref, source)
        uv = self._uv()
        self._run([uv, "sync", "--project", str(source), "--python", spec.python])
        executable = resolve_venv_command(source / ".venv", spec.executable)
        self._require_created(executable, f"{tool.name} executable")
        return self._link(executable, self.bin_dir / spec.executable)

    def _holehe_install(self, tool: ToolPackage, root: Path) -> Path:
        spec = tool.install
        if not spec.package or not spec.python:
            raise PackageError("catalog error for Holehe")
        uv = self._uv()
        venv = root / "venv"
        self._run([uv, "venv", "--python", spec.python, str(venv)])
        self._run([uv, "pip", "install", "--python", str(venv_python(venv)), spec.package])
        helper_source = files("mia.helpers").joinpath("holehe_runner.py")
        helper = root / "holehe_runner.py"
        if not self.dry_run:
            helper.write_text(helper_source.read_text(encoding="utf-8"), encoding="utf-8")
        self._require_created(helper, "Holehe helper")
        return self._write_wrapper(
            self.bin_dir / spec.executable,
            [f'exec "{venv_python(venv)}" "{helper}" "$@"'],
            windows_command=[str(venv_python(venv)), str(helper)],
        )

    def _spiderfoot_install(self, tool: ToolPackage, root: Path) -> Path:
        spec = tool.install
        if not all((spec.repo, spec.ref, spec.python)):
            raise PackageError("catalog error for SpiderFoot")
        source = root / "source"
        self._git_clone(spec.repo, spec.ref, source)
        uv = self._uv()
        venv = root / "venv"
        self._run([uv, "venv", "--python", spec.python, str(venv)])
        requirements = root / "requirements-mia.txt"
        if self.dry_run:
            self._commands.append(["prepare-spiderfoot-requirements", str(requirements)])
        else:
            lines = (source / "requirements.txt").read_text(encoding="utf-8").splitlines()
            patched = [
                "pyyaml>=6.0,<7" if line.lower().startswith("pyyaml") else line for line in lines
            ]
            requirements.write_text("\n".join(patched) + "\n", encoding="utf-8")
        self._run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(venv_python(venv)),
                "-r",
                str(requirements),
            ]
        )
        entry = source / "sf.py"
        self._require_created(entry, "SpiderFoot entry point")
        return self._write_wrapper(
            self.bin_dir / spec.executable,
            [f'exec "{venv_python(venv)}" "{entry}" "$@"'],
            windows_command=[str(venv_python(venv)), str(entry)],
        )

    @staticmethod
    def _platform_key() -> str:
        system = platform.system().lower()
        machine = platform.machine().lower()
        aliases = {
            "amd64": "x86_64",
            "x64": "x86_64",
            "aarch64": "arm64",
            "armv8": "arm64",
            "armv7l": "armv7",
            "i686": "i386",
        }
        return f"{system}-{aliases.get(machine, machine)}"

    @staticmethod
    def _safe_extract_zip(archive: Path, destination: Path) -> None:
        root = destination.resolve()
        with zipfile.ZipFile(archive) as handle:
            for member in handle.infolist():
                target = (destination / member.filename).resolve()
                unix_mode = (member.external_attr >> 16) & 0o170000
                if not target.is_relative_to(root):
                    raise PackageError(f"unsafe path in archive: {member.filename}")
                if unix_mode == 0o120000:
                    raise PackageError(f"archive symlinks are not allowed: {member.filename}")
            handle.extractall(destination)

    @staticmethod
    def _safe_extract_tar(archive: Path, destination: Path) -> None:
        root = destination.resolve()
        with tarfile.open(archive, "r:*") as handle:
            for member in handle.getmembers():
                target = (destination / member.name).resolve()
                if not target.is_relative_to(root):
                    raise PackageError(f"unsafe path in archive: {member.name}")
                if member.issym() or member.islnk() or member.isdev():
                    raise PackageError(f"unsafe archive member type: {member.name}")
            try:
                handle.extractall(destination, filter="data")
            except TypeError:  # Python versions without extraction filters
                handle.extractall(destination)

    def _download_file(self, url: str, destination: Path) -> None:
        display = ["download", url, str(destination)]
        self._commands.append(display)
        if self.dry_run:
            return
        log_path = self._tool_log_path()
        started = time.monotonic()
        self._emit(
            "command_start", message=f"Downloading {url}", command=display, log_path=log_path
        )
        request = urllib.request.Request(url, headers={"User-Agent": "MIA-OSINT/4"})
        try:
            with (
                urllib.request.urlopen(request, timeout=120) as response,
                destination.open("wb") as output,
            ):
                total = int(response.headers.get("Content-Length") or 0)
                received = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    received += len(chunk)
                    detail = f"Downloaded {received / 1024 / 1024:.1f} MiB" + (
                        f" / {total / 1024 / 1024:.1f} MiB" if total else ""
                    )
                    self._emit(
                        "output",
                        message=detail,
                        elapsed_seconds=time.monotonic() - started,
                        log_path=log_path,
                    )
        except (OSError, urllib.error.URLError) as exc:
            raise PackageError(f"download failed for {url}: {exc}") from exc
        self._emit(
            "command_end",
            message="Download completed",
            command=display,
            elapsed_seconds=time.monotonic() - started,
            return_code=0,
            log_path=log_path,
        )

    def _download_archive_install(self, tool: ToolPackage, root: Path) -> Path:
        spec = tool.install
        key = self._platform_key()
        url = spec.urls.get(key)
        if not url:
            available = ", ".join(sorted(spec.urls))
            raise PackageError(
                f"{tool.name} has no release asset for {key}; supported platforms: {available}"
            )
        suffix = (
            ".tar.gz" if (spec.archive == "tar.gz" or url.endswith((".tar.gz", ".tgz"))) else ".zip"
        )
        archive = root / f"download{suffix}"
        extracted = root / "extracted"
        if not self.dry_run:
            extracted.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._download_file(url, archive)
        if self.dry_run:
            self._commands.append(["extract", str(archive), str(extracted)])
        elif suffix == ".zip":
            self._safe_extract_zip(archive, extracted)
        else:
            self._safe_extract_tar(archive, extracted)
        relative = spec.binary_path or spec.executable
        source = extracted / relative
        if not self.dry_run and not source.exists():
            matches = list(extracted.rglob(Path(relative).name))
            if is_windows() and not matches:
                matches = list(extracted.rglob(f"{Path(relative).name}.exe"))
            if len(matches) == 1:
                source = matches[0]
        self._require_created(source, f"{tool.name} executable")
        destination = root / "bin" / source.name
        if not self.dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(source, destination)
            if not is_windows():
                destination.chmod(0o755)
        else:
            self._commands.append(["install", str(source), str(destination)])
        return self._link(destination, self.bin_dir / spec.executable)

    def _git_script_install(self, tool: ToolPackage, root: Path) -> Path:
        spec = tool.install
        if not all((spec.repo, spec.script)):
            raise PackageError(f"catalog error for {tool.tool_id}: incomplete Git script recipe")
        source = root / "source"
        self._git_clone(spec.repo, spec.ref, source)
        runtime = spec.runtime
        if runtime:
            package_map = spec.runtime_packages or {
                "apt": runtime,
                "dnf": runtime,
                "pacman": runtime,
                "zypper": runtime,
                "apk": runtime,
                "brew": runtime,
            }
            self._ensure_command(runtime, package_map)
        script = source / spec.script
        self._require_created(script, f"{tool.name} script")
        command = f'"{script}" "$@"' if not runtime else f'"{runtime}" "{script}" "$@"'
        windows_command = [str(script)] if not runtime else [runtime, str(script)]
        return self._write_wrapper(
            self.bin_dir / spec.executable,
            [f'cd "{source}"', f"exec {command}"],
            windows_command=windows_command,
            working_directory=source,
        )

    def _system_install(self, tool: ToolPackage) -> tuple[Path, str]:
        spec = tool.install
        if not self.allow_system:
            raise PackageError(f"{tool.name} requires a system package (--no-system was used)")
        package = spec.packages.get(self.package_manager)
        if not package:
            raise PackageError(
                f"no {self.package_manager} package mapping is available for {tool.name}"
            )
        self._run(self._system_install_command(package))
        executable = shutil.which(spec.executable)
        if not executable and not self.dry_run:
            raise PackageError(
                f"{tool.name} package installed but executable {spec.executable!r} was not found on PATH"
            )
        return Path(executable or spec.executable), package

    def install(self, tool: ToolPackage) -> OperationResult:
        supported, support_detail = self.platform_compatibility(tool)
        if not supported:
            raise PackageError(
                f"{tool.name} is unavailable on this Windows build: {support_detail}"
            )
        self._active_tool_id = tool.tool_id
        self._active_action = "install"
        self._commands = []
        installed, executable, source = self.status(tool)
        if installed and source == "managed":
            return OperationResult(
                tool_id=tool.tool_id,
                action="install",
                success=True,
                message=f"already installed at {executable}",
                outcome="already-present",
            )
        root = self.tools_dir / tool.tool_id
        if not self.dry_run:
            if root.exists():
                shutil.rmtree(root)
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.bin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        method = tool.install.kind
        system_package: str | None = None
        try:
            if method == "python":
                installed_path = self._python_install(tool, root)
            elif method == "go":
                installed_path = self._go_install(tool, root)
            elif method == "cargo":
                installed_path = self._cargo_install(tool, root)
            elif method == "git_python_script":
                installed_path = self._git_python_script_install(tool, root)
            elif method == "uv_project":
                installed_path = self._uv_project_install(tool, root)
            elif method == "holehe":
                installed_path = self._holehe_install(tool, root)
            elif method == "spiderfoot":
                installed_path = self._spiderfoot_install(tool, root)
            elif method == "download_archive":
                installed_path = self._download_archive_install(tool, root)
            elif method == "git_script":
                installed_path = self._git_script_install(tool, root)
            elif method == "system":
                installed_path, system_package = self._system_install(tool)
            else:  # pragma: no cover - Pydantic validates this
                raise PackageError(f"unsupported install method: {method}")
        except (Exception, KeyboardInterrupt):
            if not self.dry_run and method != "system":
                shutil.rmtree(root, ignore_errors=True)
            raise

        if not self.dry_run:
            state = self.load_state()
            now = datetime.now(UTC)
            state.packages[tool.tool_id] = InstalledPackage(
                tool_id=tool.tool_id,
                method=method,
                installed_at=now,
                updated_at=now,
                executable=str(installed_path),
                managed_root=str(root) if method != "system" else None,
                system_manager=self.package_manager if method == "system" else None,
                system_package=system_package,
                source=tool.homepage,
            )
            self.save_state(state)
        return OperationResult(
            tool_id=tool.tool_id,
            action="install",
            success=True,
            message=(f"would install {tool.name}" if self.dry_run else f"installed {tool.name}"),
            commands=list(self._commands),
            outcome="planned" if self.dry_run else "installed",
            log_path=str(self._tool_log_path()) if self._tool_log_path() else None,
        )

    @staticmethod
    def _managed_executable_unchanged(record: InstalledPackage, executable: Path) -> bool:
        if executable.is_symlink():
            if not record.managed_root:
                return False
            try:
                return executable.resolve().is_relative_to(
                    Path(record.managed_root).expanduser().resolve()
                )
            except OSError:
                return False
        if executable.is_file():
            try:
                header = executable.read_text(encoding="utf-8", errors="replace")[:256]
            except OSError:
                return False
            return "Managed by MIA package manager" in header
        return not executable.exists()

    def uninstall(self, tool: ToolPackage, *, remove_system: bool = False) -> OperationResult:
        self._active_tool_id = tool.tool_id
        self._active_action = "uninstall"
        self._commands = []
        state = self.load_state()
        record = state.packages.get(tool.tool_id)
        if not record:
            return OperationResult(
                tool_id=tool.tool_id,
                action="uninstall",
                success=True,
                message="not installed by MIA; nothing removed",
                outcome="skipped",
            )
        if record.method == "system":
            if not remove_system:
                return OperationResult(
                    tool_id=tool.tool_id,
                    action="uninstall",
                    success=False,
                    message=(
                        "system package was preserved; repeat with --remove-system-packages "
                        "after reviewing dependencies"
                    ),
                    outcome="preserved",
                )
            if not record.system_package:
                raise PackageError(f"missing recorded system package for {tool.tool_id}")
            self._run(self._system_remove_command(record.system_package))
        else:
            executable = Path(record.executable).expanduser() if record.executable else None
            if executable and (executable.is_symlink() or executable.exists()):
                if not self._managed_executable_unchanged(record, executable):
                    return OperationResult(
                        tool_id=tool.tool_id,
                        action="uninstall",
                        success=False,
                        message=(
                            f"preserved changed command at {executable}; remove it manually or "
                            "restore the MIA-managed link/wrapper before retrying"
                        ),
                        outcome="preserved",
                    )
                if self.dry_run:
                    self._commands.append(["rm", "-f", str(executable)])
                else:
                    executable.unlink(missing_ok=True)
            if record.managed_root:
                root = Path(record.managed_root).expanduser()
                if self.dry_run:
                    self._commands.append(["rm", "-rf", str(root)])
                else:
                    shutil.rmtree(root, ignore_errors=True)
        if not self.dry_run:
            state.packages.pop(tool.tool_id, None)
            self.save_state(state)
        return OperationResult(
            tool_id=tool.tool_id,
            action="uninstall",
            success=True,
            message=f"removed {tool.name}",
            commands=list(self._commands),
            outcome="planned" if self.dry_run else "removed",
            log_path=str(self._tool_log_path()) if self._tool_log_path() else None,
        )

    def update(self, tool: ToolPackage) -> OperationResult:
        self._active_tool_id = tool.tool_id
        self._active_action = "update"
        installed, _, _ = self.status(tool)
        if not installed:
            result = self.install(tool)
            result.action = "update"
            if result.success and result.outcome in {"installed", "planned"}:
                result.message = (
                    f"would install {tool.name} (was absent)"
                    if self.dry_run
                    else f"installed {tool.name} (was absent)"
                )
            return result
        uninstall_result = self.uninstall(tool, remove_system=False)
        if tool.install.kind == "system":
            self._commands = []
            if self.package_manager == "brew":
                self._run(["brew", "upgrade", tool.install.packages.get("brew", tool.tool_id)])
                return OperationResult(
                    tool_id=tool.tool_id,
                    action="update",
                    success=True,
                    message=f"requested update for {tool.name}",
                    commands=list(self._commands),
                    outcome="updated",
                    log_path=str(self._tool_log_path()) if self._tool_log_path() else None,
                )
            return OperationResult(
                tool_id=tool.tool_id,
                action="update",
                success=False,
                message="system-managed tools should be updated with the distribution package manager",
                outcome="preserved",
            )
        if not uninstall_result.success:
            return uninstall_result
        result = self.install(tool)
        result.action = "update"
        if result.outcome == "installed":
            result.outcome = "updated"
        return result

    def inventory(self) -> list[dict[str, Any]]:
        state = self.load_state()
        rows: list[dict[str, Any]] = []
        for tool in sorted(self.catalog.tools.values(), key=lambda item: item.tool_id):
            available, executable, source = self.status(tool)
            record = state.packages.get(tool.tool_id)
            platform_supported, platform_detail = self.platform_compatibility(tool)
            rows.append(
                {
                    "id": tool.tool_id,
                    "name": tool.name,
                    "categories": tool.categories,
                    "integration": tool.integration,
                    "risk": tool.risk,
                    "installed": available,
                    "executable": executable,
                    "source": source,
                    "managed": record is not None,
                    "setup_required": tool.setup_required,
                    "api_keys": tool.api_keys,
                    "unmaintained": tool.unmaintained,
                    "platform_supported": platform_supported,
                    "platform_detail": platform_detail,
                }
            )
        return rows


def host_summary() -> dict[str, str]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "package_manager": detect_package_manager(),
    }
