from __future__ import annotations

from datetime import UTC, datetime

from mia.config import AppConfig
from mia.models import (
    Finding,
    FindingStatus,
    PluginContext,
    PluginRunResult,
    PluginRunStatus,
    TargetType,
)
from mia.plugin import BasePlugin
from mia.process import ProcessRunner
from mia.utils import atomic_write_json

HASH_CANDIDATES: dict[int, list[str]] = {
    16: ["MySQL 3.x", "DES (Unix, truncated forms)"],
    32: ["MD5", "NTLM", "MD4"],
    40: ["SHA-1", "RIPEMD-160"],
    56: ["SHA-224"],
    64: ["SHA-256", "BLAKE2s", "SHA3-256"],
    96: ["SHA-384", "SHA3-384"],
    128: ["SHA-512", "BLAKE2b", "SHA3-512"],
}


class HashIdentifierPlugin(BasePlugin):
    plugin_id = "hashid"
    name = "Hash identifier"
    description = "Local candidate identification based on encoding and digest length"
    target_types = frozenset({TargetType.HASH})
    network_required = False

    async def execute(
        self, context: PluginContext, config: AppConfig, runner: ProcessRunner
    ) -> PluginRunResult:
        started = datetime.now(UTC)
        context.raw_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        algorithms = HASH_CANDIDATES.get(len(context.target), ["Unknown hexadecimal digest"])
        raw_path = context.raw_dir / "hash_candidates.json"
        atomic_write_json(
            raw_path,
            {"length": len(context.target), "encoding": "hex", "candidates": algorithms},
        )
        findings = [
            Finding(
                plugin_id=self.plugin_id,
                category="Hash candidates",
                kind="hash_algorithm",
                title=algorithm,
                value=algorithm,
                status=FindingStatus.POSSIBLE,
                source_confidence=0.70 if len(algorithms) > 1 else 0.82,
                attributes={"digest_length": len(context.target), "encoding": "hex"},
                evidence_path=str(raw_path),
            )
            for algorithm in algorithms
        ]
        finished = datetime.now(UTC)
        return PluginRunResult(
            plugin_id=self.plugin_id,
            plugin_name=self.name,
            status=PluginRunStatus.SUCCESS,
            started_at=started,
            finished_at=finished,
            duration_seconds=(finished - started).total_seconds(),
            raw_dir=str(context.raw_dir),
            findings=findings,
            warnings=["Hash length alone cannot uniquely identify an algorithm"],
        )


PLUGIN_CLASS = HashIdentifierPlugin
