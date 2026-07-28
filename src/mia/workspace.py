from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import secrets
import shutil
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from mia.exceptions import MIAError
from mia.models import (
    CaseAttachment,
    CaseRecord,
    CaseStatus,
    EvidenceEdge,
    EvidenceNode,
    IdentityCluster,
    ProfileVerification,
    ReviewStatus,
    ReviewTask,
    ScanResult,
    TimelineEvent,
)
from mia.utils import atomic_write_json, atomic_write_text, safe_slug


class CaseNotFoundError(MIAError):
    pass


class CaseWorkspace:
    """Persistent on-disk investigation workspace."""

    def __init__(self, root: Path, record: CaseRecord) -> None:
        self.root = root
        self.record = record
        self.db_path = root / "case.db"
        self.notes_path = root / "notes.md"
        self.evidence_dir = root / "evidence"
        self.screenshots_dir = root / "screenshots"
        self.reports_dir = root / "reports"
        self.timeline_dir = root / "timeline"
        self.graph_dir = root / "graph"
        self.exports_dir = root / "exports"
        self.logs_dir = root / "logs"
        self.scans_dir = root / "scans"
        self.snapshots_dir = root / "snapshots"
        self.analysis_dir = root / "analysis"
        self._ensure_layout()
        self._initialize_database()

    def _ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path in (
            self.evidence_dir,
            self.screenshots_dir,
            self.reports_dir,
            self.timeline_dir,
            self.graph_dir,
            self.exports_dir,
            self.logs_dir,
            self.scans_dir,
            self.snapshots_dir,
            self.analysis_dir,
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.notes_path.exists():
            atomic_write_text(
                self.notes_path,
                f"# {self.record.name}\n\nInvestigation notes. Treat automated findings as leads, not proof.\n",
            )
        self.write_manifest()

    def write_manifest(self) -> None:
        manifest = self.record.model_dump(mode="json")
        atomic_write_text(self.root / "case.yaml", yaml.safe_dump(manifest, sort_keys=False))

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS case_meta (
                    case_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scans (
                    scan_id TEXT PRIMARY KEY,
                    depth INTEGER NOT NULL,
                    parent_scan_id TEXT,
                    target TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    canonical_value TEXT NOT NULL,
                    label TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    node_json TEXT NOT NULL,
                    UNIQUE(entity_type, canonical_value)
                );
                CREATE TABLE IF NOT EXISTS edges (
                    edge_id TEXT PRIMARY KEY,
                    source_node_id TEXT NOT NULL,
                    target_node_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    edge_json TEXT NOT NULL,
                    UNIQUE(source_node_id, target_node_id, relation),
                    FOREIGN KEY(source_node_id) REFERENCES nodes(node_id),
                    FOREIGN KEY(target_node_id) REFERENCES nodes(node_id)
                );
                CREATE TABLE IF NOT EXISTS timeline_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    node_id TEXT,
                    event_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profile_verifications (
                    verification_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    verification_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identity_clusters (
                    cluster_id TEXT PRIMARY KEY,
                    confidence REAL NOT NULL,
                    cluster_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_tasks (
                    task_id TEXT PRIMARY KEY,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    task_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deep_seeds (
                    seed_id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    seed_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    analysis_id TEXT PRIMARY KEY,
                    generated_at TEXT NOT NULL,
                    analysis_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attachments (
                    attachment_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    attachment_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_nodes_value ON nodes(canonical_value);
                CREATE INDEX IF NOT EXISTS idx_timeline_time ON timeline_events(occurred_at);
                CREATE INDEX IF NOT EXISTS idx_verification_node ON profile_verifications(node_id, verified_at);
                CREATE INDEX IF NOT EXISTS idx_review_status ON review_tasks(status, priority);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO case_meta(case_id, name, record_json) VALUES (?, ?, ?)",
                (
                    self.record.case_id,
                    self.record.name,
                    json.dumps(self.record.model_dump(mode="json"), ensure_ascii=False),
                ),
            )
        with contextlib.suppress(OSError):
            self.db_path.chmod(0o600)

    def scan_directory(self, scan_id: str) -> Path:
        path = self.scans_dir / scan_id
        path.mkdir(parents=True, exist_ok=False, mode=0o700)
        return path

    def save_scan(self, result: ScanResult) -> None:
        payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO scans(
                    scan_id, depth, parent_scan_id, target, target_type, started_at, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.scan_id,
                    result.depth,
                    result.parent_scan_id,
                    result.target,
                    result.target_type.value,
                    result.started_at.isoformat(),
                    payload,
                ),
            )
        self.record.updated_at = datetime.now(UTC)
        self.write_manifest()

    def save_graph(
        self,
        nodes: list[EvidenceNode],
        edges: list[EvidenceEdge],
        events: list[TimelineEvent],
    ) -> None:
        with self.connect() as connection:
            for node in nodes:
                existing = connection.execute(
                    "SELECT node_json FROM nodes WHERE entity_type = ? AND canonical_value = ?",
                    (node.entity_type, node.canonical_value),
                ).fetchone()
                if existing:
                    old = EvidenceNode.model_validate_json(existing["node_json"])
                    node.node_id = old.node_id
                    node.first_seen = min(old.first_seen, node.first_seen)
                    node.last_seen = max(old.last_seen, node.last_seen)
                    node.confidence = max(old.confidence, node.confidence)
                    node.sources = sorted(set(old.sources) | set(node.sources))
                    node.evidence_refs = sorted(set(old.evidence_refs) | set(node.evidence_refs))
                    node.attributes = {**old.attributes, **node.attributes}
                    node.attributes["root_target"] = bool(
                        old.attributes.get("root_target") or node.attributes.get("root_target")
                    )
                    node.attributes["pivot_target"] = bool(
                        old.attributes.get("pivot_target") or node.attributes.get("pivot_target")
                    )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO nodes(
                        node_id, entity_type, canonical_value, label, confidence, node_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node.node_id,
                        node.entity_type,
                        node.canonical_value,
                        node.label,
                        node.confidence,
                        json.dumps(node.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
            endpoint_ids = {
                row["node_id"] for row in connection.execute("SELECT node_id FROM nodes").fetchall()
            }
            # Edges already carry stable IDs; only insert those whose endpoints exist.
            for edge in edges:
                if (
                    edge.source_node_id not in endpoint_ids
                    or edge.target_node_id not in endpoint_ids
                ):
                    continue
                connection.execute(
                    """
                    INSERT INTO edges(
                        edge_id, source_node_id, target_node_id, relation, confidence, edge_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_node_id, target_node_id, relation) DO UPDATE SET
                        confidence = MAX(confidence, excluded.confidence),
                        edge_json = excluded.edge_json
                    """,
                    (
                        edge.edge_id,
                        edge.source_node_id,
                        edge.target_node_id,
                        edge.relation,
                        edge.confidence,
                        json.dumps(edge.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
            for event in events:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO timeline_events(
                        event_id, occurred_at, event_type, node_id, event_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.occurred_at.isoformat(),
                        event.event_type,
                        event.node_id,
                        json.dumps(event.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )

    def nodes(self) -> list[EvidenceNode]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT node_json FROM nodes ORDER BY confidence DESC"
            ).fetchall()
        return [EvidenceNode.model_validate_json(row["node_json"]) for row in rows]

    def edges(self) -> list[EvidenceEdge]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT edge_json FROM edges ORDER BY confidence DESC"
            ).fetchall()
        return [EvidenceEdge.model_validate_json(row["edge_json"]) for row in rows]

    def timeline(self) -> list[TimelineEvent]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM timeline_events ORDER BY occurred_at ASC"
            ).fetchall()
        return [TimelineEvent.model_validate_json(row["event_json"]) for row in rows]

    def scans(self) -> list[ScanResult]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT result_json FROM scans ORDER BY started_at ASC"
            ).fetchall()
        return [ScanResult.model_validate_json(row["result_json"]) for row in rows]

    def save_verification(self, verification: ProfileVerification) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO profile_verifications(
                    verification_id, node_id, verified_at, verification_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    verification.verification_id,
                    verification.node_id,
                    verification.verified_at.isoformat(),
                    json.dumps(verification.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def verifications(self) -> list[ProfileVerification]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT verification_json FROM profile_verifications ORDER BY verified_at DESC"
            ).fetchall()
        return [ProfileVerification.model_validate_json(row["verification_json"]) for row in rows]

    def latest_verification(self, node_id: str) -> ProfileVerification | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT verification_json FROM profile_verifications
                WHERE node_id = ? ORDER BY verified_at DESC LIMIT 1
                """,
                (node_id,),
            ).fetchone()
        return ProfileVerification.model_validate_json(row["verification_json"]) if row else None

    def replace_clusters(self, clusters: list[IdentityCluster]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM identity_clusters")
            for cluster in clusters:
                connection.execute(
                    "INSERT INTO identity_clusters(cluster_id, confidence, cluster_json) VALUES (?, ?, ?)",
                    (
                        cluster.cluster_id,
                        cluster.confidence,
                        json.dumps(cluster.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )

    def replace_identity_edges(self, edges: list[EvidenceEdge]) -> None:
        """Replace derived identity-comparison edges without touching source evidence."""
        relations = (
            "likely_same_identity",
            "possibly_same_identity",
            "likely_unrelated",
        )
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM edges WHERE relation IN (?, ?, ?)",
                relations,
            )
        self.save_graph([], edges, [])

    def replace_account_link_edges(self, edges: list[EvidenceEdge]) -> None:
        """Replace derived public-profile-link edges after strict re-evaluation."""

        with self.connect() as connection:
            connection.execute("DELETE FROM edges WHERE relation = ?", ("links_to_account",))
        self.save_graph([], edges, [])

    def delete_nodes(self, node_ids: list[str]) -> None:
        """Delete derived nodes and their dependent records from a case workspace."""

        unique = sorted(set(node_ids))
        if not unique:
            return
        placeholders = ",".join("?" for _ in unique)
        with self.connect() as connection:
            connection.execute(
                f"DELETE FROM edges WHERE source_node_id IN ({placeholders}) OR target_node_id IN ({placeholders})",
                [*unique, *unique],
            )
            connection.execute(
                f"DELETE FROM timeline_events WHERE node_id IN ({placeholders})", unique
            )
            connection.execute(
                f"DELETE FROM profile_verifications WHERE node_id IN ({placeholders})", unique
            )
            connection.execute(f"DELETE FROM nodes WHERE node_id IN ({placeholders})", unique)

    def clusters(self) -> list[IdentityCluster]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT cluster_json FROM identity_clusters ORDER BY confidence DESC"
            ).fetchall()
        return [IdentityCluster.model_validate_json(row["cluster_json"]) for row in rows]

    def replace_review_tasks(self, tasks: list[ReviewTask]) -> None:
        existing = {task.task_id: task for task in self.review_tasks()}
        with self.connect() as connection:
            connection.execute("DELETE FROM review_tasks")
            for task in tasks:
                old = existing.get(task.task_id)
                if old and old.status != ReviewStatus.PENDING:
                    task.status = old.status
                    task.resolved_at = old.resolved_at
                    task.resolution_note = old.resolution_note
                connection.execute(
                    "INSERT INTO review_tasks(task_id, priority, status, task_json) VALUES (?, ?, ?, ?)",
                    (
                        task.task_id,
                        task.priority,
                        task.status.value,
                        json.dumps(task.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )

    def review_tasks(self, status: ReviewStatus | None = None) -> list[ReviewTask]:
        query = "SELECT task_json FROM review_tasks"
        params: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status.value,)
        query += (
            " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, task_id"
        )
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [ReviewTask.model_validate_json(row["task_json"]) for row in rows]

    def resolve_review_task(self, task_id: str, status: ReviewStatus, note: str = "") -> ReviewTask:
        tasks = {task.task_id: task for task in self.review_tasks()}
        matches = [task for key, task in tasks.items() if key == task_id or key.startswith(task_id)]
        if len(matches) != 1:
            raise MIAError("review task not found or ambiguous")
        task = matches[0]
        task.status = status
        task.resolution_note = note
        task.resolved_at = datetime.now(UTC)
        with self.connect() as connection:
            connection.execute(
                "UPDATE review_tasks SET status = ?, task_json = ? WHERE task_id = ?",
                (
                    status.value,
                    json.dumps(task.model_dump(mode="json"), ensure_ascii=False),
                    task.task_id,
                ),
            )
        return task

    def save_deep_seeds(self, seeds: list[object]) -> None:
        with self.connect() as connection:
            for seed in seeds:
                payload = seed.model_dump(mode="json")
                connection.execute(
                    "INSERT OR REPLACE INTO deep_seeds(seed_id, target_type, target, seed_json) VALUES (?, ?, ?, ?)",
                    (
                        seed.seed_id,
                        seed.target_type.value,
                        seed.target,
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )

    def deep_seeds(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT seed_json FROM deep_seeds ORDER BY rowid").fetchall()
        return [json.loads(row["seed_json"]) for row in rows]

    def save_analysis(self, analysis: object) -> Path:
        payload = analysis.model_dump(mode="json")
        analysis_id = (
            "analysis-"
            + hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()[:20]
        )
        path = self.analysis_dir / f"{analysis_id}.json"
        atomic_write_json(path, payload)
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO analysis_runs(analysis_id, generated_at, analysis_json) VALUES (?, ?, ?)",
                (
                    analysis_id,
                    str(payload.get("generated_at", "")),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        return path

    def latest_analysis(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT analysis_json FROM analysis_runs ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["analysis_json"]) if row else None

    def add_attachment(
        self, source: Path, *, kind: str = "evidence", note: str = ""
    ) -> CaseAttachment:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise MIAError(f"attachment is not a file: {source}")
        if kind not in {"evidence", "screenshot"}:
            raise MIAError("attachment kind must be evidence or screenshot")
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        sha256 = digest.hexdigest()
        destination_dir = self.screenshots_dir if kind == "screenshot" else self.evidence_dir
        safe_name = source.name.replace("/", "_").replace("\\", "_")
        destination = destination_dir / safe_name
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != sha256:
            destination = destination_dir / f"{source.stem}-{sha256[:8]}{source.suffix}"
        if not destination.exists():
            shutil.copy2(source, destination)
            with contextlib.suppress(OSError):
                destination.chmod(0o600)
        attachment = CaseAttachment(
            attachment_id=f"attachment-{sha256[:20]}-{kind}",
            case_id=self.record.case_id,
            kind=kind,
            filename=destination.name,
            path=str(destination),
            sha256=sha256,
            size_bytes=destination.stat().st_size,
            note=note,
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO attachments(
                    attachment_id, kind, filename, sha256, added_at, attachment_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment.attachment_id,
                    attachment.kind,
                    attachment.filename,
                    attachment.sha256,
                    attachment.added_at.isoformat(),
                    json.dumps(attachment.model_dump(mode="json"), ensure_ascii=False),
                ),
            )
        self.record.updated_at = datetime.now(UTC)
        self.write_manifest()
        return attachment

    def attachments(self, kind: str | None = None) -> list[CaseAttachment]:
        query = "SELECT attachment_json FROM attachments"
        parameters: tuple[str, ...] = ()
        if kind is not None:
            query += " WHERE kind = ?"
            parameters = (kind,)
        query += " ORDER BY added_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [CaseAttachment.model_validate_json(row["attachment_json"]) for row in rows]

    def append_note(self, text: str) -> None:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        with self.notes_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## {timestamp}\n\n{text.strip()}\n")

    def graph_payload(self) -> dict[str, Any]:
        return {
            "case": self.record.model_dump(mode="json"),
            "nodes": [node.model_dump(mode="json") for node in self.nodes()],
            "edges": [edge.model_dump(mode="json") for edge in self.edges()],
            "timeline": [event.model_dump(mode="json") for event in self.timeline()],
            "scans": [scan.model_dump(mode="json") for scan in self.scans()],
            "notes": self.notes_path.read_text(encoding="utf-8")
            if self.notes_path.exists()
            else "",
            "attachments": [item.model_dump(mode="json") for item in self.attachments()],
            "verifications": [item.model_dump(mode="json") for item in self.verifications()],
            "clusters": [item.model_dump(mode="json") for item in self.clusters()],
            "review_tasks": [item.model_dump(mode="json") for item in self.review_tasks()],
            "deep_seeds": self.deep_seeds(),
            "analysis": self.latest_analysis(),
            "screenshots": [item.filename for item in self.attachments("screenshot")],
        }

    def export_timeline(self) -> dict[str, str]:
        events = self.timeline()
        json_path = self.timeline_dir / "timeline.json"
        csv_path = self.timeline_dir / "timeline.csv"
        markdown_path = self.timeline_dir / "timeline.md"
        atomic_write_json(json_path, [event.model_dump(mode="json") for event in events])

        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(("occurred_at", "event_type", "title", "source", "node_id"))
        for event in events:
            writer.writerow(
                (
                    event.occurred_at.isoformat(),
                    event.event_type,
                    event.title,
                    event.source or "",
                    event.node_id or "",
                )
            )
        atomic_write_text(csv_path, buffer.getvalue())

        lines = [f"# Timeline — {self.record.name}\n"]
        if not events:
            lines.append("No dated evidence has been extracted yet.\n")
        for event in events:
            source = f" — {event.source}" if event.source else ""
            lines.append(
                f"- **{event.occurred_at.isoformat()}** — {event.title}{source} "
                f"(`{event.event_type}`)\n"
            )
        atomic_write_text(markdown_path, "\n".join(lines))
        return {
            "json": str(json_path),
            "csv": str(csv_path),
            "markdown": str(markdown_path),
        }

    def export_payload(self) -> Path:
        self.export_timeline()
        path = self.exports_dir / "case.json"
        atomic_write_json(path, self.graph_payload())
        return path


class CaseManager:
    def __init__(self, cases_dir: Path) -> None:
        self.cases_dir = cases_dir.expanduser()
        self.cases_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def create(
        self,
        name: str,
        *,
        description: str = "",
        tags: list[str] | None = None,
        initial_target: str | None = None,
        initial_target_type: Any = None,
    ) -> CaseWorkspace:
        case_id = f"case-{datetime.now(UTC).strftime('%Y%m%d')}-{secrets.token_hex(4)}"
        slug = safe_slug(name, max_length=64)
        root = self.cases_dir / f"{slug}-{case_id[-8:]}"
        record = CaseRecord(
            case_id=case_id,
            name=name,
            slug=slug,
            root_dir=str(root),
            description=description,
            tags=tags or [],
            initial_target=initial_target,
            initial_target_type=initial_target_type,
        )
        return CaseWorkspace(root, record)

    def _load_manifest(self, path: Path) -> CaseRecord | None:
        manifest = path / "case.yaml"
        if not manifest.exists():
            return None
        try:
            return CaseRecord.model_validate(yaml.safe_load(manifest.read_text(encoding="utf-8")))
        except (OSError, ValueError, yaml.YAMLError):
            return None

    def list(self, include_archived: bool = False) -> list[CaseRecord]:
        records: list[CaseRecord] = []
        for path in self.cases_dir.iterdir():
            if not path.is_dir():
                continue
            record = self._load_manifest(path)
            if record and (include_archived or record.status == CaseStatus.OPEN):
                records.append(record)
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def resolve(self, identifier: str) -> CaseWorkspace:
        matches = [
            record
            for record in self.list(include_archived=True)
            if record.case_id == identifier
            or record.case_id.startswith(identifier)
            or record.slug == identifier
            or record.name.lower() == identifier.lower()
        ]
        if not matches:
            raise CaseNotFoundError(f"case not found: {identifier}")
        if len(matches) > 1:
            raise CaseNotFoundError(f"case identifier is ambiguous: {identifier}")
        record = matches[0]
        return CaseWorkspace(Path(record.root_dir), record)
