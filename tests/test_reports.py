from datetime import UTC, datetime
from pathlib import Path

from mia.config import ReportsConfig
from mia.models import MergedFinding, ScanProfile, ScanResult, TargetType
from mia.reports import ReportWriter


def test_report_writer(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    result = ScanResult(
        mia_version="3.0.0",
        scan_id="scan-1",
        target="octocat",
        target_type=TargetType.USERNAME,
        profile=ScanProfile.DEEP,
        started_at=now,
        finished_at=now,
        duration_seconds=1.2,
        output_dir=str(tmp_path),
        findings=[
            MergedFinding(
                dedup_key="url:https://github.com/octocat",
                category="Profiles",
                kind="profile",
                title="GitHub",
                value="https://github.com/octocat",
                url="https://github.com/octocat",
                status="confirmed",
                sources=["maigret", "sherlock"],
                occurrences=2,
                confidence=0.91,
                confidence_label="High",
                confidence_reasons=["Corroborated by 2 independent plugins"],
            )
        ],
    )
    paths = ReportWriter(ReportsConfig()).write(result)
    assert set(paths) == {"html", "json", "text", "markdown"}
    assert "GitHub" in (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Responsible-use notice" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_html_report_escapes_untrusted_tool_output(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    malicious = '<script>alert("report")</script>'
    result = ScanResult(
        mia_version="3.2.0",
        scan_id="scan-escape",
        target='name" onmouseover="alert(1)',
        target_type=TargetType.USERNAME,
        profile=ScanProfile.DEFAULT,
        started_at=now,
        finished_at=now,
        duration_seconds=0.2,
        output_dir=str(tmp_path),
        findings=[
            MergedFinding(
                dedup_key="url:https://example.com/user",
                category="Profiles",
                kind="profile",
                title=malicious,
                value='https://example.com/user?value="quoted"',
                url='https://example.com/user?value="quoted"',
                status="possible",
                sources=["test-plugin"],
                confidence=0.5,
                confidence_label="Low",
            )
        ],
    )

    ReportWriter(ReportsConfig()).write(result)
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert malicious not in html
    assert "&lt;script&gt;" in html
    assert 'onmouseover="alert(1)' not in html
    assert "default profile" in html
