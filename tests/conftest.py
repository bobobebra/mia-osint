from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer import rich_utils

from mia.config import AppConfig, load_config
from mia.models import PluginContext, ProcessResult, ScanProfile, TargetType


@pytest.fixture(autouse=True)
def stable_cli_width(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rich_utils, "MAX_WIDTH", 160)


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    config = load_config()
    config.paths.output_dir = tmp_path / "reports"
    config.paths.state_dir = tmp_path / "state"
    config.paths.log_dir = tmp_path / "logs"
    config.ensure_directories()
    return config


@pytest.fixture
def plugin_context(tmp_path: Path) -> PluginContext:
    scan_dir = tmp_path / "scan"
    raw_dir = scan_dir / "raw" / "plugin"
    raw_dir.mkdir(parents=True)
    return PluginContext(
        scan_id="test-scan",
        target="octocat",
        target_type=TargetType.USERNAME,
        profile=ScanProfile.DEEP,
        scan_dir=scan_dir,
        raw_dir=raw_dir,
        timeout_seconds=30,
    )


@pytest.fixture
def process_result(tmp_path: Path) -> ProcessResult:
    now = datetime.now(UTC)
    stdout_path = tmp_path / "stdout.txt"
    stderr_path = tmp_path / "stderr.txt"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    return ProcessResult(
        command=["tool"],
        return_code=0,
        started_at=now,
        finished_at=now,
        duration_seconds=0.01,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
    )
