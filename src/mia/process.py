from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mia.models import ProcessResult
from mia.platform_support import (
    is_windows,
    popen_platform_kwargs,
    prepare_subprocess_command,
    prepend_managed_bin,
    subprocess_creationflags,
    subprocess_startupinfo,
)
from mia.utils import atomic_write_json


@dataclass(slots=True)
class _CapturedStream:
    text: str
    truncated: bool


class ProcessRunner:
    """Run external tools without a shell and preserve bounded raw output."""

    def __init__(self, max_capture_bytes: int = 50 * 1024 * 1024) -> None:
        self.max_capture_bytes = max_capture_bytes

    async def _capture(
        self,
        stream: asyncio.StreamReader | None,
        path: Path,
    ) -> _CapturedStream:
        if stream is None:
            path.write_bytes(b"")
            return _CapturedStream("", False)

        captured = bytearray()
        written = 0
        truncated = False
        with path.open("wb") as handle:
            while True:
                chunk = await stream.read(64 * 1024)
                if not chunk:
                    break
                remaining = self.max_capture_bytes - written
                if remaining > 0:
                    kept = chunk[:remaining]
                    handle.write(kept)
                    captured.extend(kept)
                    written += len(kept)
                if len(chunk) > max(remaining, 0):
                    truncated = True
        return _CapturedStream(captured.decode("utf-8", errors="replace"), truncated)

    async def run(
        self,
        command: list[str],
        cwd: Path,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
        stdin_data: str | bytes | None = None,
    ) -> ProcessResult:
        if not command or not command[0]:
            raise ValueError("command cannot be empty")
        cwd.mkdir(parents=True, exist_ok=True)
        stdout_path = cwd / "stdout.txt"
        stderr_path = cwd / "stderr.txt"
        started = datetime.now(UTC)
        process_env = prepend_managed_bin()
        process_env.update({"NO_COLOR": "1", "TERM": "dumb", "PYTHONUNBUFFERED": "1"})
        if env:
            process_env.update(env)

        atomic_write_json(
            cwd / "command.json",
            {
                "command": command,
                "cwd": str(cwd),
                "started_at": started.isoformat(),
                "timeout_seconds": timeout_seconds,
            },
        )

        kwargs: dict[str, object] = popen_platform_kwargs(hidden=True)
        execution_command = prepare_subprocess_command(command)

        process = await asyncio.create_subprocess_exec(
            *execution_command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
            env=process_env,
            **kwargs,
        )
        if stdin_data is not None and process.stdin is not None:
            payload = stdin_data.encode("utf-8") if isinstance(stdin_data, str) else stdin_data
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
        stdout_task = asyncio.create_task(self._capture(process.stdout, stdout_path))
        stderr_task = asyncio.create_task(self._capture(process.stderr, stderr_path))
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
        except TimeoutError:
            timed_out = True
            if is_windows():
                taskkill = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    creationflags=subprocess_creationflags(hidden=True, new_process_group=False),
                    startupinfo=subprocess_startupinfo(hidden=True),
                )
                await taskkill.wait()
            else:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                if is_windows():
                    process.kill()
                else:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                await process.wait()

        stdout_capture, stderr_capture = await asyncio.gather(stdout_task, stderr_task)
        finished = datetime.now(UTC)
        result = ProcessResult(
            command=command,
            return_code=process.returncode,
            started_at=started,
            finished_at=finished,
            duration_seconds=(finished - started).total_seconds(),
            timed_out=timed_out,
            stdout=stdout_capture.text,
            stderr=stderr_capture.text,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            output_truncated=stdout_capture.truncated or stderr_capture.truncated,
        )
        atomic_write_json(cwd / "process.json", result.model_dump(mode="json"))
        return result
