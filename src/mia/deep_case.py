from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from mia.account_discovery import LinkedAccountImporter, expand_account_seeds
from mia.assistant import InvestigationAssistant, write_summary
from mia.config import AppConfig
from mia.graph import canonical_entity, export_all_graph_formats, stable_edge_id, stable_node_id
from mia.investigation import InvestigationEngine
from mia.knowledge import KnowledgeDatabase
from mia.models import (
    ConfidenceFactor,
    DeepCaseManifest,
    DeepCaseSeed,
    EvidenceEdge,
    EvidenceEffect,
    EvidenceNode,
    IdentityCluster,
    ReviewTask,
    ScanProfile,
    ScanResult,
    TargetType,
)
from mia.orchestrator import EventCallback, Orchestrator
from mia.pivot import PivotQueue, extract_pivots
from mia.reports.dashboard import write_dashboard
from mia.targeting import validate_target
from mia.utils import atomic_write_json, atomic_write_text
from mia.verification import IdentityClusterEngine, ProfileVerifier
from mia.workspace import CaseManager, CaseWorkspace

SCANNABLE_TYPES = {
    TargetType.USERNAME,
    TargetType.EMAIL,
    TargetType.DOMAIN,
    TargetType.IP,
    TargetType.PHONE,
    TargetType.FILE,
    TargetType.HASH,
    TargetType.PERSON,
    TargetType.URL,
    TargetType.CERTIFICATE,
    TargetType.COMPANY,
}


@dataclass(slots=True)
class DeepCaseResult:
    workspace: CaseWorkspace
    scans: list[ScanResult] = field(default_factory=list)
    failed_seeds: list[str] = field(default_factory=list)
    skipped_seeds: list[str] = field(default_factory=list)
    verifications: int = 0
    clusters: list[IdentityCluster] = field(default_factory=list)
    review_tasks: list[ReviewTask] = field(default_factory=list)
    dashboard_path: Path | None = None
    graph_paths: dict[str, str] = field(default_factory=dict)
    total_seed_count: int = 0
    new_seed_count: int = 0
    generated_account_leads: int = 0


def seed_id(target_type: TargetType, target: str, subject: str | None = None) -> str:
    digest = hashlib.sha256(f"{target_type.value}|{target}|{subject or ''}".encode()).hexdigest()[
        :20
    ]
    return f"seed-{digest}"


def normalize_manifest(manifest: DeepCaseManifest) -> DeepCaseManifest:
    output: list[DeepCaseSeed] = []
    seen: set[tuple[str, str, str]] = set()
    for seed in manifest.seeds:
        target = validate_target(seed.target, seed.target_type)
        subject = (seed.subject or "").strip()
        key = (
            seed.target_type.value,
            canonical_entity(seed.target_type.value, target),
            subject.casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(
            seed.model_copy(
                update={
                    "seed_id": seed.seed_id or seed_id(seed.target_type, target, seed.subject),
                    "target": target,
                    "label": seed.label or target,
                    "subject": subject or None,
                }
            )
        )
    manifest.seeds = output
    if not manifest.seeds:
        raise ValueError("a deep case needs at least one seed")
    return manifest


def load_manifest(path: Path) -> DeepCaseManifest:
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw) if path.suffix.lower() == ".json" else yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError("deep-case manifest must be a YAML or JSON mapping")
    # Friendly shorthand: usernames/emails/domains/etc. at top level.
    seeds = list(payload.get("seeds") or [])
    aliases = {
        "usernames": TargetType.USERNAME,
        "emails": TargetType.EMAIL,
        "domains": TargetType.DOMAIN,
        "ips": TargetType.IP,
        "phones": TargetType.PHONE,
        "people": TargetType.PERSON,
        "companies": TargetType.COMPANY,
        "addresses": TargetType.ADDRESS,
        "locations": TargetType.LOCATION,
        "urls": TargetType.URL,
        "hashes": TargetType.HASH,
        "certificates": TargetType.CERTIFICATE,
        "files": TargetType.FILE,
    }
    for key, target_type in aliases.items():
        values = payload.pop(key, []) or []
        for value in values:
            if isinstance(value, str):
                seeds.append({"target": value, "target_type": target_type.value})
            elif isinstance(value, dict):
                seeds.append({**value, "target_type": target_type.value})
    payload["seeds"] = seeds
    return normalize_manifest(DeepCaseManifest.model_validate(payload))


def write_manifest(path: Path, manifest: DeepCaseManifest) -> None:
    atomic_write_text(
        path,
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
    )


class DeepCaseEngine:
    """Run many heterogeneous seeds as one evidence-aware investigation."""

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
        self.ingester = InvestigationEngine(config, orchestrator, knowledge, logger)

    async def run(
        self,
        manifest: DeepCaseManifest,
        *,
        case_identifier: str | None = None,
        profile: ScanProfile | None = None,
        verify_profiles: bool | None = None,
        enable_pivoting: bool | None = None,
        max_depth: int | None = None,
        max_targets: int | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        event_callback: EventCallback | None = None,
        use_cache: bool | None = None,
    ) -> DeepCaseResult:
        manifest = normalize_manifest(manifest)
        profile = profile or self.config.deep_cases.profile
        generated_account_leads = 0
        if manifest.workflow == "account-discovery" and self.config.account_discovery.enabled:
            expanded, generated_account_leads = expand_account_seeds(
                manifest.seeds,
                profile,
                enabled=True,
                generate_variants=self.config.account_discovery.generate_variants,
                max_generated=self.config.account_discovery.max_generated_variants,
            )
            manifest = normalize_manifest(manifest.model_copy(update={"seeds": expanded}))
        incoming_notes = manifest.notes
        incoming_hypotheses = list(manifest.hypotheses)
        incoming_seeds = list(manifest.seeds)
        created_new = case_identifier is None
        if case_identifier:
            workspace = self.cases.resolve(case_identifier)
            existing_manifest_path = workspace.root / "deep-case.yaml"
            existing_manifest = (
                load_manifest(existing_manifest_path)
                if existing_manifest_path.exists()
                else DeepCaseManifest(
                    name=workspace.record.name,
                    description=workspace.record.description,
                    tags=workspace.record.tags,
                    seeds=[],
                )
            )
            existing = [DeepCaseSeed.model_validate(item) for item in workspace.deep_seeds()]
            existing_keys = {
                (
                    item.target_type.value,
                    canonical_entity(item.target_type.value, item.target),
                    (item.subject or "").strip().casefold(),
                )
                for item in existing
            }
            incoming_seeds = [
                item
                for item in incoming_seeds
                if (
                    item.target_type.value,
                    canonical_entity(item.target_type.value, item.target),
                    (item.subject or "").strip().casefold(),
                )
                not in existing_keys
            ]
            manifest = normalize_manifest(
                manifest.model_copy(
                    update={
                        "name": workspace.record.name,
                        "workflow": manifest.workflow or existing_manifest.workflow,
                        "description": manifest.description
                        or existing_manifest.description
                        or workspace.record.description,
                        "tags": sorted(
                            set(workspace.record.tags)
                            | set(existing_manifest.tags)
                            | set(manifest.tags)
                        ),
                        "hypotheses": list(
                            dict.fromkeys([*existing_manifest.hypotheses, *manifest.hypotheses])
                        ),
                        "notes": "\n".join(
                            item
                            for item in (existing_manifest.notes, manifest.notes)
                            if item.strip()
                        ).strip(),
                        "seeds": [*existing, *incoming_seeds],
                    }
                )
            )
        else:
            workspace = self.cases.create(
                manifest.name,
                description=manifest.description or "MIA multi-seed deep investigation",
                tags=manifest.tags,
                initial_target=manifest.seeds[0].target,
                initial_target_type=manifest.seeds[0].target_type,
            )
        result = DeepCaseResult(workspace=workspace)
        result.generated_account_leads = generated_account_leads
        try:
            workspace.save_deep_seeds(manifest.seeds)
            write_manifest(workspace.root / "deep-case.yaml", manifest)
            if incoming_notes.strip():
                workspace.append_note(incoming_notes)
            for hypothesis in incoming_hypotheses:
                workspace.append_note(f"Hypothesis (unverified): {hypothesis}")
            graph_manifest = manifest.model_copy(update={"seeds": incoming_seeds})
            if incoming_seeds:
                self._save_seed_graph(workspace, graph_manifest)

            pivot_config = self.config.pivoting.model_copy(deep=True)
            pivot_config.enabled = (
                self.config.deep_cases.enable_pivoting
                if enable_pivoting is None
                else enable_pivoting
            )
            pivot_config.max_depth = (
                max_depth if max_depth is not None else self.config.deep_cases.max_depth
            )
            pivot_config.max_targets = (
                max_targets if max_targets is not None else self.config.deep_cases.max_targets
            )
            queue = PivotQueue(pivot_config)
            seed_nodes = {
                (
                    seed.target_type.value,
                    canonical_entity(seed.target_type.value, seed.target),
                ): stable_node_id(
                    workspace.record.case_id,
                    seed.target_type.value,
                    canonical_entity(seed.target_type.value, seed.target),
                )
                for seed in incoming_seeds
            }

            for seed in incoming_seeds:
                queue.mark_visited(seed.target, seed.target_type)
                if seed.target_type not in SCANNABLE_TYPES:
                    result.skipped_seeds.append(
                        f"{seed.target_type.value}:{seed.target} (stored as context; no scanner)"
                    )
                    continue
                try:
                    selected = self.orchestrator.select_plugins(
                        seed.target_type, profile, include, exclude
                    )
                except Exception as exc:
                    result.failed_seeds.append(f"{seed.target_type.value}:{seed.target}: {exc}")
                    continue
                if not selected:
                    result.skipped_seeds.append(
                        f"{seed.target_type.value}:{seed.target} (no available compatible plugin)"
                    )
                    continue
                try:
                    scan = await self.orchestrator.scan(
                        seed.target,
                        seed.target_type,
                        profile,
                        include,
                        exclude,
                        event_callback,
                        workspace=workspace,
                        depth=0,
                        pivot_source_node_id=seed_nodes.get(
                            (
                                seed.target_type.value,
                                canonical_entity(seed.target_type.value, seed.target),
                            )
                        ),
                        use_cache=use_cache,
                    )
                    result.scans.append(scan)
                    self.ingester._ingest_scan(workspace, scan)
                    if pivot_config.enabled:
                        candidates = extract_pivots(scan, pivot_config)
                        self.ingester._attach_source_nodes(workspace, candidates)
                        queue.enqueue(candidates, depth=1, parent_scan_id=scan.scan_id)
                except Exception as exc:
                    result.failed_seeds.append(f"{seed.target_type.value}:{seed.target}: {exc}")
                    if not self.config.deep_cases.continue_on_seed_failure:
                        raise

            while queue:
                task = queue.pop()
                if task is None:
                    break
                if task.depth > pivot_config.max_depth:
                    continue
                try:
                    selected = self.orchestrator.select_plugins(
                        task.candidate.target_type,
                        pivot_config.child_profile,
                        None,
                        exclude,
                    )
                    if not selected:
                        continue
                    child = await self.orchestrator.scan(
                        task.candidate.target,
                        task.candidate.target_type,
                        pivot_config.child_profile,
                        None,
                        exclude,
                        event_callback,
                        workspace=workspace,
                        depth=task.depth,
                        parent_scan_id=task.parent_scan_id,
                        pivot_source_node_id=task.candidate.source_node_id,
                        use_cache=use_cache,
                    )
                    result.scans.append(child)
                    self.ingester._ingest_scan(workspace, child)
                    if task.depth < pivot_config.max_depth:
                        candidates = extract_pivots(child, pivot_config)
                        self.ingester._attach_source_nodes(workspace, candidates)
                        queue.enqueue(
                            candidates,
                            depth=task.depth + 1,
                            parent_scan_id=child.scan_id,
                        )
                except Exception as exc:
                    result.failed_seeds.append(
                        f"pivot {task.candidate.target_type.value}:{task.candidate.target}: {exc}"
                    )

            should_verify = (
                self.config.deep_cases.verify_profiles
                if verify_profiles is None
                else verify_profiles
            )
            if manifest.workflow in {"email-enrichment", "domain-recon", "timeline"}:
                should_verify = False if verify_profiles is None else verify_profiles
            if should_verify and self.config.verification.enabled:
                verifier = ProfileVerifier(self.config)
                verifications = await verifier.verify_case(workspace)
                result.verifications = len(verifications)
                if (
                    manifest.workflow == "account-discovery"
                    and self.config.account_discovery.enabled
                    and self.config.account_discovery.follow_public_profile_links
                ):
                    importer = LinkedAccountImporter()
                    for _ in range(self.config.account_discovery.max_link_hops):
                        linked_nodes = importer.import_from_verifications(workspace)
                        if not linked_nodes:
                            break
                        linked_verifications = await verifier.verify_nodes(workspace, linked_nodes)
                        result.verifications += len(linked_verifications)
            result.clusters, result.review_tasks, _ = IdentityClusterEngine(self.config).run(
                workspace
            )
            nodes, edges = workspace.nodes(), workspace.edges()
            result.graph_paths = export_all_graph_formats(workspace.graph_dir, nodes, edges)
            workspace.export_payload()
            self.knowledge.ingest(workspace.record, nodes)
            correlations = (
                self.knowledge.correlations_for_case(workspace.record.case_id)
                if self.config.workspaces.auto_correlate
                else []
            )
            summary = InvestigationAssistant(self.config).local_summary(nodes, edges, correlations)
            write_summary(workspace.reports_dir, summary)
            result.dashboard_path = write_dashboard(
                workspace,
                raw_excerpt_bytes=self.config.reports.dashboard_raw_excerpt_bytes,
                assistant_summary=summary,
                correlations=correlations,
                max_nodes=self.config.workspaces.graph_max_nodes_in_dashboard,
            )
            atomic_write_json(
                workspace.exports_dir / "deep-case-result.json",
                {
                    "case_id": workspace.record.case_id,
                    "seed_count": len(manifest.seeds),
                    "new_seed_count": len(incoming_seeds),
                    "generated_account_leads": result.generated_account_leads,
                    "scan_count": len(result.scans),
                    "failed_seeds": result.failed_seeds,
                    "skipped_seeds": result.skipped_seeds,
                    "verification_count": result.verifications,
                    "cluster_count": len(result.clusters),
                    "review_task_count": len(result.review_tasks),
                },
            )
            result.total_seed_count = len(manifest.seeds)
            result.new_seed_count = len(incoming_seeds)
            return result
        except Exception:
            if created_new:
                shutil.rmtree(workspace.root, ignore_errors=True)
            raise

    def _save_seed_graph(self, workspace: CaseWorkspace, manifest: DeepCaseManifest) -> None:
        subject_value = workspace.record.case_id
        subject = EvidenceNode(
            node_id=stable_node_id(workspace.record.case_id, "case_subject", subject_value),
            case_id=workspace.record.case_id,
            entity_type="case_subject",
            label=manifest.name,
            value=subject_value,
            canonical_value=subject_value,
            confidence=1.0,
            confidence_label="High",
            sources=["user"],
            attributes={
                "root_target": True,
                "deep_case": True,
                "hypotheses": manifest.hypotheses,
                "workflow": manifest.workflow,
            },
            manual=True,
        )
        node_map: dict[str, EvidenceNode] = {subject.node_id: subject}
        edges: list[EvidenceEdge] = []
        for seed in manifest.seeds:
            canonical = canonical_entity(seed.target_type.value, seed.target)
            node_id = stable_node_id(workspace.record.case_id, seed.target_type.value, canonical)
            node = node_map.get(node_id)
            if node is None:
                node = EvidenceNode(
                    node_id=node_id,
                    case_id=workspace.record.case_id,
                    entity_type=seed.target_type.value,
                    label=seed.label or seed.target,
                    value=seed.target,
                    canonical_value=canonical,
                    confidence=seed.confidence,
                    confidence_label="High" if seed.confidence >= 0.85 else "Medium",
                    sources=["user"],
                    attributes={
                        "deep_seed": True,
                        "seed_ids": [seed.seed_id],
                        "notes": [seed.notes] if seed.notes else [],
                        "tags": sorted(set(seed.tags)),
                        "subjects": [seed.subject] if seed.subject else [],
                    },
                    manual=True,
                )
                node_map[node_id] = node
            else:
                node.confidence = max(node.confidence, seed.confidence)
                node.confidence_label = "High" if node.confidence >= 0.85 else "Medium"
                node.attributes["seed_ids"] = list(
                    dict.fromkeys([*node.attributes.get("seed_ids", []), seed.seed_id])
                )
                if seed.notes:
                    node.attributes["notes"] = list(
                        dict.fromkeys([*node.attributes.get("notes", []), seed.notes])
                    )
                node.attributes["tags"] = sorted(
                    set(node.attributes.get("tags", [])) | set(seed.tags)
                )
                if seed.subject:
                    node.attributes["subjects"] = list(
                        dict.fromkeys([*node.attributes.get("subjects", []), seed.subject])
                    )

            parent = subject
            relation = "case_seed"
            label = "provided case seed"
            if seed.subject:
                subject_canonical = canonical_entity("candidate_subject", seed.subject)
                subject_id = stable_node_id(
                    workspace.record.case_id, "candidate_subject", subject_canonical
                )
                parent = node_map.get(subject_id) or EvidenceNode(
                    node_id=subject_id,
                    case_id=workspace.record.case_id,
                    entity_type="candidate_subject",
                    label=seed.subject,
                    value=seed.subject,
                    canonical_value=subject_canonical,
                    confidence=0.5,
                    confidence_label="Low",
                    sources=["user"],
                    attributes={
                        "deep_case_subject": True,
                        "warning": "A subject label groups investigator context; it is not identity proof.",
                    },
                    manual=True,
                )
                if subject_id not in node_map:
                    node_map[subject_id] = parent
                    edges.append(
                        EvidenceEdge(
                            edge_id=stable_edge_id(
                                workspace.record.case_id,
                                subject.node_id,
                                parent.node_id,
                                "candidate_subject",
                            ),
                            case_id=workspace.record.case_id,
                            source_node_id=subject.node_id,
                            target_node_id=parent.node_id,
                            relation="candidate_subject",
                            label="candidate subject",
                            confidence=0.5,
                            confidence_label="Low",
                            reasons=[
                                "The investigator supplied this label to organize case context."
                            ],
                            evidence_refs=[seed.seed_id],
                        )
                    )
                relation = "subject_context"
                label = "provided subject context"
            edges.append(
                EvidenceEdge(
                    edge_id=stable_edge_id(
                        workspace.record.case_id, parent.node_id, node.node_id, relation
                    ),
                    case_id=workspace.record.case_id,
                    source_node_id=parent.node_id,
                    target_node_id=node.node_id,
                    relation=relation,
                    label=label,
                    confidence=seed.confidence,
                    confidence_label="High" if seed.confidence >= 0.85 else "Medium",
                    reasons=["The user explicitly supplied this item as case context."],
                    factors=[
                        ConfidenceFactor(
                            factor_id="user-supplied-seed",
                            label="User-supplied context",
                            effect=EvidenceEffect.NEUTRAL,
                            weight=0.0,
                            explanation=(
                                "This records what the investigator supplied. It does not prove "
                                "that the seed belongs to the same identity as other seeds."
                            ),
                            evidence_refs=[seed.seed_id],
                        )
                    ],
                    evidence_refs=[seed.seed_id],
                )
            )
        workspace.save_graph(list(node_map.values()), edges, [])
