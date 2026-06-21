"""Tests for ``scripts/extract_changelog.py``.

The extractor pulls a single version's curated, user-facing section out of
``CHANGES.md`` so ``release.yaml`` can use it as the GitHub release notes
(instead of the auto-generated PR list).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).parent.parent
_SCRIPT = _REPO / "scripts" / "extract_changelog.py"


def _load():
    spec = importlib.util.spec_from_file_location("extract_changelog", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CHANGELOG = """\
# Changelog

Most recent at the top.

## v5.4.0

Intro line for 5.4.0.

### Added

**A user-facing thing ([#1](https://example/1)).**  Details here.

## v5.3.0

Older release.

### Fixed

Something old.
"""


def test_extracts_the_requested_version_section() -> None:
    section = _load().extract_section(_CHANGELOG, "5.4.0")
    assert "Intro line for 5.4.0." in section
    assert "**A user-facing thing" in section
    assert "### Added" in section


def test_excludes_other_version_sections() -> None:
    section = _load().extract_section(_CHANGELOG, "5.4.0")
    assert "Older release." not in section
    assert "v5.3.0" not in section


def test_strips_prerelease_suffix_to_find_base_section() -> None:
    section = _load().extract_section(_CHANGELOG, "5.4.0-rc.1")
    assert "Intro line for 5.4.0." in section


def test_section_has_no_leading_or_trailing_blank_lines() -> None:
    section = _load().extract_section(_CHANGELOG, "5.4.0")
    assert section == section.strip("\n")
    assert section.strip()


def test_missing_version_raises() -> None:
    with pytest.raises(ValueError):
        _load().extract_section(_CHANGELOG, "9.9.9")


def test_exact_match_does_not_confuse_prefix_versions() -> None:
    changelog = "## v5.4.10\n\nten.\n\n## v5.4.1\n\none.\n"
    mod = _load()
    assert "one." in mod.extract_section(changelog, "5.4.1")
    assert "ten" not in mod.extract_section(changelog, "5.4.1")
    assert "ten." in mod.extract_section(changelog, "5.4.10")


def test_cli_prints_section_and_returns_zero(tmp_path: Path, capsys) -> None:
    mod = _load()
    changelog = tmp_path / "CHANGES.md"
    changelog.write_text(_CHANGELOG, encoding="utf-8")
    rc = mod.main(["5.4.0", "--changelog", str(changelog)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Intro line for 5.4.0." in out
    assert "Older release." not in out


def test_cli_returns_nonzero_on_missing_section(tmp_path: Path, capsys) -> None:
    mod = _load()
    changelog = tmp_path / "CHANGES.md"
    changelog.write_text(_CHANGELOG, encoding="utf-8")
    rc = mod.main(["9.9.9", "--changelog", str(changelog)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "9.9.9" in err


def test_release_workflow_builds_notes_from_changelog() -> None:
    workflow = (_REPO / ".github" / "workflows" / "release.yaml").read_text(
        encoding="utf-8"
    )
    assert "extract_changelog.py" in workflow
    assert "--notes-file" in workflow
    # The whole point: stop using the auto-generated PR-list notes.
    assert "--generate-notes" not in workflow
