from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from mia.models import PluginRunResult, PluginRunStatus, ScanProfile, TargetType


class ResultCache:
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
                CREATE TABLE IF NOT EXISTS plugin_cache (
                    cache_key TEXT PRIMARY KEY,
                    plugin_id TEXT NOT NULL,
                    target TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    source_scan_id TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_plugin_cache_created ON plugin_cache(created_at);
                """
            )

    @staticmethod
    def key(
        plugin_id: str,
        target: str,
        target_type: TargetType,
        profile: ScanProfile,
        extra_args: list[str],
    ) -> str:
        material = json.dumps(
            {
                "plugin": plugin_id,
                "target": target.strip(),
                "target_type": target_type.value,
                "profile": profile.value,
                "extra_args": extra_args,
            },
            sort_keys=True,
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def get(
        self, cache_key: str, ttl_seconds: int, reuse_failed: bool = False
    ) -> PluginRunResult | None:
        if ttl_seconds <= 0:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT created_at, source_scan_id, result_json FROM plugin_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        created = datetime.fromisoformat(row["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - created).total_seconds()
        if age > ttl_seconds:
            return None
        result = PluginRunResult.model_validate_json(row["result_json"])
        if not reuse_failed and result.status in {
            PluginRunStatus.FAILED,
            PluginRunStatus.TIMED_OUT,
            PluginRunStatus.UNAVAILABLE,
        }:
            return None
        result.status = PluginRunStatus.CACHED
        result.cached = True
        result.cache_source_scan_id = row["source_scan_id"]
        result.cache_age_seconds = age
        result.warnings = [*result.warnings, f"Reused cached result ({age:.0f}s old)"]
        return result

    def put(
        self,
        cache_key: str,
        source_scan_id: str,
        result: PluginRunResult,
        *,
        target: str,
        target_type: TargetType,
        profile: ScanProfile,
    ) -> None:
        # Persist the original status. It will be changed to CACHED only when read.
        payload = result.model_copy(deep=True)
        payload.cached = False
        payload.cache_source_scan_id = None
        payload.cache_age_seconds = None
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO plugin_cache(
                    cache_key, plugin_id, target, target_type, profile,
                    created_at, source_scan_id, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    result.plugin_id,
                    target,
                    target_type.value,
                    profile.value,
                    datetime.now(UTC).isoformat(),
                    source_scan_id,
                    json.dumps(payload.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def stats(self) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS entries, MIN(created_at) AS oldest, MAX(created_at) AS newest
                FROM plugin_cache
                """
            ).fetchone()
            by_plugin = connection.execute(
                """
                SELECT plugin_id, COUNT(*) AS entries
                FROM plugin_cache
                GROUP BY plugin_id
                ORDER BY entries DESC, plugin_id
                """
            ).fetchall()
        return {
            "path": str(self.path),
            "entries": int(row["entries"]),
            "oldest": row["oldest"],
            "newest": row["newest"],
            "by_plugin": [dict(item) for item in by_plugin],
        }

    def clear(self) -> int:
        with self.connect() as connection:
            count = int(
                connection.execute("SELECT COUNT(*) AS count FROM plugin_cache").fetchone()["count"]
            )
            connection.execute("DELETE FROM plugin_cache")
        return count
