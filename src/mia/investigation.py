from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from mia.assistant import InvestigationAssistant, write_summary
from mia.config import AppConfig
from mia.exceptions import PluginError
from mia.graph import build_graph, export_all_graph_formats
from mia.knowledge import KnowledgeDatabase
from mia.models import AssistantSummary, CorrelationSuggestion, ScanProfile, ScanResult, TargetType
from mia.orchestrator import EventCallback, Orchestrator
from mia.pivot import PivotQueue, extract_pivots
from mia.reports.dashboard import write_dashboard
from mia.workspace import CaseManager, CaseWorkspace


@dataclass(slots=True)
class InvestigationResult:
    workspace: CaseWorkspace
    scans: list[ScanResult] = field(default_factory=list)
    correlations: list[CorrelationSuggestion] = field(default_factory=list)
    dashboard_path: Path | None = None
    graph_paths: dict[str, str] = field(default_factory=dict)
    assistant_summary: AssistantSummary | None = None
    skipped_pivots: list[str] = field(default_factory=list)


class InvestigationEngine:
    def __init__(
        self,
        config: AppConfig,
        orchestrator: Orchestrator,
        knowledge: KnowledgeDatabase,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.orchestrator = orchestrator
        self.knowledge = knowledge
        self.logger = logger
        self.cases = CaseManager(config.paths.cases_dir)

    async def investigate(
        self,
        target: str,
        target_type: TargetType,
        profile: ScanProfile,
        *,
        case_identifier: str | None = None,
        case_name: str | None = None,
        enable_pivoting: bool | None = None,
        max_depth: int | None = None,
        max_targets: int | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        event_callback: EventCallback | None = None,
        use_cache: bool | None = None,
    ) -> InvestigationResult:
        selected = self.orchestrator.select_plugins(target_type, profile, include, exclude)
        if not selected:
            raise PluginError(
                "no enabled and available plugins support the root target/profile selection"
            )
        created_new = not bool(case_identifier)
        if case_identifier:
            workspace = self.cases.resolve(case_identifier)
        else:
            workspace = self.cases.create(
                case_name or target,
                description=f"MIA investigation rooted at {target}",
                initial_target=target,
                initial_target_type=target_type,
            )
        pivot_config = self.config.pivoting.model_copy(deep=True)
        if enable_pivoting is not None:
            pivot_config.enabled = enable_pivoting
        if max_depth is not None:
            pivot_config.max_depth = max_depth
        if max_targets is not None:
            pivot_config.max_targets = max_targets

        outcome = InvestigationResult(workspace=workspace)
        queue = PivotQueue(pivot_config)
        queue.mark_visited(target, target_type)

        try:
            root = await self.orchestrator.scan(
                target,
                target_type,
                profile,
                include,
                exclude,
                event_callback,
                workspace=workspace,
                depth=0,
                use_cache=use_cache,
            )
            if root.successful_plugins == 0:
                raise PluginError("no root-scan plugin completed successfully")
        except Exception:
            if created_new:
                shutil.rmtree(workspace.root, ignore_errors=True)
            raise
        outcome.scans.append(root)
        self._ingest_scan(workspace, root)

        if pivot_config.enabled:
            candidates = extract_pivots(root, pivot_config)
            self._attach_source_nodes(workspace, candidates)
            queue.enqueue(candidates, depth=1, parent_scan_id=root.scan_id)

        while queue:
            task = queue.pop()
            if task is None:
                break
            if task.depth > pivot_config.max_depth:
                outcome.skipped_pivots.append(f"{task.candidate.target}: maximum depth exceeded")
                continue
            child_profile = pivot_config.child_profile
            child = await self.orchestrator.scan(
                task.candidate.target,
                task.candidate.target_type,
                child_profile,
                None,
                exclude,
                event_callback,
                workspace=workspace,
                depth=task.depth,
                parent_scan_id=task.parent_scan_id,
                pivot_source_node_id=task.candidate.source_node_id,
                use_cache=use_cache,
            )
            outcome.scans.append(child)
            self._ingest_scan(workspace, child)
            if task.depth < pivot_config.max_depth:
                candidates = extract_pivots(child, pivot_config)
                self._attach_source_nodes(workspace, candidates)
                queue.enqueue(
                    candidates,
                    depth=task.depth + 1,
                    parent_scan_id=child.scan_id,
                )

        nodes, edges = workspace.nodes(), workspace.edges()
        outcome.graph_paths = export_all_graph_formats(workspace.graph_dir, nodes, edges)
        workspace.export_payload()
        self.knowledge.ingest(workspace.record, nodes)
        if self.config.workspaces.auto_correlate:
            outcome.correlations = self.knowledge.correlations_for_case(workspace.record.case_id)

        assistant = InvestigationAssistant(self.config)
        outcome.assistant_summary = assistant.local_summary(nodes, edges, outcome.correlations)
        write_summary(workspace.reports_dir, outcome.assistant_summary)
        outcome.dashboard_path = write_dashboard(
            workspace,
            raw_excerpt_bytes=self.config.reports.dashboard_raw_excerpt_bytes,
            assistant_summary=outcome.assistant_summary,
            correlations=outcome.correlations,
            max_nodes=self.config.workspaces.graph_max_nodes_in_dashboard,
        )
        self.logger.info(
            "Investigation %s completed with %d scans, %d nodes, and %d edges",
            workspace.record.case_id,
            len(outcome.scans),
            len(nodes),
            len(edges),
        )
        return outcome

    def _ingest_scan(self, workspace: CaseWorkspace, result: ScanResult) -> None:
        nodes, edges, events = build_graph(workspace.record.case_id, result, self.config.confidence)
        workspace.save_graph(nodes, edges, events)
        # Keep shared knowledge current after each scan so interrupted cases remain searchable.
        self.knowledge.ingest(workspace.record, workspace.nodes())

    @staticmethod
    def _attach_source_nodes(workspace: CaseWorkspace, candidates: list[object]) -> None:
        by_finding_key = {
            str(node.attributes.get("finding_key")): node.node_id
            for node in workspace.nodes()
            if node.attributes.get("finding_key")
        }
        for candidate in candidates:
            key = candidate.source_finding_key
            if key and key in by_finding_key:
                candidate.source_node_id = by_finding_key[key]
