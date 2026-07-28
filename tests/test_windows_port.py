from __future__ import annotations

from pathlib import Path

from mia import platform_support
from mia.package_manager import PackageManager


def test_windows_application_paths_use_appdata(monkeypatch, tmp_path: Path) -> None:
    local = tmp_path / "Local"
    roaming = tmp_path / "Roaming"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setattr(platform_support, "is_windows", lambda: True)
    monkeypatch.setattr(platform_support, "is_macos", lambda: False)

    paths = platform_support.platform_paths()

    assert paths.config_dir == roaming / "MIA"
    assert paths.state_dir == local / "MIA"
    assert paths.cases_dir == local / "MIA" / "cases"
    assert paths.reports_dir == local / "MIA" / "reports"
    assert paths.bin_dir == local / "MIA" / "bin"


def test_windows_virtual_environment_layout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(platform_support, "is_windows", lambda: True)
    venv = tmp_path / "venv"

    assert platform_support.venv_scripts_dir(venv) == venv / "Scripts"
    assert platform_support.venv_python(venv) == venv / "Scripts" / "python.exe"
    assert platform_support.managed_command_path(tmp_path, "maigret") == tmp_path / "maigret.cmd"


def test_windows_managed_wrapper_is_cmd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("mia.package_manager.is_windows", lambda: True)
    monkeypatch.setattr(platform_support, "is_windows", lambda: True)
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
    )

    wrapper = manager._write_wrapper(
        tmp_path / "bin" / "example",
        ['exec "python" "tool.py" "$@"'],
        windows_command=[r"C:\Python\python.exe", r"C:\Tools\tool.py"],
        working_directory=Path(r"C:\Tools"),
    )

    assert wrapper.name == "example.cmd"
    text = wrapper.read_text(encoding="utf-8")
    assert "Managed by MIA package manager" in text
    assert "cd /d" in text
    assert "%*" in text


def test_linux_managed_wrapper_remains_shell_script(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("mia.package_manager.is_windows", lambda: False)
    monkeypatch.setattr(platform_support, "is_windows", lambda: False)
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
    )

    wrapper = manager._write_wrapper(
        tmp_path / "bin" / "example",
        ['exec "python" "tool.py" "$@"'],
    )

    assert wrapper.name == "example"
    assert wrapper.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")


def test_windows_python_tool_plan_uses_scripts_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("mia.package_manager.is_windows", lambda: True)
    monkeypatch.setattr(platform_support, "is_windows", lambda: True)
    monkeypatch.setattr("mia.package_manager.shutil.which", lambda name: None)
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
        dry_run=True,
    )

    result = manager.install(manager.catalog.tools["maigret"])
    flattened = [" ".join(command) for command in result.commands]

    assert any("Scripts/python.exe" in command for command in flattened)
    assert any(command.startswith("create-command-shim") for command in flattened)


def test_windows_catalog_rejects_unmapped_system_tool(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("mia.package_manager.is_windows", lambda: True)
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="winget",
        dry_run=True,
    )

    supported, detail = manager.platform_compatibility(manager.catalog.tools["exiftool"])

    assert not supported
    assert "Windows package mapping" in detail


def test_windows_core_group_contains_portable_starters(tmp_path: Path) -> None:
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
        dry_run=True,
    )

    assert [tool.tool_id for tool in manager.resolve(groups=["windows-core"])] == [
        "maigret",
        "sherlock",
        "holehe",
    ]


def test_windows_cmd_commands_use_comspec(monkeypatch) -> None:
    monkeypatch.setattr(platform_support, "is_windows", lambda: True)
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")

    prepared = platform_support.prepare_subprocess_command(
        [r"C:\Users\Example User\AppData\Local\MIA\bin\maigret.cmd", "hello user"]
    )

    assert prepared[:4] == [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c"]
    assert "maigret.cmd" in prepared[4]
    assert '"hello user"' in prepared[4]


def test_native_windows_executable_does_not_use_cmd(monkeypatch) -> None:
    monkeypatch.setattr(platform_support, "is_windows", lambda: True)
    command = [r"C:\Tools\maigret.exe", "bobobebra"]
    assert platform_support.prepare_subprocess_command(command) == command
