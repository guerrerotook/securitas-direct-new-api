"""Guard: card modules' relative imports carry the imported file's content stamp.

``/verisure-owa-panel`` is served with ``cache_headers=True`` (long max-age), so
each relative import between card modules must be stamped
``?v=<sha256(imported file)[:8]>-<manifest version>``; otherwise a changed
module stays stale in the browser. ``scripts/stamp_card_imports.py`` writes the
stamps.

The JS copy of the first check (``tests-js/integration/card-cache-busting.test.js``)
runs only in the path-filtered ``js-tests.yml`` workflow, which does not fire on
a manifest-only version bump; this file runs in the unfiltered ``tests.yaml``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

_ROOT = Path(__file__).parent.parent
_SECURITAS = _ROOT / "custom_components" / "securitas"
_WWW = _SECURITAS / "www"
_SCRIPT = _ROOT / "scripts" / "stamp_card_imports.py"
_RELEASE_WORKFLOW = _ROOT / ".github" / "workflows" / "release.yaml"
_STAMP_COMMAND = "python3 scripts/stamp_card_imports.py"

_IMPORT_RE = re.compile(
    r'\b(?:from\s+|import\s*\(?\s*)"\./([A-Za-z0-9._-]+\.js)([^"]*)"'
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stamp_card_imports", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest_version(component: Path = _SECURITAS) -> str:
    return json.loads((component / "manifest.json").read_text())["version"]


def _stale_imports(www: Path, version: str) -> dict[str, list[str]]:
    """Imports whose query is not ?v=<hash8 of the file on disk>-<version>."""
    offenders: dict[str, list[str]] = {}
    for path in sorted(www.glob("*.js")):
        bad = []
        for name, query in _IMPORT_RE.findall(path.read_text()):
            digest = hashlib.sha256((www / name).read_bytes()).hexdigest()[:8]
            if query != f"?v={digest}-{version}":
                bad.append(f"./{name}{query}")
        if bad:
            offenders[path.name] = bad
    return offenders


def _queries_of(www: Path, target: str) -> dict[str, set[str]]:
    """For each file importing ``target``, the set of queries it uses."""
    found: dict[str, set[str]] = {}
    for path in sorted(www.glob("*.js")):
        for name, query in _IMPORT_RE.findall(path.read_text()):
            if name == target:
                found.setdefault(path.name, set()).add(query)
    return found


def test_card_imports_carry_content_stamps() -> None:
    offenders = _stale_imports(_WWW, _manifest_version())
    assert not offenders, (
        f"card JS relative imports out of date: {offenders}. "
        "Run: python scripts/stamp_card_imports.py"
    )


def test_checker_agrees_the_tree_is_stamped() -> None:
    script = _load_script()
    assert script.stamp(_WWW, _manifest_version(), check=True) == []


def test_lazy_badge_editor_import_is_stamped() -> None:
    chip = (_WWW / "verisure-owa-alarm-chip.js").read_text()
    assert 'import("./verisure-owa-alarm-badge-editor.js?v=' in chip


def test_a_changed_module_changes_every_url_up_its_import_chain(
    tmp_path: Path,
) -> None:
    script = _load_script()
    www = tmp_path / "www"
    shutil.copytree(_WWW, www)
    version = _manifest_version()
    script.stamp(www, version)
    utils_before = _queries_of(www, "verisure-owa-card-utils.js")
    shared_before = _queries_of(www, "verisure-owa-alarm-shared.js")
    chip_before = _queries_of(www, "verisure-owa-alarm-chip.js")

    utils = www / "verisure-owa-card-utils.js"
    utils.write_bytes(utils.read_bytes() + b"\n")
    assert script.stamp(www, version, check=True), "checker missed the edit"
    script.stamp(www, version)

    utils_after = _queries_of(www, "verisure-owa-card-utils.js")
    shared_after = _queries_of(www, "verisure-owa-alarm-shared.js")
    chip_after = _queries_of(www, "verisure-owa-alarm-chip.js")
    assert "verisure-owa-alarm-shared.js" in utils_before
    for importer, queries in utils_before.items():
        assert queries.isdisjoint(utils_after[importer]), importer
    assert {"verisure-owa-alarm-card.js", "verisure-owa-alarm-chip.js"} <= set(
        shared_before
    )
    for importer, queries in shared_before.items():
        assert queries.isdisjoint(shared_after[importer]), importer
    for importer, queries in chip_before.items():
        assert queries.isdisjoint(chip_after[importer]), importer
    assert script.stamp(www, version, check=True) == []
    assert _stale_imports(www, version) == {}


def test_an_import_cycle_is_refused(tmp_path: Path) -> None:
    script = _load_script()
    (tmp_path / "a.js").write_text('import "./b.js?v=1";\n')
    (tmp_path / "b.js").write_text('import "./a.js?v=1";\n')
    with pytest.raises(ValueError, match="cycle"):
        script.compute_stamps(tmp_path, "1.0.0")


def _release_step_script(name: str) -> str:
    workflow = yaml.safe_load(_RELEASE_WORKFLOW.read_text())
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if step.get("name") == name:
                return step["run"]
    raise AssertionError(f"no {name!r} step in {_RELEASE_WORKFLOW}")


def test_release_bump_step_leaves_stamps_the_tests_accept(tmp_path: Path) -> None:
    """Run the release workflow's own bump step on a copy of the repo."""
    component = tmp_path / "custom_components" / "securitas"
    component.mkdir(parents=True)
    shutil.copy(_SECURITAS / "manifest.json", component / "manifest.json")
    shutil.copytree(_WWW, component / "www")
    (tmp_path / "scripts").mkdir()
    shutil.copy(_SCRIPT, tmp_path / "scripts" / _SCRIPT.name)
    git = [
        "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "-c",
        "core.autocrlf=false",
    ]
    subprocess.run([*git, "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run([*git, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-qm", "base"], cwd=tmp_path, check=True)

    bump = _release_step_script("Bump manifest versions")
    assert _STAMP_COMMAND in bump
    new_version = "99.1.0-beta.2"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", bump],
        cwd=tmp_path,
        env={
            "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
            "VERSION": new_version,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    assert _manifest_version(component) == new_version
    assert _stale_imports(component / "www", new_version) == {}
    check = subprocess.run(
        [sys.executable, "scripts/stamp_card_imports.py", "--check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr


def test_release_roll_forward_step_restamps_after_the_manifest_write() -> None:
    roll = _release_step_script(
        "Roll branch forward to the next minor (final releases only)"
    )
    assert "sed " not in roll
    manifest_write = roll.index("manifest.json")
    assert roll.index(_STAMP_COMMAND) > manifest_write
    assert roll.index(_STAMP_COMMAND) < roll.index("git add")
