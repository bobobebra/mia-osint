from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mia.models import CaseRecord, CorrelationSuggestion, EvidenceNode


class KnowledgeDatabase:
    """Shared local index used to correlate entities across investigation cases."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
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

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    root_dir TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    canonical_value TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    UNIQUE(entity_type, canonical_value)
                );
                CREATE TABLE IF NOT EXISTS case_entities (
                    case_id TEXT NOT NULL,
                    entity_id INTEGER NOT NULL,
                    node_id TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    node_json TEXT NOT NULL,
                    PRIMARY KEY(case_id, entity_id),
                    FOREIGN KEY(case_id) REFERENCES cases(case_id) ON DELETE CASCADE,
                    FOREIGN KEY(entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_entities_value ON entities(canonical_value);
                CREATE INDEX IF NOT EXISTS idx_case_entities_entity ON case_entities(entity_id);
                """
            )

    def ingest(self, case: CaseRecord, nodes: list[EvidenceNode]) -> None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO cases(case_id, name, root_dir, updated_at, record_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.name,
                    case.root_dir,
                    now,
                    json.dumps(case.model_dump(mode="json"), ensure_ascii=False),
                ),
            )
            for node in nodes:
                connection.execute(
                    """
                    INSERT INTO entities(entity_type, canonical_value, first_seen, last_seen)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(entity_type, canonical_value) DO UPDATE SET
                        last_seen = excluded.last_seen
                    """,
                    (
                        node.entity_type,
                        node.canonical_value,
                        node.first_seen.isoformat(),
                        node.last_seen.isoformat(),
                    ),
                )
                entity_id = connection.execute(
                    "SELECT entity_id FROM entities WHERE entity_type = ? AND canonical_value = ?",
                    (node.entity_type, node.canonical_value),
                ).fetchone()["entity_id"]
                connection.execute(
                    """
                    INSERT OR REPLACE INTO case_entities(
                        case_id, entity_id, node_id, confidence, node_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        case.case_id,
                        entity_id,
                        node.node_id,
                        node.confidence,
                        json.dumps(node.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )

    def search(self, value: str, limit: int = 50) -> list[dict[str, Any]]:
        query = f"%{value.strip().lower()}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.entity_type, e.canonical_value, c.case_id, c.name AS case_name,
                       ce.node_id, ce.confidence, c.root_dir, e.first_seen, e.last_seen
                FROM entities e
                JOIN case_entities ce ON ce.entity_id = e.entity_id
                JOIN cases c ON c.case_id = ce.case_id
                WHERE lower(e.canonical_value) LIKE ?
                ORDER BY e.last_seen DESC, ce.confidence DESC
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def correlations_for_case(self, case_id: str) -> list[CorrelationSuggestion]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.entity_type, e.canonical_value,
                       GROUP_CONCAT(DISTINCT ce.case_id) AS case_ids,
                       GROUP_CONCAT(DISTINCT c.name) AS case_names,
                       COUNT(DISTINCT ce.case_id) AS case_count
                FROM entities e
                JOIN case_entities ce ON ce.entity_id = e.entity_id
                JOIN cases c ON c.case_id = ce.case_id
                WHERE e.entity_id IN (
                    SELECT entity_id FROM case_entities WHERE case_id = ?
                )
                GROUP BY e.entity_id
                HAVING COUNT(DISTINCT ce.case_id) > 1
                ORDER BY case_count DESC, e.entity_type, e.canonical_value
                """,
                (case_id,),
            ).fetchall()
        suggestions = []
        for row in rows:
            ids = str(row["case_ids"]).split(",")
            names = str(row["case_names"]).split(",")
            suggestions.append(
                CorrelationSuggestion(
                    entity_type=row["entity_type"],
                    canonical_value=row["canonical_value"],
                    case_ids=ids,
                    case_names=names,
                    confidence=1.0,
                    reason=f"The exact normalized {row['entity_type']} appears in {row['case_count']} cases.",
                )
            )
        return suggestions

    def case_count(self) -> int:
        with self.connect() as connection:
            return int(
                connection.execute("SELECT COUNT(*) AS count FROM cases").fetchone()["count"]
            )
