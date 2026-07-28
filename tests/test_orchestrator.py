import asyncio
import logging
from pathlib import Path

from mia.db import ScanDatabase
from mia.models import ScanProfile, TargetType
from mia.orchestrator import Orchestrator
from mia.registry import PluginRegistry


def test_end_to_end_local_hash_scan(app_config, tmp_path: Path) -> None:
    registry = PluginRegistry.discover()
    database = ScanDatabase(app_config.paths.database_path)
    logger = logging.getLogger("mia-test")
    orchestrator = Orchestrator(app_config, registry, database, logger)
    result = asyncio.run(
        orchestrator.scan(
            target="d41d8cd98f00b204e9800998ecf8427e",
            target_type=TargetType.HASH,
            profile=ScanProfile.QUICK,
            include=["hashid"],
        )
    )
    assert result.findings
    assert Path(result.report_paths["html"]).exists()
    assert database.load(result.scan_id).target == result.target
