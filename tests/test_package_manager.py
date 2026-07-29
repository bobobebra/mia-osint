from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mia.package_manager import (
    InstalledPackage,
    PackageError,
    PackageManager,
    PackageState,
    load_catalog,
)


def test_catalog_is_large_and_group_references_are_valid() -> None:
    catalog = load_catalog()
    assert len(catalog.tools) >= 40
    referenced = {tool_id for members in catalog.groups.values() for tool_id in members}
    assert referenced <= set(catalog.tools)
    assert {"local", "passive", "mixed"} == {tool.risk for tool in catalog.tools.values()}
    assert {"full", "raw", "managed-only"} == {tool.integration for tool in catalog.tools.values()}


def test_group_resolution_is_unique_and_unknown_values_fail() -> None:
    manager = PackageManager(dry_run=True, package_manager="none")
    resolved = manager.resolve(groups=["core", "core"])
    assert [tool.tool_id for tool in resolved] == manager.catalog.groups["core"]
    with pytest.raises(PackageError, match="unknown package group"):
        manager.resolve(groups=["not-a-group"])
    with pytest.raises(PackageError, match="unknown OSINT tool"):
        manager.resolve(names=["not-a-tool"])


def test_all_excludes_mixed_unless_requested() -> None:
    manager = PackageManager(dry_run=True, package_manager="none")
    safe = manager.all_tools()
    everything = manager.all_tools(include_mixed=True)
    assert safe
    assert all(tool.risk != "mixed" for tool in safe)
    assert any(tool.risk == "mixed" for tool in everything)
    assert len(everything) == len(manager.catalog.tools)


def test_python_install_dry_run_uses_isolated_uv_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("mia.package_manager.shutil.which", lambda name: None)
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
        dry_run=True,
    )
    result = manager.install(manager.catalog.tools["waymore"])
    assert result.success
    flattened = [" ".join(command) for command in result.commands]
    assert any("uv venv --python 3.12" in command for command in flattened)
    assert any("uv pip install" in command and "waymore" in command for command in flattened)
    assert any(command.startswith("ln -sfn") for command in flattened)


def test_go_install_dry_run_installs_go_prerequisite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("mia.package_manager.shutil.which", lambda name: None)
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="apt",
        dry_run=True,
    )
    result = manager.install(manager.catalog.tools["subfinder"])
    flattened = [" ".join(command) for command in result.commands]
    assert any("apt-get install -y golang-go" in command for command in flattened)
    assert any(
        "go install github.com/projectdiscovery/subfinder" in command for command in flattened
    )


def test_go_install_dry_run_without_system_manager_records_manual_prerequisite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("mia.package_manager.shutil.which", lambda name: None)
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
        dry_run=True,
    )

    result = manager.install(manager.catalog.tools["subfinder"])

    assert result.success
    assert ["manual-prerequisite", "go"] in result.commands
    assert any(" go install " in f" {' '.join(command)} " for command in result.commands)


def test_system_packages_are_preserved_by_default(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    manager = PackageManager(
        state_dir=state_dir,
        bin_dir=tmp_path / "bin",
        package_manager="apt",
        dry_run=False,
        runner=lambda command, env: subprocess.CompletedProcess(command, 0, "", ""),
    )
    now = datetime.now(UTC)
    manager.save_state(
        PackageState(
            packages={
                "whois": InstalledPackage(
                    tool_id="whois",
                    method="system",
                    installed_at=now,
                    updated_at=now,
                    executable="whois",
                    system_manager="apt",
                    system_package="whois",
                )
            }
        )
    )
    result = manager.uninstall(manager.catalog.tools["whois"])
    assert not result.success
    assert "preserved" in result.message
    assert "whois" in manager.load_state().packages


def test_state_file_round_trip_is_private(tmp_path: Path) -> None:
    manager = PackageManager(state_dir=tmp_path / "state", bin_dir=tmp_path / "bin")
    manager.save_state(PackageState())
    assert manager.state_path.exists()
    assert manager.state_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(manager.state_path.read_text())["schema_version"] == 1


def test_uninstall_preserves_user_replaced_command(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command = bin_dir / "waymore"
    command.write_text("#!/bin/sh\necho user replacement\n", encoding="utf-8")
    command.chmod(0o755)
    managed_root = state_dir / "packages" / "waymore"
    managed_root.mkdir(parents=True)
    now = datetime.now(UTC)
    manager = PackageManager(state_dir=state_dir, bin_dir=bin_dir, package_manager="none")
    manager.save_state(
        PackageState(
            packages={
                "waymore": InstalledPackage(
                    tool_id="waymore",
                    method="python",
                    installed_at=now,
                    updated_at=now,
                    executable=str(command),
                    managed_root=str(managed_root),
                    source="https://example.test",
                )
            }
        )
    )

    result = manager.uninstall(manager.catalog.tools["waymore"])

    assert not result.success
    assert "preserved changed command" in result.message
    assert command.exists()
    assert managed_root.exists()
    assert "waymore" in manager.load_state().packages


@pytest.mark.parametrize(
    ("tool_id", "expected_fragment"),
    [
        (
            "findomain",
            "download https://github.com/Findomain/Findomain/releases/latest/download/findomain-linux.zip",
        ),
        ("blackbird", "git clone --depth 1 --branch main"),
        ("theharvester", "uv sync --project"),
        ("holehe", "holehe==1.61"),
        ("spiderfoot", "prepare-spiderfoot-requirements"),
        ("exiftool", "apt-get install -y libimage-exiftool-perl"),
    ],
)
def test_every_install_recipe_kind_has_a_dry_run(
    tool_id: str,
    expected_fragment: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("mia.package_manager.shutil.which", lambda name: None)
    manager = PackageManager(
        state_dir=tmp_path / tool_id / "state",
        bin_dir=tmp_path / tool_id / "bin",
        package_manager="apt",
        dry_run=True,
    )
    result = manager.install(manager.catalog.tools[tool_id])
    commands = [" ".join(command) for command in result.commands]
    assert result.success
    assert any(expected_fragment in command for command in commands)


def test_default_runner_streams_output_heartbeats_and_writes_a_tool_log(tmp_path: Path) -> None:
    events = []
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
        event_handler=events.append,
        heartbeat_seconds=0.05,
    )
    manager._active_tool_id = "stream-test"
    manager._active_action = "install"

    manager._run(
        [
            __import__("sys").executable,
            "-c",
            (
                "import time; "
                "print('first line', flush=True); "
                "time.sleep(0.65); "
                "print('last line', flush=True)"
            ),
        ]
    )

    kinds = [event.kind for event in events]
    messages = [event.message for event in events]
    assert kinds[0] == "command_start"
    assert "output" in kinds
    assert "heartbeat" in kinds
    assert kinds[-1] == "command_end"
    assert any("first line" in message for message in messages)
    assert any("last line" in message for message in messages)
    log_path = manager.active_log_path
    assert log_path is not None and log_path.exists()
    assert log_path.stat().st_mode & 0o777 == 0o600
    log = log_path.read_text(encoding="utf-8")
    assert "first line" in log
    assert "last line" in log


def test_custom_runner_still_emits_output_events(tmp_path: Path) -> None:
    events = []

    def runner(command, env):
        return subprocess.CompletedProcess(command, 0, "custom output\n", "")

    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
        runner=runner,
        event_handler=events.append,
    )
    manager._active_tool_id = "custom-test"
    manager._active_action = "install"

    manager._run(["custom-command"])

    assert [event.kind for event in events] == ["command_start", "output", "command_end"]
    assert events[1].message == "custom output"


def test_missing_command_becomes_a_package_error_and_closes_progress(tmp_path: Path) -> None:
    events = []
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
        event_handler=events.append,
    )
    manager._active_tool_id = "missing-test"
    manager._active_action = "install"

    with pytest.raises(PackageError, match="could not start"):
        manager._run([str(tmp_path / "definitely-not-a-command")])

    assert [event.kind for event in events] == ["command_start", "command_end"]
    assert events[-1].return_code == 127


@pytest.mark.parametrize(
    ("tool_id", "archive_kind"),
    [("findomain", "zip"), ("phoneinfoga", "tar.gz")],
)
def test_download_archive_recipe_installs_local_fixture(
    tool_id: str,
    archive_kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import tarfile
    import zipfile

    fixture = tmp_path / ("fixture.zip" if archive_kind == "zip" else "fixture.tar.gz")
    executable_body = b"#!/bin/sh\necho fixture-tool\n"
    if archive_kind == "zip":
        with zipfile.ZipFile(fixture, "w") as archive:
            archive.writestr(
                tool_id if tool_id != "phoneinfoga" else "phoneinfoga", executable_body
            )
    else:
        with tarfile.open(fixture, "w:gz") as archive:
            info = tarfile.TarInfo("phoneinfoga")
            info.mode = 0o755
            info.size = len(executable_body)
            archive.addfile(info, io.BytesIO(executable_body))

    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
    )
    monkeypatch.setattr(manager, "_platform_key", lambda: "linux-x86_64")
    monkeypatch.setattr(
        manager,
        "_download_file",
        lambda url, destination: __import__("shutil").copy2(fixture, destination),
    )

    result = manager.install(manager.catalog.tools[tool_id])

    assert result.success
    command = tmp_path / "bin" / manager.catalog.tools[tool_id].install.executable
    completed = subprocess.run([str(command)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert completed.stdout.strip() == "fixture-tool"


def test_git_script_recipe_creates_runtime_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def which(name: str):
        if name in {"git", "ruby"}:
            return f"/usr/bin/{name}"
        return None

    def runner(command, env):
        if command[:2] == ["git", "clone"]:
            destination = Path(command[-1])
            destination.mkdir(parents=True)
            script = destination / "whatweb"
            script.write_text("puts 'whatweb fixture'\n", encoding="utf-8")
            script.chmod(0o755)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("mia.package_manager.shutil.which", which)
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
        runner=runner,
    )

    result = manager.install(manager.catalog.tools["whatweb"])

    assert result.success
    wrapper = tmp_path / "bin" / "whatweb"
    assert wrapper.exists()
    text = wrapper.read_text(encoding="utf-8")
    assert "ruby" in text
    assert "source/whatweb" in text


def test_uv_project_recipe_handles_current_cloud_enum_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def which(name: str):
        if name in {"git", "uv"}:
            return f"/usr/bin/{name}"
        return None

    def runner(command, env):
        if command[:2] == ["git", "clone"]:
            source = Path(command[-1])
            source.mkdir(parents=True)
            (source / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
        elif command[:2] == ["/usr/bin/uv", "sync"]:
            source = Path(command[command.index("--project") + 1])
            executable = source / ".venv" / "bin" / "cloud_enum"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\necho cloud fixture\n", encoding="utf-8")
            executable.chmod(0o755)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("mia.package_manager.shutil.which", which)
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
        runner=runner,
    )
    monkeypatch.setattr(manager, "_uv", lambda: "/usr/bin/uv")

    result = manager.install(manager.catalog.tools["cloud-enum"])

    assert result.success
    assert (tmp_path / "bin" / "cloud_enum").exists()
