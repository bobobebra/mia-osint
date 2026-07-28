from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from mia.models import AssistantSummary, CorrelationSuggestion
from mia.utils import atomic_write_text
from mia.workspace import CaseWorkspace


def _excerpt(path: str | None, limit: int) -> str:
    if not path or limit <= 0:
        return ""
    candidate = Path(path)
    try:
        content = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return content[:limit]


def _raw_files(directory: str | None, limit: int, max_files: int = 24) -> list[dict[str, str]]:
    if not directory or limit <= 0:
        return []
    root = Path(directory)
    if not root.is_dir():
        return []
    files: list[dict[str, str]] = []
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file() or len(files) >= max_files:
            continue
        try:
            if candidate.stat().st_size > max(limit * 8, 2_000_000):
                excerpt = "[file omitted from dashboard: too large]"
            else:
                excerpt = candidate.read_text(encoding="utf-8", errors="replace")[:limit]
        except OSError:
            continue
        files.append({"path": str(candidate.relative_to(root)), "excerpt": excerpt})
    return files


def build_dashboard_payload(
    workspace: CaseWorkspace,
    *,
    raw_excerpt_bytes: int = 12000,
    assistant_summary: AssistantSummary | None = None,
    correlations: list[CorrelationSuggestion] | None = None,
    max_nodes: int = 1500,
) -> dict[str, Any]:
    payload = workspace.graph_payload()
    payload["nodes"] = payload["nodes"][:max_nodes]
    allowed = {node["node_id"] for node in payload["nodes"]}
    payload["edges"] = [
        edge
        for edge in payload["edges"]
        if edge["source_node_id"] in allowed and edge["target_node_id"] in allowed
    ]
    runs = []
    for scan in workspace.scans():
        for run in scan.plugin_runs:
            runs.append(
                {
                    "scan_id": scan.scan_id,
                    "target": scan.target,
                    "depth": scan.depth,
                    "plugin_id": run.plugin_id,
                    "plugin_name": run.plugin_name,
                    "status": run.status.value,
                    "duration_seconds": run.duration_seconds,
                    "finding_count": len(run.findings),
                    "error": run.error,
                    "warnings": run.warnings,
                    "stdout_excerpt": _excerpt(run.stdout_path, raw_excerpt_bytes),
                    "stderr_excerpt": _excerpt(run.stderr_path, raw_excerpt_bytes),
                    "raw_files": _raw_files(run.raw_dir, raw_excerpt_bytes),
                    "cached": run.cached,
                }
            )
    payload["plugin_runs"] = runs
    payload["assistant"] = assistant_summary.model_dump(mode="json") if assistant_summary else None
    payload["correlations"] = [item.model_dump(mode="json") for item in correlations or []]
    payload["exports"] = {
        "json": "../exports/case.json",
        "graph_json": "../graph/graph.json",
        "graphml": "../graph/graph.graphml",
        "gexf": "../graph/graph.gexf",
        "mermaid": "../graph/graph.mmd",
        "timeline_json": "../timeline/timeline.json",
        "timeline_csv": "../timeline/timeline.csv",
        "timeline_markdown": "../timeline/timeline.md",
    }
    return payload


def render_dashboard(payload: dict[str, Any]) -> str:
    template_dir = Path(str(files("mia").joinpath("templates")))
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(default=True, default_for_string=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("case_dashboard.html.j2")
    return template.render(payload=payload)


def write_dashboard(
    workspace: CaseWorkspace,
    *,
    raw_excerpt_bytes: int = 12000,
    assistant_summary: AssistantSummary | None = None,
    correlations: list[CorrelationSuggestion] | None = None,
    max_nodes: int = 1500,
) -> Path:
    payload = build_dashboard_payload(
        workspace,
        raw_excerpt_bytes=raw_excerpt_bytes,
        assistant_summary=assistant_summary,
        correlations=correlations,
        max_nodes=max_nodes,
    )
    path = workspace.reports_dir / "index.html"
    atomic_write_text(path, render_dashboard(payload))
    return path
