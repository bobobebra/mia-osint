from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mia.assistant import InvestigationAssistant
from mia.cache import ResultCache
from mia.cli import app
from mia.config import AppConfig
from mia.db import ScanDatabase
from mia.graph import build_graph, export_all_graph_formats
from mia.investigation import InvestigationEngine
from mia.knowledge import KnowledgeDatabase
from mia.models import (
    CaseStatus,
    EvidenceNode,
    FindingStatus,
    MergedFinding,
    PluginRunResult,
    PluginRunStatus,
    ScanProfile,
    ScanResult,
    TargetType,
)
from mia.orchestrator import Orchestrator
from mia.pivot import PivotQueue, extract_pivots
from mia.plugin_sdk import CommunityPluginManager
from mia.registry import PluginRegistry
from mia.reports.dashboard import write_dashboard
from mia.secrets import SecretStore
from mia.workspace import CaseManager

runner = CliRunner()


def _scan(tmp_path: Path, *, target: str = "alice") -> ScanResult:
    now = datetime.now(UTC)
    return ScanResult(
        mia_version="4.0.0a1",
        scan_id="scan-test",
        target=target,
        target_type=TargetType.USERNAME,
        profile=ScanProfile.DEFAULT,
        started_at=now,
        finished_at=now,
        duration_seconds=0.1,
        output_dir=str(tmp_path / "scan"),
        findings=[
            MergedFinding(
                dedup_key="email:alice@example.com",
                category="Emails",
                kind="email",
                title="alice@example.com",
                value="alice@example.com",
                status=FindingStatus.CONFIRMED,
                sources=["fixture-a", "fixture-b"],
                occurrences=2,
                confidence=0.92,
                confidence_label="High",
                confidence_reasons=["Corroborated by two sources"],
                attributes={"created_at": "2024-01-01"},
            )
        ],
    )


def test_workspace_persists_nodes_edges_timeline_and_exports(
    tmp_path: Path, app_config: AppConfig
) -> None:
    app_config.paths.cases_dir = tmp_path / "cases"
    workspace = CaseManager(app_config.paths.cases_dir).create("Alice")
    scan = _scan(tmp_path)
    scan.case_id = workspace.record.case_id
    workspace.save_scan(scan)
    nodes, edges, events = build_graph(workspace.record.case_id, scan, app_config.confidence)
    workspace.save_graph(nodes, edges, events)

    assert len(workspace.nodes()) == 2
    assert len(workspace.edges()) == 1
    assert workspace.edges()[0].relation == "associated_email"
    assert workspace.edges()[0].factors
    assert len(workspace.timeline()) == 1
    paths = export_all_graph_formats(workspace.graph_dir, workspace.nodes(), workspace.edges())
    assert set(paths) == {"json", "graphml", "gexf", "mermaid"}
    assert all(Path(path).exists() for path in paths.values())


def test_knowledge_database_correlates_exact_entities(tmp_path: Path) -> None:
    manager = CaseManager(tmp_path / "cases")
    first = manager.create("First")
    second = manager.create("Second")
    knowledge = KnowledgeDatabase(tmp_path / "knowledge.db")
    for workspace in (first, second):
        node = EvidenceNode(
            node_id=f"node-{workspace.record.case_id}",
            case_id=workspace.record.case_id,
            entity_type="email",
            label="alice@example.com",
            value="alice@example.com",
            canonical_value="alice@example.com",
            confidence=0.9,
            confidence_label="High",
            sources=["test"],
        )
        knowledge.ingest(workspace.record, [node])

    correlations = knowledge.correlations_for_case(first.record.case_id)
    assert len(correlations) == 1
    assert correlations[0].canonical_value == "alice@example.com"
    assert set(correlations[0].case_ids) == {first.record.case_id, second.record.case_id}
    assert len(knowledge.search("alice@")) == 2


def test_pivot_extraction_is_explicit_bounded_and_loop_safe(
    tmp_path: Path, app_config: AppConfig
) -> None:
    scan = _scan(tmp_path)
    scan.findings[0].attributes.update(
        {"domains": ["example.com", "example.com"], "ip_addresses": ["192.0.2.10"]}
    )
    config = app_config.pivoting.model_copy(deep=True)
    config.enabled = True
    config.max_targets = 3
    pivots = extract_pivots(scan, config)
    assert len(pivots) == 3
    assert len({(item.target_type, item.target) for item in pivots}) == 3

    queue = PivotQueue(config)
    queue.mark_visited("alice", TargetType.USERNAME)
    assert queue.enqueue(pivots, depth=1, parent_scan_id=scan.scan_id) == 2
    assert queue.enqueue(pivots, depth=1, parent_scan_id=scan.scan_id) == 0


def test_child_scan_graph_links_back_to_pivot_source(tmp_path: Path, app_config: AppConfig) -> None:
    parent = _scan(tmp_path)
    parent_nodes, _, _ = build_graph("case-pivot", parent, app_config.confidence)
    source = next(node for node in parent_nodes if node.entity_type == "email")
    child = ScanResult(
        mia_version="4.0.0a1",
        scan_id="scan-child",
        target="alice@example.com",
        target_type=TargetType.EMAIL,
        profile=ScanProfile.QUICK,
        output_dir=str(tmp_path / "child"),
        depth=1,
        parent_scan_id=parent.scan_id,
        pivot_source_node_id=source.node_id,
    )
    child_nodes, child_edges, _ = build_graph("case-pivot", child, app_config.confidence)
    assert child_nodes[0].attributes["pivot_target"] is True
    scan_node = next(node for node in child_nodes if node.entity_type == "scan")
    assert child_edges[0].relation == "triggered_scan"
    assert child_edges[0].source_node_id == source.node_id
    assert child_edges[0].target_node_id == scan_node.node_id
    assert "not evidence" in child_edges[0].factors[0].explanation


def test_timeline_exports_are_written_with_case_payload(
    tmp_path: Path, app_config: AppConfig
) -> None:
    workspace = CaseManager(tmp_path / "cases").create("Timeline exports")
    scan = _scan(tmp_path)
    scan.findings[0].attributes["created_at"] = "2024-01-02T03:04:05Z"
    workspace.save_scan(scan)
    nodes, edges, events = build_graph(workspace.record.case_id, scan, app_config.confidence)
    workspace.save_graph(nodes, edges, events)

    workspace.export_payload()

    assert (workspace.timeline_dir / "timeline.json").exists()
    assert "created_at" in (workspace.timeline_dir / "timeline.csv").read_text(encoding="utf-8")
    markdown = (workspace.timeline_dir / "timeline.md").read_text(encoding="utf-8")
    assert "2024-01-02" in markdown


def test_case_attachment_is_hashed_recorded_and_exported(tmp_path: Path) -> None:
    workspace = CaseManager(tmp_path / "cases").create("Attachments")
    source = tmp_path / "evidence.txt"
    source.write_text("public evidence", encoding="utf-8")
    attachment = workspace.add_attachment(source, kind="evidence", note="manual import")
    assert Path(attachment.path).read_text(encoding="utf-8") == "public evidence"
    assert len(attachment.sha256) == 64
    assert workspace.attachments()[0].note == "manual import"
    exported = json.loads(workspace.export_payload().read_text(encoding="utf-8"))
    assert exported["attachments"][0]["attachment_id"] == attachment.attachment_id


def test_dashboard_is_offline_and_includes_bounded_raw_evidence(
    tmp_path: Path, app_config: AppConfig
) -> None:
    app_config.paths.cases_dir = tmp_path / "cases"
    workspace = CaseManager(app_config.paths.cases_dir).create("Dashboard")
    scan = _scan(tmp_path)
    raw_dir = workspace.root / "raw-fixture"
    raw_dir.mkdir()
    (raw_dir / "response.json").write_text('{"hello":"world"}', encoding="utf-8")
    now = datetime.now(UTC)
    scan.plugin_runs = [
        PluginRunResult(
            plugin_id="fixture",
            plugin_name="Fixture",
            status=PluginRunStatus.SUCCESS,
            started_at=now,
            finished_at=now,
            duration_seconds=0.01,
            raw_dir=str(raw_dir),
        )
    ]
    workspace.save_scan(scan)
    nodes, edges, events = build_graph(workspace.record.case_id, scan, app_config.confidence)
    workspace.save_graph(nodes, edges, events)
    summary = InvestigationAssistant(app_config).local_summary(workspace.nodes(), workspace.edges())
    dashboard = write_dashboard(workspace, assistant_summary=summary)
    html = dashboard.read_text(encoding="utf-8")

    assert "Interactive evidence graph" in html
    assert "Timeline" in html
    assert "response.json" in html
    assert "hello" in html
    assert "<script src=" not in html
    assert "https://cdn" not in html


def test_dashboard_json_payload_escapes_script_terminators(
    tmp_path: Path, app_config: AppConfig
) -> None:
    app_config.paths.cases_dir = tmp_path / "cases"
    workspace = CaseManager(app_config.paths.cases_dir).create("Script safety")
    scan = _scan(tmp_path)
    scan.findings[0].title = "</script><script>alert(1)</script>"
    workspace.save_scan(scan)
    nodes, edges, events = build_graph(workspace.record.case_id, scan, app_config.confidence)
    workspace.save_graph(nodes, edges, events)
    dashboard = write_dashboard(workspace)
    html = dashboard.read_text(encoding="utf-8")

    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script\\u003e" in html


def test_plugin_sdk_scaffold_validate_install_and_remove(tmp_path: Path) -> None:
    manager = CommunityPluginManager(tmp_path / "installed")
    source = manager.create("example-plugin", tmp_path / "source")
    validation = manager.validate(source)
    assert validation["valid"] is True
    installed = manager.install(source)
    assert installed == tmp_path / "installed" / "example-plugin"
    assert manager.list()[0][0].version == "0.1.0"
    assert manager.uninstall("example-plugin") is True


def test_api_plugins_are_discovered() -> None:
    ids = set(PluginRegistry.discover().ids())
    assert {
        "api-shodan",
        "api-virustotal",
        "api-hibp",
        "api-securitytrails",
        "api-censys",
        "api-intelx",
    }.issubset(ids)


def test_secret_store_prefers_documented_environment_variable(
    monkeypatch, app_config: AppConfig
) -> None:
    monkeypatch.setenv("MIA_SHODAN_API_KEY", "secret-from-env")
    store = SecretStore(app_config)
    assert store.get("shodan") == "secret-from-env"
    assert store.source("shodan") == "environment (MIA_SHODAN_API_KEY)"


def test_remote_assistant_requires_explicit_model(app_config: AppConfig) -> None:
    assistant = InvestigationAssistant(app_config)
    with pytest.raises(RuntimeError, match="AI model is not configured"):
        asyncio.run(assistant.openai_compatible_summary([], []))


def test_local_assistant_cites_only_case_evidence(tmp_path: Path, app_config: AppConfig) -> None:
    scan = _scan(tmp_path)
    nodes, edges, _ = build_graph("case-assistant", scan, app_config.confidence)
    summary = InvestigationAssistant(app_config).local_summary(nodes, edges)
    allowed = {node.node_id for node in nodes} | {edge.edge_id for edge in edges}
    statements = [
        *summary.executive_summary,
        *summary.notable_findings,
        *summary.uncertainty_warnings,
        *summary.suggested_next_steps,
    ]
    assert statements
    assert all(set(statement.evidence_ids).issubset(allowed) for statement in statements)


def test_cache_roundtrip_marks_reused_result_cached(tmp_path: Path) -> None:
    cache = ResultCache(tmp_path / "cache.db")
    now = datetime.now(UTC)
    result = PluginRunResult(
        plugin_id="fixture",
        plugin_name="Fixture",
        status=PluginRunStatus.SUCCESS,
        started_at=now,
        finished_at=now,
        duration_seconds=0.01,
    )
    key = cache.key("fixture", "alice", TargetType.USERNAME, ScanProfile.DEFAULT, [])
    cache.put(
        key,
        "scan-origin",
        result,
        target="alice",
        target_type=TargetType.USERNAME,
        profile=ScanProfile.DEFAULT,
    )
    reused = cache.get(key, ttl_seconds=60)
    assert reused is not None
    assert reused.status == PluginRunStatus.CACHED
    assert reused.cache_source_scan_id == "scan-origin"


def test_investigation_engine_creates_complete_local_hash_case(
    tmp_path: Path, app_config: AppConfig
) -> None:
    app_config.paths.cases_dir = tmp_path / "cases"
    app_config.paths.state_dir = tmp_path / "state"
    app_config.paths.output_dir = tmp_path / "reports"
    app_config.paths.log_dir = tmp_path / "logs"
    app_config.ensure_directories()
    registry = PluginRegistry.discover()
    database = ScanDatabase(app_config.paths.database_path)
    orchestrator = Orchestrator(app_config, registry, database, logging.getLogger("test-v4"))
    engine = InvestigationEngine(
        app_config,
        orchestrator,
        KnowledgeDatabase(app_config.paths.knowledge_database_path),
        logging.getLogger("test-v4"),
    )
    result = asyncio.run(
        engine.investigate(
            "d41d8cd98f00b204e9800998ecf8427e",
            TargetType.HASH,
            ScanProfile.QUICK,
            include=["hashid"],
        )
    )
    assert result.dashboard_path and result.dashboard_path.exists()
    assert len(result.workspace.nodes()) == 4
    assert len(result.workspace.edges()) == 3
    assert result.workspace.export_payload().exists()


def test_case_cli_investigate_and_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MIA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MIA_CASES_DIR", str(tmp_path / "cases"))
    monkeypatch.setenv("MIA_OUTPUT_DIR", str(tmp_path / "reports"))
    result = runner.invoke(
        app,
        [
            "investigate",
            "d41d8cd98f00b204e9800998ecf8427e",
            "--type",
            "hash",
            "--tool",
            "hashid",
            "--no-pivot",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "Case updated" in result.stdout
    listed = runner.invoke(app, ["case", "list", "--json"])
    assert listed.exit_code == 0
    assert "case_id" in listed.stdout


def test_case_attachment_cli_auto_rebuilds_dashboard(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MIA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MIA_CASES_DIR", str(tmp_path / "cases"))
    monkeypatch.setenv("MIA_OUTPUT_DIR", str(tmp_path / "reports"))
    created = runner.invoke(app, ["case", "create", "Attachment CLI"])
    assert created.exit_code == 0, created.stdout
    case_id = created.stdout.split("Created ", 1)[1].split(" at ", 1)[0].strip()
    source = tmp_path / "manual.txt"
    source.write_text("manual public evidence", encoding="utf-8")

    added = runner.invoke(
        app, ["case", "add-evidence", case_id, str(source), "--note", "manual import"]
    )

    assert added.exit_code == 0, added.stdout
    workspace = CaseManager(tmp_path / "cases").resolve(case_id)
    dashboard = workspace.reports_dir / "index.html"
    assert dashboard.exists()
    html = dashboard.read_text(encoding="utf-8")
    assert "manual.txt" in html
    assert "manual import" in html


def test_case_archive_filter(tmp_path: Path) -> None:
    manager = CaseManager(tmp_path / "cases")
    workspace = manager.create("Archived")
    workspace.record.status = CaseStatus.ARCHIVED
    workspace.write_manifest()
    assert manager.list() == []
    assert manager.list(include_archived=True)[0].status == CaseStatus.ARCHIVED
