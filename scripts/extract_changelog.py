#!/usr/bin/env python3
"""Extract one version's section from ``CHANGES.md`` for GitHub release notes.

``release.yaml`` runs this so a release's notes are the curated, user-facing
changelog entry rather than the auto-generated PR list. A pre-release/build
suffix is stripped before lookup, so ``5.4.0-rc.1`` resolves to the ``## v5.4.0``
section. Exits non-zero if no matching section exists, which fails the release
before a tag is pushed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def extract_section(changelog: str, version: str) -> str:
    """Return the body of the ``## v<base>`` section, where ``base`` is
    ``version`` with any ``-prerelease``/``+build`` suffix removed."""
    base = version.split("-", 1)[0].split("+", 1)[0]
    heading = f"## v{base}"
    lines = changelog.splitlines()

    start = next((i for i, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        raise ValueError(
            f"No '{heading}' section found in changelog for version {version!r}"
        )

    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
        len(lines),
    )
    section = "\n".join(lines[start + 1 : end]).strip("\n")
    if not section.strip():
        raise ValueError(f"'{heading}' section is empty in changelog")
    return section


def main(argv: list[str] | None = None) -> int:
    """Print the changelog section for the given version; return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Version to extract, e.g. 5.4.0 or 5.4.0-rc.1")
    parser.add_argument(
        "--changelog", type=Path, default=Path("CHANGES.md"), help="Path to CHANGES.md"
    )
    args = parser.parse_args(argv)

    try:
        section = extract_section(
            args.changelog.read_text(encoding="utf-8"), args.version
        )
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
