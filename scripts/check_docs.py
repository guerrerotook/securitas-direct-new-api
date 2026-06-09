#!/usr/bin/env python3
"""Guard against docs drift on a push.

Policy (matches what the team agreed):
  * STRUCTURAL surface change with no docs touched  -> ERROR (block the push)
  * Routine code edit with no docs touched          -> WARNING (nudge only)
  * Any docs file touched                            -> all good

"Structural" = the integration's public surface changed shape: a *.py module
under the component was added / removed / renamed, or a service was added or
removed in services.yaml. Those are exactly the changes that tend to leave the
README describing something that no longer matches. Editing the body of an
existing module is a routine edit — worth a nudge, not a block.

Usage:  check_docs.py <git-diff-range>      e.g. check_docs.py origin/main..HEAD

Exit code: 1 on a blocking structural drift, else 0.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC_PREFIXES = ("readme", "docs/", "changelog")


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return out.stdout


def component_dir() -> Path | None:
    base = ROOT / "custom_components"
    if not base.is_dir():
        return None
    dirs = [d for d in base.iterdir() if d.is_dir() and (d / "manifest.json").exists()]
    return dirs[0] if len(dirs) == 1 else None


def services_keys(ref: str, path: str) -> set[str]:
    """Top-level service keys in services.yaml at a given git ref ('' = worktree)."""
    try:
        text = git("show", f"{ref}:{path}") if ref else (ROOT / path).read_text()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()
    # services.yaml top-level keys are the service names — read them without a
    # yaml dependency: lines at column 0 that aren't comments and end in ':'.
    keys = set()
    for line in text.splitlines():
        if line and line[0] not in " #\t" and ":" in line:
            keys.add(line.split(":", 1)[0].strip())
    return keys


def main() -> int:
    diff_range = sys.argv[1] if len(sys.argv) > 1 else "origin/main..HEAD"
    comp = component_dir()
    if comp is None:
        return 0
    comp_rel = comp.relative_to(ROOT).as_posix()

    # name-status gives us A/D/R/M per file — we need the verb, not just the path.
    status = git("diff", "--name-status", diff_range).splitlines()
    changed = [line.split("\t") for line in status if line.strip()]

    docs_touched = any(parts[-1].lower().startswith(DOC_PREFIXES) for parts in changed)

    structural: list[str] = []
    edited_py = False
    for parts in changed:
        verb, path = parts[0], parts[-1]
        if not path.startswith(f"{comp_rel}/") or "/translations/" in path:
            continue
        if path.endswith(".py"):
            if verb[0] in ("A", "D", "R"):
                structural.append(f"{verb[0]} {path}")
            else:
                edited_py = True

    svc = f"{comp_rel}/services.yaml"
    if any(p[-1] == svc for p in changed):
        base = diff_range.split("..")[0] or "HEAD"
        added_removed = services_keys(base, svc) ^ services_keys("", svc)
        if added_removed:
            structural.append(f"services.yaml: {', '.join(sorted(added_removed))}")

    if structural and not docs_touched:
        print("  ✗ Structural surface change without a docs update:")
        for s in structural:
            print(f"      {s}")
        print("    Update README.md / docs/ (or `git push --no-verify` if truly N/A).")
        return 1
    if edited_py and not docs_touched:
        print(
            "  ⚠ Component code changed but no docs touched — check the README still matches."
        )
    else:
        print("check_docs: ok ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
