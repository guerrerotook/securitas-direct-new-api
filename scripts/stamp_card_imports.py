#!/usr/bin/env python3
"""Stamp the Lovelace card modules' relative imports with a content hash.

The card files under custom_components/securitas/www/ are served with a long
browser cache lifetime, so every URL one module imports must change whenever
the imported file changes. This script rewrites each relative import
(``from "./x.js?v=…"``, ``import "./x.js?v=…"`` and ``import("./x.js?v=…")``)
to ``?v=<first 8 hex of sha256(x.js)>-<manifest version>``.

A file's bytes include its own import stamps, so files are stamped
dependencies first: a change deep in the import chain changes the stamp of
every module above it. An import cycle is an error.

Re-run this script after editing any card module. The entry points' own URLs
are computed when const.py is imported, so Home Assistant must be restarted
to serve the new ones.

Exit code: 1 when an import names a missing file or forms a cycle, or, with
--check, when any import is out of date; else 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "securitas"

IMPORT_RE = re.compile(
    r'(?P<head>\b(?:from\s+|import\s*\(?\s*)"\./(?P<name>[A-Za-z0-9._-]+\.js))'
    r'(?P<query>[^"]*)"'
)


def _hash8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]


def _restamp(text: str, stamps: dict[str, str]) -> str:
    return IMPORT_RE.sub(
        lambda m: f'{m["head"]}?v={stamps[m["name"]]}"',
        text,
    )


def _plan(
    www_dir: Path, version: str
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return (stamp per file, stamped text per file, current text per file)."""
    sources = {p.name: p.read_bytes().decode("utf-8") for p in www_dir.glob("*.js")}
    deps: dict[str, list[str]] = {}
    for name, text in sources.items():
        deps[name] = [m["name"] for m in IMPORT_RE.finditer(text)]
        missing = [d for d in deps[name] if d not in sources]
        if missing:
            raise ValueError(f"{name} imports missing file(s): {', '.join(missing)}")

    stamps: dict[str, str] = {}
    stamped: dict[str, str] = {}
    visiting: list[str] = []

    def visit(name: str) -> None:
        if name in stamps:
            return
        if name in visiting:
            chain = [*visiting[visiting.index(name) :], name]
            raise ValueError(f"import cycle: {' -> '.join(chain)}")
        visiting.append(name)
        for dep in deps[name]:
            visit(dep)
        visiting.pop()
        stamped[name] = _restamp(sources[name], stamps)
        stamps[name] = f"{_hash8(stamped[name].encode('utf-8'))}-{version}"

    for name in sorted(sources):
        visit(name)
    return stamps, stamped, sources


def compute_stamps(www_dir: Path, version: str) -> dict[str, str]:
    """Map each card module's file name to the ``<hash8>-<version>`` its importers use."""
    return _plan(www_dir, version)[0]


def stamp(www_dir: Path, version: str, check: bool = False) -> list[str]:
    """Stamp every relative import; with check=True only report.

    Returns one line per import that was (or, with check, would be) changed.
    """
    stamps, stamped, sources = _plan(www_dir, version)
    changes: list[str] = []
    for name in sorted(stamped):
        current = sources[name]
        if stamped[name] == current:
            continue
        changes.extend(
            f"{name}: ./{m['name']}{m['query']} -> ?v={stamps[m['name']]}"
            for m in IMPORT_RE.finditer(current)
            if m["query"] != f"?v={stamps[m['name']]}"
        )
        if not check:
            (www_dir / name).write_bytes(stamped[name].encode("utf-8"))
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report out-of-date imports without changing any file",
    )
    args = parser.parse_args()

    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    try:
        changes = stamp(COMPONENT / "www", manifest["version"], check=args.check)
    except ValueError as err:
        sys.exit(f"stamp_card_imports: {err}")
    if args.check and changes:
        print("Card module imports are out of date:")
        for line in changes:
            print(f"  {line}")
        print("Fix with: python3 scripts/stamp_card_imports.py")
        return 1
    for line in changes:
        print(line)
    if changes:
        print(f"stamp_card_imports: restamped {len(changes)} import(s) ✓")
    else:
        print("stamp_card_imports: ok ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
