#!/usr/bin/env python3
"""Create a modern-Python-compatible requirements file for SpiderFoot v4.0.

SpiderFoot v4.0 pins PyYAML below 6. PyYAML 5.4.1 predates Python 3.10 wheels
and commonly fails to build with current packaging toolchains. SpiderFoot's
current official requirements use PyYAML 6, so MIA applies that single upstream-
aligned compatibility substitution while preserving every other v4.0 pin.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def prepare(source: Path, destination: Path) -> None:
    lines = source.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("pyyaml"):
            output.append("pyyaml>=6.0,<7")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append("pyyaml>=6.0,<7")
    destination.write_text("\n".join(output) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
