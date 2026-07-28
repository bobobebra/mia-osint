from datetime import UTC, datetime
from pathlib import Path

from mia.db import ScanDatabase
from mia.models import MergedFinding, ScanProfile, ScanResult, TargetType


def make_result(scan_id: str, output: Path, value: str) -> ScanResult:
    now = datetime.now(UTC)
    return ScanResult(
        mia_version="3.0.0",
        scan_id=scan_id,
        target="octocat",
        target_type=TargetType.USERNAME,
        profile=ScanProfile.DEEP,
        started_at=now,
        finished_at=now,
        duration_seconds=1.0,
        output_dir=str(output),
        findings=[
            MergedFinding(
                dedup_key=f"url:{value}",
                category="Profiles",
                kind="profile",
                title="Site",
                value=value,
                url=value,
                status="confirmed",
                sources=["maigret"],
                occurrences=1,
                confidence=0.75,
                confidence_label="Medium",
            )
        ],
    )


def test_save_load_history_and_compare(tmp_path: Path) -> None:
    database = ScanDatabase(tmp_path / "mia.db")
    first = make_result("20260101T000000Z-aaa", tmp_path / "one", "https://a.example/u")
    second = make_result("20260102T000000Z-bbb", tmp_path / "two", "https://b.example/u")
    database.save(first)
    database.save(second)
    assert database.load("20260101").scan_id == first.scan_id
    assert len(database.history()) == 2
    diff = database.compare(first.scan_id, second.scan_id)
    assert len(diff["added"]) == 1
    assert len(diff["removed"]) == 1
