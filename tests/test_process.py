import asyncio
import sys
from pathlib import Path

from mia.process import ProcessRunner


def test_process_capture(tmp_path: Path) -> None:
    result = asyncio.run(
        ProcessRunner().run(
            [sys.executable, "-c", "print('hello')"],
            tmp_path / "run",
            timeout_seconds=5,
        )
    )
    assert result.return_code == 0
    assert result.stdout.strip() == "hello"
    assert Path(result.stdout_path).read_text().strip() == "hello"


def test_process_timeout(tmp_path: Path) -> None:
    result = asyncio.run(
        ProcessRunner().run(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            tmp_path / "timeout",
            timeout_seconds=1,
        )
    )
    assert result.timed_out is True
