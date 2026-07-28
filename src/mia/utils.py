from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def safe_slug(value: str, max_length: int = 48) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", normalized)
    normalized = re.sub(r"[-_.]{2,}", "-", normalized).strip("-._")
    if not normalized:
        normalized = "target"
    suffix = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:8]
    visible = normalized[: max(8, max_length - 9)]
    return f"{visible}-{suffix}"


def new_scan_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(3)}"


def create_scan_directory(output_root: Path, target: str, scan_id: str) -> Path:
    target_root = output_root / safe_slug(target)
    scan_dir = target_root / scan_id
    scan_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        target_root.chmod(0o700)
        scan_dir.chmod(0o700)
    except OSError:
        pass
    return scan_dir


def update_latest_symlink(scan_dir: Path) -> None:
    latest = scan_dir.parent / "latest"
    temp = scan_dir.parent / f".latest-{os.getpid()}"
    try:
        temp.unlink(missing_ok=True)
        temp.symlink_to(scan_dir.name, target_is_directory=True)
        temp.replace(latest)
    except OSError:
        temp.unlink(missing_ok=True)


def atomic_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_text(content, encoding="utf-8")
    with contextlib.suppress(OSError):
        temp.chmod(mode)
    temp.replace(path)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def render_command(command: list[str]) -> str:
    return shlex.join(command)


def strip_ansi(value: str) -> str:
    ansi = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi.sub("", value)
