from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mia.process import ProcessRunner


@pytest.mark.skipif(sys.platform != "win32", reason="Windows subprocess behavior")
@pytest.mark.asyncio
async def test_cmd_wrapper_preserves_selector_arguments(tmp_path: Path) -> None:
    """Managed .cmd shims must not reinterpret common selector characters."""

    dumper = tmp_path / "dump args.py"
    dumper.write_text(
        "import json, sys; print(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "managed wrapper.cmd"
    wrapper.write_text(
        f'@echo off\r\n"{sys.executable}" "{dumper}" %*\r\n',
        encoding="utf-8",
    )
    arguments = ["hello user", "a&b", "%PATH%", "person+tag@example.com"]

    result = await ProcessRunner().run(
        [str(wrapper), *arguments],
        tmp_path / "run",
        timeout_seconds=20,
    )

    assert result.return_code == 0, result.stderr
    assert json.loads(result.stdout) == arguments
