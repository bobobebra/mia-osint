"""Desktop integration helpers for MIA.

The module intentionally contains no UI framework logic.  It installs small,
user-owned Linux desktop entries that invoke the same ``mia`` command used by
the terminal.  This keeps Discover and Workbench on one MIA Core installation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DesktopEntry:
    identifier: str
    name: str
    comment: str
    mode: str
    icon_source: str


@dataclass(frozen=True, slots=True)
class DesktopStatus:
    supported: bool
    applications_dir: Path
    icons_dir: Path
    command: Path | None
    discover_installed: bool
    workbench_installed: bool


ENTRIES = (
    DesktopEntry(
        identifier="mia-discover",
        name="MIA Discover",
        comment="Guided public-source account discovery",
        mode="discover",
        icon_source="web/static_discover/mia-discover-icon.svg",
    ),
    DesktopEntry(
        identifier="mia-workbench",
        name="MIA Workbench",
        comment="Advanced OSINT investigation workspace",
        mode="workbench",
        icon_source="web/static_workbench/mia-workbench-icon.svg",
    ),
)


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()


def _applications_dir() -> Path:
    return _xdg_data_home() / "applications"


def _icons_dir() -> Path:
    return _xdg_data_home() / "icons" / "hicolor" / "scalable" / "apps"


def _resolve_command(command: Path | str | None = None) -> Path | None:
    if command:
        candidate = Path(command).expanduser()
        return candidate.resolve() if candidate.exists() else candidate.absolute()
    override = os.environ.get("MIA_DESKTOP_COMMAND")
    if override:
        candidate = Path(override).expanduser()
        return candidate.resolve() if candidate.exists() else candidate.absolute()
    discovered = shutil.which("mia")
    if discovered:
        return Path(discovered).resolve()
    sibling = Path(sys.executable).resolve().with_name("mia")
    if sibling.exists():
        return sibling
    for candidate in (
        Path("~/.local/bin/mia").expanduser(),
        Path("~/bin/mia").expanduser(),
        Path("~/.local/share/mia/venv/bin/mia").expanduser(),
    ):
        if candidate.exists():
            return candidate.resolve()
    return None


def _desktop_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _entry_text(entry: DesktopEntry, command: Path) -> str:
    return "\n".join(
        (
            "[Desktop Entry]",
            "Type=Application",
            f"Name={entry.name}",
            f"Comment={entry.comment}",
            f"Exec={_desktop_quote(str(command))} {entry.mode}",
            f"Icon={entry.identifier}",
            "Terminal=false",
            "StartupNotify=true",
            "Categories=Network;Utility;",
            f"StartupWMClass={entry.identifier}",
            "X-MIA-Managed=true",
            "",
        )
    )


def _refresh_desktop_database(applications_dir: Path, data_home: Path) -> None:
    commands: list[list[str]] = []
    update_desktop = shutil.which("update-desktop-database")
    if update_desktop:
        commands.append([update_desktop, str(applications_dir)])
    update_icons = shutil.which("gtk-update-icon-cache")
    if update_icons:
        commands.append([update_icons, "-f", "-t", str(data_home / "icons" / "hicolor")])
    for command in commands:
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def install_desktop_entries(command: Path | str | None = None) -> DesktopStatus:
    """Install Discover and Workbench launchers for the current Linux user."""

    if not sys.platform.startswith("linux"):
        raise RuntimeError("desktop shortcut installation is currently supported on Linux only")
    resolved = _resolve_command(command)
    if resolved is None:
        raise RuntimeError("could not locate the installed 'mia' command")

    applications_dir = _applications_dir()
    icons_dir = _icons_dir()
    applications_dir.mkdir(parents=True, exist_ok=True)
    icons_dir.mkdir(parents=True, exist_ok=True)

    package_root = files("mia")
    for entry in ENTRIES:
        source = package_root.joinpath(entry.icon_source)
        with as_file(source) as source_path:
            shutil.copyfile(source_path, icons_dir / f"{entry.identifier}.svg")
        desktop_path = applications_dir / f"{entry.identifier}.desktop"
        desktop_path.write_text(_entry_text(entry, resolved), encoding="utf-8")
        desktop_path.chmod(0o755)

    _refresh_desktop_database(applications_dir, _xdg_data_home())
    return desktop_status(resolved)


def remove_desktop_entries() -> DesktopStatus:
    """Remove only MIA-managed desktop entries and copied application icons."""

    applications_dir = _applications_dir()
    icons_dir = _icons_dir()
    for entry in ENTRIES:
        (applications_dir / f"{entry.identifier}.desktop").unlink(missing_ok=True)
        (icons_dir / f"{entry.identifier}.svg").unlink(missing_ok=True)
    if sys.platform.startswith("linux"):
        _refresh_desktop_database(applications_dir, _xdg_data_home())
    return desktop_status()


def desktop_status(command: Path | str | None = None) -> DesktopStatus:
    applications_dir = _applications_dir()
    icons_dir = _icons_dir()

    def installed(entry: DesktopEntry) -> bool:
        desktop_path = applications_dir / f"{entry.identifier}.desktop"
        icon_path = icons_dir / f"{entry.identifier}.svg"
        return desktop_path.is_file() and icon_path.is_file()

    return DesktopStatus(
        supported=sys.platform.startswith("linux"),
        applications_dir=applications_dir,
        icons_dir=icons_dir,
        command=_resolve_command(command),
        discover_installed=installed(ENTRIES[0]),
        workbench_installed=installed(ENTRIES[1]),
    )
