from __future__ import annotations

import asyncio
import secrets
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

OperationRunner = Callable[["Operation"], Awaitable[dict[str, Any] | None]]


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class Operation:
    operation_id: str
    kind: str
    title: str
    status: str = "queued"
    progress: float = 0.0
    current: str = "Waiting"
    message: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=300))
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "progress": round(self.progress, 4),
            "current": self.current,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "events": list(self.events),
        }


class OperationManager:
    def __init__(self) -> None:
        self._operations: dict[str, Operation] = {}
        self._lock = asyncio.Lock()

    async def create(self, kind: str, title: str, runner: OperationRunner) -> Operation:
        operation = Operation(
            operation_id=f"op-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}",
            kind=kind,
            title=title,
        )
        async with self._lock:
            self._operations[operation.operation_id] = operation
        operation.task = asyncio.create_task(self._execute(operation, runner))
        return operation

    async def _execute(self, operation: Operation, runner: OperationRunner) -> None:
        operation.status = "running"
        operation.started_at = _now()
        await self.emit(operation, "started", message=operation.title)
        try:
            result = await runner(operation)
            operation.result = result or {}
            operation.progress = 1.0
            operation.status = "completed"
            operation.current = "Complete"
            await self.emit(operation, "completed", message="Operation completed")
        except asyncio.CancelledError:
            operation.status = "cancelled"
            operation.error = "Cancelled by user"
            operation.current = "Cancelled"
            await self.emit(operation, "cancelled", message=operation.error)
        except Exception as exc:  # operation boundary intentionally catches all
            operation.status = "failed"
            operation.error = str(exc)
            operation.current = "Failed"
            await self.emit(operation, "failed", message=str(exc))
        finally:
            operation.finished_at = _now()
            operation.updated_at = operation.finished_at
            await self._broadcast(operation, {"type": "snapshot", "operation": operation.payload()})

    async def emit(
        self,
        operation: Operation,
        event_type: str,
        *,
        message: str = "",
        current: str | None = None,
        progress: float | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if current is not None:
            operation.current = current
        if message:
            operation.message = message
        if progress is not None:
            operation.progress = max(0.0, min(1.0, progress))
        operation.updated_at = _now()
        event = {
            "type": event_type,
            "at": operation.updated_at,
            "message": message,
            "current": operation.current,
            "progress": operation.progress,
            "data": data or {},
        }
        operation.events.append(event)
        await self._broadcast(operation, event)

    async def _broadcast(self, operation: Operation, event: dict[str, Any]) -> None:
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in operation.subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            operation.subscribers.discard(queue)

    def get(self, operation_id: str) -> Operation | None:
        return self._operations.get(operation_id)

    def list(self) -> list[Operation]:
        return sorted(self._operations.values(), key=lambda item: item.created_at, reverse=True)

    async def cancel(self, operation_id: str) -> bool:
        operation = self.get(operation_id)
        if not operation or not operation.task or operation.task.done():
            return False
        operation.task.cancel()
        return True

    def subscribe(self, operation: Operation) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=128)
        operation.subscribers.add(queue)
        return queue

    def unsubscribe(self, operation: Operation, queue: asyncio.Queue[dict[str, Any]]) -> None:
        operation.subscribers.discard(queue)
