"""Cross-platform operating-system integration for MIA Core.

All platform-specific path and process behavior belongs here so Discover,
Workbench, scanners, and reports continue to share one implementation.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PlatformPaths:
    config_dir: Path
    data_dir: Path
    state_dir: Path
    log_dir: Path
    cases_dir: Path
    reports_dir: Path
    plugins_dir: Path
    bin_dir: Path


def is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def is_macos() -> bool:
    return sys.platform == "darwin"


def platform_paths() -> PlatformPaths:
    """Return user-owned application paths for the current operating system."""

    home = Path.home()
    if is_windows():
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "MIA"
        roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "MIA"
        return PlatformPaths(
            config_dir=roaming,
            data_dir=local,
            state_dir=local,
            log_dir=local / "logs",
            cases_dir=local / "cases",
            reports_dir=local / "reports",
            plugins_dir=local / "plugins",
            bin_dir=local / "bin",
        )
    if is_macos():
        data = home / "Library" / "Application Support" / "MIA"
        return PlatformPaths(
            config_dir=home / "Library" / "Preferences" / "MIA",
            data_dir=data,
            state_dir=data,
            log_dir=home / "Library" / "Logs" / "MIA",
            cases_dir=data / "cases",
            reports_dir=data / "reports",
            plugins_dir=data / "plugins",
            bin_dir=data / "bin",
        )

    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    state_home = Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state"))
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    data = data_home / "mia"
    return PlatformPaths(
        config_dir=config_home / "mia",
        data_dir=data,
        state_dir=data,
        log_dir=state_home / "mia" / "log",
        cases_dir=home / "mia_cases",
        reports_dir=home / "mia_reports",
        plugins_dir=data / "plugins",
        bin_dir=home / ".local" / "bin",
    )


def venv_scripts_dir(venv: Path) -> Path:
    return venv / ("Scripts" if is_windows() else "bin")


def venv_python(venv: Path) -> Path:
    return venv_scripts_dir(venv) / ("python.exe" if is_windows() else "python")


def executable_filename(name: str) -> str:
    if is_windows() and not Path(name).suffix:
        return f"{name}.exe"
    return name


def managed_command_path(bin_dir: Path, name: str) -> Path:
    """Path used for a MIA-managed command shim."""

    return bin_dir / (f"{name}.cmd" if is_windows() else name)


def prepare_subprocess_command(command: list[str]) -> list[str]:
    """Return a CreateProcess-compatible command without accepting shell text.

    Windows cannot execute ``.cmd`` and ``.bat`` files directly through every
    subprocess API. MIA therefore invokes the operating-system command processor
    only for those explicit file types and quotes the original argument vector
    with :func:`subprocess.list2cmdline`.
    """

    if not command:
        raise ValueError("command cannot be empty")
    suffix = Path(command[0]).suffix.lower()
    if not is_windows() or suffix not in {".cmd", ".bat"}:
        return list(command)
    comspec = os.environ.get("COMSPEC") or str(
        Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "cmd.exe"
    )
    return [comspec, "/d", "/s", "/c", subprocess.list2cmdline(command)]


def resolve_venv_command(venv: Path, name: str) -> Path:
    scripts = venv_scripts_dir(venv)
    candidates = [scripts / name]
    if is_windows():
        candidates = [scripts / f"{name}.exe", scripts / f"{name}.cmd", scripts / name]
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def subprocess_creationflags(*, hidden: bool = True, new_process_group: bool = True) -> int:
    if not is_windows():
        return 0
    flags = 0
    if hidden:
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if new_process_group:
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return flags


def subprocess_startupinfo(*, hidden: bool = True) -> Any | None:
    if not is_windows() or not hidden:
        return None
    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_type is None:
        return None
    startupinfo = startupinfo_type()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return startupinfo


def popen_platform_kwargs(*, hidden: bool = True) -> dict[str, Any]:
    if is_windows():
        return {
            "creationflags": subprocess_creationflags(hidden=hidden),
            "startupinfo": subprocess_startupinfo(hidden=hidden),
        }
    return {"start_new_session": True}


def prepend_managed_bin(env: dict[str, str] | None = None) -> dict[str, str]:
    result = dict(os.environ if env is None else env)
    bin_dir = str(platform_paths().bin_dir)
    current = result.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if bin_dir not in parts:
        result["PATH"] = os.pathsep.join([bin_dir, *parts])
    return result


def activate_managed_bin() -> None:
    """Expose MIA-managed commands to this process and its children."""

    os.environ.update(prepend_managed_bin())


def terminate_process_tree(process: subprocess.Popen[Any], *, grace_seconds: float = 3.0) -> None:
    """Terminate a process and its descendants without invoking a shell."""

    if process.poll() is not None:
        return
    if is_windows():
        taskkill = shutil.which("taskkill") or str(
            Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
        )
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(grace_seconds, 1),
                creationflags=subprocess_creationflags(hidden=True, new_process_group=False),
                startupinfo=subprocess_startupinfo(hidden=True),
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=grace_seconds)
        if process.poll() is None:
            with contextlib.suppress(OSError):
                process.kill()
        return

    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2)
