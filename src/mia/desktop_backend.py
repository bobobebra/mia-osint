"""Frozen MIA Core entry point used by the Windows Tauri desktop shell."""

from __future__ import annotations

import argparse
import asyncio
import socket
from pathlib import Path

import uvicorn

from mia import __version__
from mia.platform_support import activate_managed_bin
from mia.utils import atomic_write_json
from mia.web import create_app


def _available_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


async def _serve(*, mode: str, port: int, handshake: Path, config_path: Path | None) -> None:
    selected_port = port or _available_port()
    application = create_app(config_path, allow_remote=False, ui_variant=mode)
    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=selected_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # desktop shell owns process lifetime
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(300):
            if server.started:
                atomic_write_json(
                    handshake,
                    {
                        "status": "ready",
                        "mode": mode,
                        "url": f"http://127.0.0.1:{selected_port}",
                        "port": selected_port,
                        "version": __version__,
                    },
                )
                break
            if task.done():
                await task
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("MIA Core did not start within 30 seconds")
        await task
    except Exception as exc:
        atomic_write_json(
            handshake,
            {
                "status": "error",
                "mode": mode,
                "version": __version__,
                "error": str(exc),
            },
        )
        raise


def main() -> None:
    activate_managed_bin()
    parser = argparse.ArgumentParser(description="MIA Core desktop sidecar")
    parser.add_argument("--mode", choices=("discover", "workbench"), default="discover")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--handshake", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    args.handshake.parent.mkdir(parents=True, exist_ok=True)
    args.handshake.unlink(missing_ok=True)
    asyncio.run(
        _serve(
            mode=args.mode,
            port=args.port,
            handshake=args.handshake,
            config_path=args.config,
        )
    )


if __name__ == "__main__":
    main()
