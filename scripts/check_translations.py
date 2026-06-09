#!/usr/bin/env python3
"""Validate translation files against the source strings.json.

Catches the drift that matters: a string key that was renamed or removed in
strings.json but left behind in a translations/<lang>.json (a "stale" key).
Stale keys are ERRORS — they're dead weight that can mask typos and never
surface to the user. Missing keys (a language that hasn't translated a string
yet) are only WARNINGS — partial translations are normal and expected.

Auto-detects the integration under custom_components/<component>/. Pass an
explicit component dir as the first argument to override.

Exit code: 1 if any stale keys are found, else 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def flatten(obj: object, prefix: str = "") -> set[str]:
    """Flatten a nested dict into the set of dotted leaf-key paths."""
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and v:
                keys |= flatten(v, path)
            else:
                keys.add(path)
    return keys


def find_component(root: Path) -> Path:
    """Locate custom_components/<component>/ — the sole integration package."""
    base = root / "custom_components"
    candidates = (
        [d for d in base.iterdir() if d.is_dir() and (d / "strings.json").exists()]
        if base.is_dir()
        else []
    )
    if len(candidates) != 1:
        names = ", ".join(d.name for d in candidates) or "none"
        sys.exit(
            f"check_translations: expected exactly one component with strings.json, found: {names}"
        )
    return candidates[0]


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    component = (
        Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else find_component(root)
    )

    strings_file = component / "strings.json"
    if not strings_file.exists():
        sys.exit(f"check_translations: no strings.json in {component}")

    reference = flatten(json.loads(strings_file.read_text()))
    trans_dir = component / "translations"
    if not trans_dir.is_dir():
        print("check_translations: no translations/ dir — nothing to check")
        return 0

    had_error = False
    for path in sorted(trans_dir.glob("*.json")):
        keys = flatten(json.loads(path.read_text()))
        stale = sorted(keys - reference)
        missing = sorted(reference - keys)
        if stale:
            had_error = True
            print(f"  ✗ {path.name}: {len(stale)} stale key(s) not in strings.json:")
            for k in stale:
                print(f"      {k}")
        if missing:
            print(f"  ⚠ {path.name}: {len(missing)} untranslated key(s)")

    if had_error:
        print(
            "\ncheck_translations: stale keys found — remove them or fix strings.json"
        )
        return 1
    print("check_translations: no stale keys ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
