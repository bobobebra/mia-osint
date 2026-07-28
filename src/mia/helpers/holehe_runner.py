from __future__ import annotations

import argparse
import json
import sys
from types import SimpleNamespace


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Structured Holehe runner for MIA")
    parser.add_argument("email")
    parser.add_argument("--timeout", type=float, default=12)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import httpx
        import trio
        from holehe import core
    except ImportError as exc:
        print(f"Holehe dependency is unavailable: {exc}", file=sys.stderr)
        return 2

    async def run() -> list[dict[str, object]]:
        modules = core.import_submodules("holehe.modules")
        compatibility_args = SimpleNamespace(nopasswordrecovery=False)
        websites = core.get_functions(modules, compatibility_args)
        output: list[dict[str, object]] = []
        client = httpx.AsyncClient(timeout=args.timeout)
        try:
            async with trio.open_nursery() as nursery:
                for website in websites:
                    nursery.start_soon(core.launch_module, website, args.email, client, output)
        finally:
            await client.aclose()
        return sorted(output, key=lambda item: str(item.get("name", item.get("domain", ""))))

    try:
        results = trio.run(run)
    except Exception as exc:
        print(f"Holehe execution failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
