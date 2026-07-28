from __future__ import annotations

import hashlib
import html
import ipaddress
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, ElementTree, SubElement

from mia.config import ConfidenceConfig
from mia.models import (
    ConfidenceFactor,
    EvidenceEdge,
    EvidenceEffect,
    EvidenceNode,
    MergedFinding,
    ScanResult,
    TimelineEvent,
)
from mia.normalizer import canonicalize_url
from mia.utils import atomic_write_json, atomic_write_text

DATE_KEYS = {
    "created_at",
    "creation_date",
    "created",
    "registered_at",
    "registration_date",
    "first_seen",
    "firstseen",
    "last_seen",
    "lastseen",
    "breach_date",
    "added_date",
    "modified_at",
    "updated_at",
    "timestamp",
    "date",
}

ENTITY_KIND_MAP = {
    "email_account": "account",
    "profile": "account",
    "web_profile": "account",
    "username": "username",
    "email": "email",
    "domain": "domain",
    "subdomain": "domain",
    "lookalike_domain": "domain",
    "dns": "dns_record",
    "whois": "domain_record",
    "ip": "ip",
    "phone": "phone",
    "phone_summary": "phone_intelligence",
    "hash": "hash",
    "hash_algorithm": "hash_algorithm",
    "certificate": "certificate",
    "url": "url",
    "web_endpoint": "website",
    "metadata": "metadata",
    "breach": "breach",
    "repository": "repository",
    "company": "company",
    "file": "document",
}


def confidence_label(score: float) -> str:
    if score >= 0.85:
        return "High"
    if score >= 0.65:
        return "Medium"
    if score >= 0.40:
        return "Low"
    return "Very low"


def canonical_entity(entity_type: str, value: str) -> str:
    cleaned = value.strip()
    if entity_type in {"email", "username", "domain", "account", "company"}:
        return cleaned.lower().rstrip(".")
    if entity_type == "ip":
        try:
            return str(ipaddress.ip_address(cleaned))
        except ValueError:
            return cleaned.lower()
    if entity_type == "phone":
        return re.sub(r"[^0-9+]", "", cleaned)
    if entity_type in {"url", "website", "repository"}:
        try:
            return canonicalize_url(cleaned)
        except ValueError:
            return cleaned
    if entity_type in {"hash", "certificate"}:
        return re.sub(r"[^a-fA-F0-9]", "", cleaned).lower()
    return cleaned.lower()


def stable_node_id(case_id: str, entity_type: str, canonical_value: str) -> str:
    digest = hashlib.sha256(f"{case_id}|{entity_type}|{canonical_value}".encode()).hexdigest()[:20]
    return f"node-{digest}"


def stable_edge_id(case_id: str, source: str, target: str, relation: str) -> str:
    digest = hashlib.sha256(f"{case_id}|{source}|{target}|{relation}".encode()).hexdigest()[:20]
    return f"edge-{digest}"


def _target_entity_type(result: ScanResult) -> str:
    return {
        "file": "document",
        "person": "person",
        "certificate": "certificate",
    }.get(result.target_type.value, result.target_type.value)


def _relation_for(finding: MergedFinding) -> tuple[str, str]:
    if finding.kind in {"profile", "web_profile", "email_account"}:
        return "has_account", "has account"
    if finding.kind in {"domain", "subdomain", "lookalike_domain"}:
        return "associated_domain", "associated domain"
    if finding.kind == "ip":
        return "resolves_to", "resolves to"
    if finding.kind == "email":
        return "associated_email", "associated email"
    if finding.kind == "phone":
        return "associated_phone", "associated phone"
    if finding.kind == "breach":
        return "appeared_in", "appeared in"
    if finding.kind == "certificate":
        return "uses_certificate", "uses certificate"
    if finding.kind == "repository":
        return "owns_repository", "owns repository"
    if finding.kind == "hash_algorithm":
        return "possible_algorithm", "may use algorithm"
    return "reported_by", "reported finding"


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        try:
            # API timestamps may be seconds or milliseconds.
            seconds = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text += "T00:00:00+00:00"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _timeline_events(
    case_id: str, node: EvidenceNode, finding: MergedFinding
) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for key, value in finding.attributes.items():
        normalized = key.lower().replace("-", "_")
        if normalized not in DATE_KEYS:
            continue
        occurred = _parse_datetime(value)
        if not occurred:
            continue
        event_id = (
            "event-"
            + hashlib.sha256(
                f"{case_id}|{node.node_id}|{normalized}|{occurred.isoformat()}".encode()
            ).hexdigest()[:20]
        )
        events.append(
            TimelineEvent(
                event_id=event_id,
                case_id=case_id,
                title=f"{node.label}: {normalized.replace('_', ' ')}",
                event_type=normalized,
                occurred_at=occurred,
                node_id=node.node_id,
                source=", ".join(finding.sources),
                evidence_refs=finding.evidence_paths,
                attributes={"value": value},
            )
        )
    return events


def build_graph(
    case_id: str,
    result: ScanResult,
    confidence_config: ConfidenceConfig,
) -> tuple[list[EvidenceNode], list[EvidenceEdge], list[TimelineEvent]]:
    root_type = _target_entity_type(result)
    root_canonical = canonical_entity(root_type, result.target)
    root = EvidenceNode(
        node_id=stable_node_id(case_id, root_type, root_canonical),
        case_id=case_id,
        entity_type=root_type,
        label=result.target,
        value=result.target,
        canonical_value=root_canonical,
        confidence=1.0,
        confidence_label="High",
        sources=["user"],
        attributes={
            "root_target": result.depth == 0,
            "pivot_target": result.depth > 0,
            "target_type": result.target_type.value,
            "scan_id": result.scan_id,
            "depth": result.depth,
        },
    )
    nodes = [root]
    edges: list[EvidenceEdge] = []
    if result.pivot_source_node_id:
        scan_node = EvidenceNode(
            node_id=stable_node_id(case_id, "scan", result.scan_id),
            case_id=case_id,
            entity_type="scan",
            label=f"Follow-up scan: {result.target}",
            value=result.scan_id,
            canonical_value=result.scan_id,
            confidence=1.0,
            confidence_label="High",
            sources=["mia"],
            attributes={
                "workflow_node": True,
                "target": result.target,
                "target_type": result.target_type.value,
                "profile": result.profile.value,
                "depth": result.depth,
                "parent_scan_id": result.parent_scan_id,
            },
        )
        nodes.append(scan_node)
        edges.append(
            EvidenceEdge(
                edge_id=stable_edge_id(
                    case_id, result.pivot_source_node_id, scan_node.node_id, "triggered_scan"
                ),
                case_id=case_id,
                source_node_id=result.pivot_source_node_id,
                target_node_id=scan_node.node_id,
                relation="triggered_scan",
                label="triggered follow-up scan",
                confidence=1.0,
                confidence_label="High",
                reasons=[
                    "MIA extracted this explicit indicator and used it as a follow-up scan target."
                ],
                factors=[
                    ConfidenceFactor(
                        factor_id="automatic-pivot",
                        label="Investigation workflow",
                        effect=EvidenceEffect.NEUTRAL,
                        weight=0.0,
                        explanation=(
                            "This edge records an automated workflow action. It is not evidence that "
                            "the connected entities belong to the same person or organization."
                        ),
                    )
                ],
                attributes={
                    "scan_id": result.scan_id,
                    "parent_scan_id": result.parent_scan_id,
                    "depth": result.depth,
                },
            )
        )
    events: list[TimelineEvent] = []
    for finding in result.findings:
        entity_type = ENTITY_KIND_MAP.get(finding.kind, finding.kind or "finding")
        value = finding.url or finding.value
        canonical = canonical_entity(entity_type, value)
        node = EvidenceNode(
            node_id=stable_node_id(case_id, entity_type, canonical),
            case_id=case_id,
            entity_type=entity_type,
            label=finding.title,
            value=value,
            canonical_value=canonical,
            confidence=finding.confidence,
            confidence_label=finding.confidence_label,
            sources=finding.sources,
            evidence_refs=finding.evidence_paths,
            attributes={
                **finding.attributes,
                "finding_kind": finding.kind,
                "finding_key": finding.dedup_key,
                "status": finding.status.value,
                "url": finding.url,
            },
            first_seen=finding.observed_at,
            last_seen=finding.observed_at,
        )
        if node.node_id == root.node_id:
            root.sources = sorted(set(root.sources) | set(finding.sources))
            root.evidence_refs = sorted(set(root.evidence_refs) | set(finding.evidence_paths))
            root.attributes = {**root.attributes, **finding.attributes}
            observations = list(root.attributes.get("observations", []))
            observations.append(
                {
                    "title": finding.title,
                    "confidence": finding.confidence,
                    "sources": finding.sources,
                    "finding_key": finding.dedup_key,
                }
            )
            root.attributes["observations"] = observations
            events.extend(_timeline_events(case_id, root, finding))
            continue
        nodes.append(node)
        relation, label = _relation_for(finding)
        base_weight = confidence_config.relationship_weights.get(relation, finding.confidence)
        edge_confidence = min(0.99, (base_weight + finding.confidence) / 2)
        factors = list(finding.confidence_factors)
        factors.append(
            ConfidenceFactor(
                factor_id=f"relationship-{relation}",
                label=label.title(),
                effect=EvidenceEffect.POSITIVE,
                weight=base_weight,
                explanation=f"The normalized finding type maps to the relationship '{label}'.",
                evidence_refs=finding.evidence_paths,
            )
        )
        edges.append(
            EvidenceEdge(
                edge_id=stable_edge_id(case_id, root.node_id, node.node_id, relation),
                case_id=case_id,
                source_node_id=root.node_id,
                target_node_id=node.node_id,
                relation=relation,
                label=label,
                confidence=edge_confidence,
                confidence_label=confidence_label(edge_confidence),
                reasons=[
                    *finding.confidence_reasons,
                    f"Relationship inferred from kind: {finding.kind}",
                ],
                factors=factors,
                evidence_refs=finding.evidence_paths,
                attributes={"scan_id": result.scan_id, "depth": result.depth},
            )
        )
        events.extend(_timeline_events(case_id, node, finding))
    # Stable IDs make de-duplication deterministic across scans.
    node_map: dict[str, EvidenceNode] = {}
    for node in nodes:
        previous = node_map.get(node.node_id)
        if not previous:
            node_map[node.node_id] = node
            continue
        previous.confidence = max(previous.confidence, node.confidence)
        previous.confidence_label = confidence_label(previous.confidence)
        previous.sources = sorted(set(previous.sources) | set(node.sources))
        previous.evidence_refs = sorted(set(previous.evidence_refs) | set(node.evidence_refs))
        previous.attributes = {**previous.attributes, **node.attributes}
    edge_map = {edge.edge_id: edge for edge in edges}
    event_map = {event.event_id: event for event in events}
    return list(node_map.values()), list(edge_map.values()), list(event_map.values())


def export_graph_json(path: Path, nodes: list[EvidenceNode], edges: list[EvidenceEdge]) -> Path:
    atomic_write_json(
        path,
        {
            "nodes": [node.model_dump(mode="json") for node in nodes],
            "edges": [edge.model_dump(mode="json") for edge in edges],
        },
    )
    return path


def export_graphml(path: Path, nodes: list[EvidenceNode], edges: list[EvidenceEdge]) -> Path:
    graphml = Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
    for key_id, target, name, attr_type in (
        ("label", "node", "label", "string"),
        ("entity_type", "node", "entity_type", "string"),
        ("confidence", "all", "confidence", "double"),
        ("relation", "edge", "relation", "string"),
    ):
        SubElement(
            graphml,
            "key",
            id=key_id,
            **{"for": target, "attr.name": name, "attr.type": attr_type},
        )
    graph = SubElement(graphml, "graph", id="MIA", edgedefault="directed")
    for node in nodes:
        element = SubElement(graph, "node", id=node.node_id)
        SubElement(element, "data", key="label").text = node.label
        SubElement(element, "data", key="entity_type").text = node.entity_type
        SubElement(element, "data", key="confidence").text = str(node.confidence)
    for edge in edges:
        element = SubElement(
            graph,
            "edge",
            id=edge.edge_id,
            source=edge.source_node_id,
            target=edge.target_node_id,
        )
        SubElement(element, "data", key="relation").text = edge.relation
        SubElement(element, "data", key="confidence").text = str(edge.confidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree(graphml).write(path, encoding="utf-8", xml_declaration=True)
    return path


def export_gexf(path: Path, nodes: list[EvidenceNode], edges: list[EvidenceEdge]) -> Path:
    gexf = Element("gexf", xmlns="http://www.gexf.net/1.3", version="1.3")
    graph = SubElement(gexf, "graph", mode="static", defaultedgetype="directed")
    nodes_el = SubElement(graph, "nodes")
    for node in nodes:
        SubElement(nodes_el, "node", id=node.node_id, label=node.label)
    edges_el = SubElement(graph, "edges")
    for index, edge in enumerate(edges):
        SubElement(
            edges_el,
            "edge",
            id=str(index),
            source=edge.source_node_id,
            target=edge.target_node_id,
            label=edge.label,
            weight=str(edge.confidence),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree(gexf).write(path, encoding="utf-8", xml_declaration=True)
    return path


def export_mermaid(path: Path, nodes: list[EvidenceNode], edges: list[EvidenceEdge]) -> Path:
    lines = ["graph LR"]
    for node in nodes:
        safe_label = html.escape(node.label.replace('"', "'"))[:100]
        lines.append(f'  {node.node_id.replace("-", "_")}["{safe_label}"]')
    for edge in edges:
        source = edge.source_node_id.replace("-", "_")
        target = edge.target_node_id.replace("-", "_")
        label = edge.label.replace('"', "'")[:60]
        lines.append(f'  {source} -->|"{label}"| {target}')
    atomic_write_text(path, "\n".join(lines) + "\n")
    return path


def export_all_graph_formats(
    directory: Path, nodes: list[EvidenceNode], edges: list[EvidenceEdge]
) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": export_graph_json(directory / "graph.json", nodes, edges),
        "graphml": export_graphml(directory / "graph.graphml", nodes, edges),
        "gexf": export_gexf(directory / "graph.gexf", nodes, edges),
        "mermaid": export_mermaid(directory / "graph.mmd", nodes, edges),
    }
    return {key: str(value) for key, value in paths.items()}
