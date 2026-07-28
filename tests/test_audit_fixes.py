from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import mia.cli as cli_module
from mia.cache import ResultCache
from mia.cli import app
from mia.config import AppConfig
from mia.db import ScanDatabase
from mia.investigation import InvestigationEngine
from mia.knowledge import KnowledgeDatabase
from mia.models import (
    PluginRunResult,
    PluginRunStatus,
    ScanProfile,
    ScanResult,
    TargetType,
)
from mia.package_manager import PackageError, PackageManager
from mia.plugins.apis import IntelXApiPlugin
from mia.plugins.extended import HttpxPlugin
from mia.workspace import CaseManager

runner = CliRunner()


def _failed_scan(tmp_path: Path, target: str = "example.com") -> ScanResult:
    now = datetime.now(UTC)
    return ScanResult(
        mia_version="4.0.0a5",
        scan_id="failed-scan",
        target=target,
        target_type=TargetType.DOMAIN,
        profile=ScanProfile.DEFAULT,
        started_at=now,
        finished_at=now,
        duration_seconds=0.1,
        output_dir=str(tmp_path / "reports"),
        plugin_runs=[
            PluginRunResult(
                plugin_id="fixture-failure",
                plugin_name="Fixture failure",
                status=PluginRunStatus.FAILED,
                started_at=now,
                finished_at=now,
                duration_seconds=0.1,
                return_code=1,
                error="fixture failure",
            )
        ],
    )


def test_httpx_plugin_rejects_python_httpx_cli(tmp_path: Path, app_config: AppConfig) -> None:
    fake = tmp_path / "httpx"
    fake.write_text("#!/bin/sh\necho 'The HTTPX command line client'\n", encoding="utf-8")
    fake.chmod(0o755)
    app_config.tools["httpx"].executable = str(fake)

    status = HttpxPlugin().detect(app_config)

    assert not status.available
    assert "unexpected executable identity" in status.message


def test_httpx_plugin_accepts_projectdiscovery_signature(
    tmp_path: Path, app_config: AppConfig
) -> None:
    fake = tmp_path / "httpx"
    fake.write_text(
        "#!/bin/sh\necho 'httpx version'\necho 'ProjectDiscovery current version: v1.7.0'\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    app_config.tools["httpx"].executable = str(fake)

    status = HttpxPlugin().detect(app_config)

    assert status.available


def test_package_status_rejects_wrong_httpx_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "httpx"
    fake.write_text("#!/bin/sh\necho 'HTTPX CLI'\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(
        "mia.package_manager.shutil.which", lambda name: str(fake) if name == "httpx" else None
    )
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
    )

    installed, executable, source = manager.status(manager.catalog.tools["httpx"])

    assert not installed
    assert executable == str(fake)
    assert source == "wrong executable identity"


def test_intelx_raw_payload_is_metadata_only() -> None:
    payload = {
        "id": "search-id",
        "status": 1,
        "selectors": ["example.com"],
        "records": [
            {
                "systemid": "record-1",
                "name": "public-record",
                "date": "2026-01-01",
                "media": 1,
                "storageid": "storage-1",
                "bucket": "bucket-a",
                "type": "domain",
                "preview": "secret preview",
                "content": "secret content",
                "raw": {"password": "do-not-store"},
            }
        ],
    }

    safe = IntelXApiPlugin().raw_payload(payload)
    serialized = json.dumps(safe)

    assert "record-1" in serialized
    assert "secret preview" not in serialized
    assert "secret content" not in serialized
    assert "do-not-store" not in serialized


@pytest.mark.parametrize("database_factory", [ScanDatabase, ResultCache, KnowledgeDatabase])
def test_database_contexts_close_connections(tmp_path: Path, database_factory) -> None:
    database = database_factory(tmp_path / f"{database_factory.__name__}.db")
    with database.connect() as connection:
        connection.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_case_workspace_closes_connections(tmp_path: Path) -> None:
    workspace = CaseManager(tmp_path / "cases").create("Close DB")
    with workspace.connect() as connection:
        connection.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_invalid_plugin_id_is_friendly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MIA_STATE_DIR", str(tmp_path / "state"))
    result = runner.invoke(app, ["plugin", "create", "Bad Plugin"])

    assert result.exit_code == 2
    assert "Error:" in result.output
    assert "Traceback" not in result.output


def test_unknown_api_service_is_rejected_without_config_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["--config", str(config_path), "api", "disable", "madeupservice"])

    assert result.exit_code == 2
    assert "unknown API service" in result.output
    assert config_path.read_text(encoding="utf-8") == "{}\n"


def test_assistant_can_switch_back_to_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("HOME", str(tmp_path))
    configured = runner.invoke(
        app,
        [
            "--config",
            str(config_path),
            "assistant",
            "configure",
            "gemini",
            "--model",
            "gemini-test",
            "--default",
        ],
    )
    assert configured.exit_code == 0, configured.output

    local = runner.invoke(
        app,
        ["--config", str(config_path), "assistant", "configure", "local", "--default"],
    )

    assert local.exit_code == 0, local.output
    assert "provider: local" in config_path.read_text(encoding="utf-8")


def test_failed_only_scan_exits_nonzero_unless_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeOrchestrator:
        async def scan(self, **kwargs):
            return _failed_scan(tmp_path)

    monkeypatch.setattr(
        cli_module,
        "_services",
        lambda ctx: (None, None, None, FakeOrchestrator()),
    )

    failed = runner.invoke(app, ["scan", "example.com", "--type", "domain"])
    allowed = runner.invoke(app, ["scan", "example.com", "--type", "domain", "--allow-empty"])

    assert failed.exit_code == 1
    assert "no selected plugin completed successfully" in failed.output
    assert allowed.exit_code == 0


def test_failed_new_investigation_rolls_back_workspace(
    tmp_path: Path, app_config: AppConfig
) -> None:
    app_config.paths.cases_dir = tmp_path / "cases"
    app_config.paths.state_dir = tmp_path / "state"

    class FakeOrchestrator:
        def select_plugins(self, *args, **kwargs):
            return [object()]

        async def scan(self, *args, **kwargs):
            return _failed_scan(tmp_path, target="example.com")

    engine = InvestigationEngine(
        app_config,
        FakeOrchestrator(),
        KnowledgeDatabase(app_config.paths.knowledge_database_path),
        __import__("logging").getLogger("rollback-test"),
    )

    with pytest.raises(Exception, match="no root-scan plugin completed successfully"):
        asyncio.run(
            engine.investigate(
                "example.com",
                TargetType.DOMAIN,
                ScanProfile.DEFAULT,
                include=["fixture-failure"],
            )
        )

    assert not list(app_config.paths.cases_dir.glob("*"))


def test_blank_case_identifier_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIA_CASES_DIR", str(tmp_path / "cases"))
    result = runner.invoke(
        app,
        [
            "investigate",
            "d41d8cd98f00b204e9800998ecf8427e",
            "--type",
            "hash",
            "--case",
            "",
        ],
    )
    assert result.exit_code == 2
    assert "cannot be blank" in result.output


def test_invalid_package_manager_is_always_rejected(tmp_path: Path) -> None:
    with pytest.raises(PackageError, match="unsupported package manager"):
        PackageManager(
            state_dir=tmp_path / "state",
            bin_dir=tmp_path / "bin",
            package_manager="nonsense",
            dry_run=True,
        )


def test_update_absent_tool_explains_that_it_will_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mia.package_manager.shutil.which", lambda name: None)
    manager = PackageManager(
        state_dir=tmp_path / "state",
        bin_dir=tmp_path / "bin",
        package_manager="none",
        dry_run=True,
    )
    result = manager.update(manager.catalog.tools["waymore"])

    assert result.action == "update"
    assert "was absent" in result.message


def test_recipe_repairs_are_present() -> None:
    catalog = PackageManager(dry_run=True, package_manager="none").catalog
    assert catalog.tools["findomain"].install.kind == "download_archive"
    assert catalog.tools["dnstwist"].install.package == "dnstwist"
    assert catalog.tools["whatweb"].install.kind == "git_script"
    assert catalog.tools["phoneinfoga"].install.kind == "download_archive"
    assert catalog.tools["vt-cli"].install.module == "github.com/VirusTotal/vt-cli/vt@latest"
    assert catalog.tools["cloud-enum"].install.kind == "uv_project"


def test_reconfiguring_logging_closes_old_file_handler(tmp_path: Path) -> None:
    from mia.logging_utils import configure_logging

    logger = configure_logging(tmp_path / "first")
    old_handlers = list(logger.handlers)
    configure_logging(tmp_path / "second")

    file_handlers = [handler for handler in old_handlers if hasattr(handler, "stream")]
    assert file_handlers
    assert all(getattr(handler, "stream", None) is None for handler in file_handlers)


def test_intelx_http_error_body_is_redacted() -> None:
    plugin = IntelXApiPlugin()
    assert "preview" not in plugin.raw_error_body("secret preview content")
    assert "redacted" in plugin.raw_error_body("secret preview content")
