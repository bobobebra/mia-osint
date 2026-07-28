from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from mia.cli import app
from mia.desktop import install_desktop_entries, remove_desktop_entries

runner = CliRunner()


def test_linux_desktop_entries_are_installed_and_removed(tmp_path: Path, monkeypatch) -> None:
    data_home = tmp_path / "share"
    launcher = tmp_path / "MIA Runtime" / "mia"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))

    status = install_desktop_entries(launcher)

    assert status.discover_installed
    assert status.workbench_installed
    discover = data_home / "applications" / "mia-discover.desktop"
    workbench = data_home / "applications" / "mia-workbench.desktop"
    assert f'Exec="{launcher}" discover' in discover.read_text(encoding="utf-8")
    assert f'Exec="{launcher}" workbench' in workbench.read_text(encoding="utf-8")
    assert (data_home / "icons/hicolor/scalable/apps/mia-discover.svg").is_file()
    assert (data_home / "icons/hicolor/scalable/apps/mia-workbench.svg").is_file()

    removed = remove_desktop_entries()
    assert not removed.discover_installed
    assert not removed.workbench_installed


def test_desktop_cli_status_is_machine_readable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    result = runner.invoke(app, ["desktop", "status", "--json"])
    assert result.exit_code == 0, result.stdout
    assert '"discover_installed": false' in result.stdout
    assert '"workbench_installed": false' in result.stdout


def test_repair_command_checks_core_without_desktop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MIA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MIA_CASES_DIR", str(tmp_path / "cases"))
    monkeypatch.setenv("MIA_OUTPUT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("MIA_CONFIG", str(tmp_path / "config.yaml"))

    result = runner.invoke(app, ["repair", "--no-desktop"])

    assert result.exit_code == 0, result.stdout
    assert "Core application:" in result.stdout
    assert "MIA installation check completed" in result.stdout
