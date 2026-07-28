from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime

from mia.config import AppConfig
from mia.models import (
    Finding,
    PluginContext,
    PluginRunResult,
    PluginRunStatus,
    TargetType,
)
from mia.plugin import BasePlugin
from mia.process import ProcessRunner
from mia.utils import atomic_write_json


class DNSPlugin(BasePlugin):
    plugin_id = "dns"
    name = "DNS resolver"
    description = "Standard-library forward and reverse DNS resolution"
    target_types = frozenset({TargetType.DOMAIN, TargetType.IP})
    homepage = None

    @staticmethod
    def _lookup(target: str, target_type: TargetType) -> dict[str, object]:
        result: dict[str, object] = {"target": target, "addresses": [], "reverse": []}
        if target_type == TargetType.DOMAIN:
            infos = socket.getaddrinfo(target, None, proto=socket.IPPROTO_TCP)
            result["addresses"] = sorted({info[4][0] for info in infos})
        else:
            try:
                hostname, aliases, addresses = socket.gethostbyaddr(target)
                result["reverse"] = [hostname, *aliases]
                result["addresses"] = addresses
            except socket.herror:
                result["reverse"] = []
        return result

    async def execute(
        self, context: PluginContext, config: AppConfig, runner: ProcessRunner
    ) -> PluginRunResult:
        started = datetime.now(UTC)
        context.raw_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(self._lookup, context.target, context.target_type),
                timeout=context.timeout_seconds,
            )
            raw_path = context.raw_dir / "dns.json"
            atomic_write_json(raw_path, data)
            findings: list[Finding] = []
            for address in data.get("addresses", []):
                findings.append(
                    Finding(
                        plugin_id=self.plugin_id,
                        category="DNS",
                        kind="dns",
                        title="Resolved address",
                        value=str(address),
                        source_confidence=0.94,
                        evidence_path=str(raw_path),
                    )
                )
            for hostname in data.get("reverse", []):
                findings.append(
                    Finding(
                        plugin_id=self.plugin_id,
                        category="DNS",
                        kind="domain",
                        title="Reverse DNS name",
                        value=str(hostname),
                        source_confidence=0.90,
                        evidence_path=str(raw_path),
                    )
                )
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
            )
        except TimeoutError:
            finished = datetime.now(UTC)
            return PluginRunResult(
                plugin_id=self.plugin_id,
                plugin_name=self.name,
                status=PluginRunStatus.TIMED_OUT,
                started_at=started,
                finished_at=finished,
                duration_seconds=(finished - started).total_seconds(),
                timed_out=True,
                raw_dir=str(context.raw_dir),
                error="DNS lookup timed out",
            )
        except (socket.gaierror, OSError) as exc:
            finished = datetime.now(UTC)
            atomic_write_json(context.raw_dir / "dns_error.json", {"error": str(exc)})
            return PluginRunResult(
                plugin_id=self.plugin_id,
                plugin_name=self.name,
                status=PluginRunStatus.FAILED,
                started_at=started,
                finished_at=finished,
                duration_seconds=(finished - started).total_seconds(),
                raw_dir=str(context.raw_dir),
                error=str(exc),
            )


PLUGIN_CLASS = DNSPlugin
