from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from mia.exceptions import ScanNotFoundError
from mia.models import ScanResult


class ScanDatabase:
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
                CREATE TABLE IF NOT EXISTS scans (
                    scan_id TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_seconds REAL,
                    output_dir TEXT NOT NULL,
                    finding_count INTEGER NOT NULL,
                    successful_plugins INTEGER NOT NULL,
                    failed_plugins INTEGER NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scans_started_at ON scans(started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_scans_target ON scans(target);

                CREATE TABLE IF NOT EXISTS plugin_runs (
                    scan_id TEXT NOT NULL,
                    plugin_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    return_code INTEGER,
                    finding_count INTEGER NOT NULL,
                    error TEXT,
                    PRIMARY KEY (scan_id, plugin_id),
                    FOREIGN KEY (scan_id) REFERENCES scans(scan_id) ON DELETE CASCADE
                );
                """
            )

    def save(self, result: ScanResult) -> None:
        payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO scans (
                    scan_id, target, target_type, profile, started_at, finished_at,
                    duration_seconds, output_dir, finding_count, successful_plugins,
                    failed_plugins, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.scan_id,
                    result.target,
                    result.target_type.value,
                    result.profile.value,
                    result.started_at.isoformat(),
                    result.finished_at.isoformat() if result.finished_at else None,
                    result.duration_seconds,
                    result.output_dir,
                    len(result.findings),
                    result.successful_plugins,
                    result.failed_plugins,
                    payload,
                ),
            )
            connection.execute("DELETE FROM plugin_runs WHERE scan_id = ?", (result.scan_id,))
            connection.executemany(
                """
                INSERT INTO plugin_runs (
                    scan_id, plugin_id, status, duration_seconds, return_code,
                    finding_count, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        result.scan_id,
                        run.plugin_id,
                        run.status.value,
                        run.duration_seconds,
                        run.return_code,
                        len(run.findings),
                        run.error,
                    )
                    for run in result.plugin_runs
                ],
            )

    def resolve_scan_id(self, scan_id_or_prefix: str) -> str:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT scan_id FROM scans WHERE scan_id = ? OR scan_id LIKE ? ORDER BY started_at DESC LIMIT 3",
                (scan_id_or_prefix, f"{scan_id_or_prefix}%"),
            ).fetchall()
        if not rows:
            raise ScanNotFoundError(f"scan not found: {scan_id_or_prefix}")
        exact = [row["scan_id"] for row in rows if row["scan_id"] == scan_id_or_prefix]
        if exact:
            return exact[0]
        if len(rows) > 1:
            raise ScanNotFoundError(f"scan prefix is ambiguous: {scan_id_or_prefix}")
        return rows[0]["scan_id"]

    def load(self, scan_id_or_prefix: str) -> ScanResult:
        scan_id = self.resolve_scan_id(scan_id_or_prefix)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM scans WHERE scan_id = ?", (scan_id,)
            ).fetchone()
        if row is None:
            raise ScanNotFoundError(f"scan not found: {scan_id}")
        return ScanResult.model_validate_json(row["result_json"])

    def history(self, limit: int = 20, target: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT scan_id, target, target_type, profile, started_at, duration_seconds,
                   finding_count, successful_plugins, failed_plugins, output_dir
            FROM scans
        """
        parameters: list[Any] = []
        if target:
            query += " WHERE target LIKE ?"
            parameters.append(f"%{target}%")
        query += " ORDER BY started_at DESC LIMIT ?"
        parameters.append(limit)
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, parameters).fetchall()]

    def compare(self, first_id: str, second_id: str) -> dict[str, Any]:
        first = self.load(first_id)
        second = self.load(second_id)
        first_map = {item.dedup_key: item for item in first.findings}
        second_map = {item.dedup_key: item for item in second.findings}
        added_keys = sorted(second_map.keys() - first_map.keys())
        removed_keys = sorted(first_map.keys() - second_map.keys())
        common = first_map.keys() & second_map.keys()
        changed = []
        for key in sorted(common):
            before = first_map[key]
            after = second_map[key]
            if before.sources != after.sources or before.confidence != after.confidence:
                changed.append(
                    {
                        "dedup_key": key,
                        "title": after.title,
                        "before_sources": before.sources,
                        "after_sources": after.sources,
                        "before_confidence": before.confidence,
                        "after_confidence": after.confidence,
                    }
                )
        return {
            "first_scan": first.scan_id,
            "second_scan": second.scan_id,
            "target_matches": first.target == second.target,
            "added": [second_map[key].model_dump(mode="json") for key in added_keys],
            "removed": [first_map[key].model_dump(mode="json") for key in removed_keys],
            "changed": changed,
            "unchanged_count": len(common) - len(changed),
        }
