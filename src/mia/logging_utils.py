from __future__ import annotations

import logging
from pathlib import Path

from rich.logging import RichHandler


def configure_logging(log_dir: Path, verbose: bool = False) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger("mia")
    logger.setLevel(level)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = False

    rich_handler = RichHandler(
        level=level,
        show_time=False,
        show_path=verbose,
        rich_tracebacks=verbose,
        markup=True,
    )
    rich_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(rich_handler)

    file_handler = logging.FileHandler(log_dir / "mia.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(file_handler)
    return logger
