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
import os
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
# pytest-cov before 7.0 starts coverage in every child Python it can see
# (the COV_CORE_* variables). A child run from a scratch folder has no branch
# coverage config, and its statement-only data then breaks the parent's combine.
_CHILD_ENV = {k: v for k, v in os.environ.items() if not k.startswith("COV_CORE_")}

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
    expected: dict[str, str] = {}
    for path in sorted(www.glob("*.js")):
        bad = []
        for name, query in _IMPORT_RE.findall(path.read_text()):
            if name not in expected:
                digest = hashlib.sha256((www / name).read_bytes()).hexdigest()[:8]
                expected[name] = f"?v={digest}-{version}"
            if query != expected[name]:
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
        f"card JS relative imports out of date: {offenders}. Run: {_STAMP_COMMAND}"
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


def _run_script_on(tmp_path: Path, files: dict[str, str], *args: str):
    """Run a copy of the script against a scratch component holding ``files``."""
    www = tmp_path / "custom_components" / "securitas" / "www"
    www.mkdir(parents=True)
    shutil.copy(_SECURITAS / "manifest.json", www.parent / "manifest.json")
    for name, text in files.items():
        (www / name).write_text(text)
    (tmp_path / "scripts").mkdir()
    shutil.copy(_SCRIPT, tmp_path / "scripts" / _SCRIPT.name)
    return subprocess.run(
        [sys.executable, f"scripts/{_SCRIPT.name}", *args],
        cwd=tmp_path,
        env=_CHILD_ENV,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("files", "message"),
    [
        (
            {"a.js": 'import "./b.js?v=1";\n', "b.js": 'import "./a.js?v=1";\n'},
            "stamp_card_imports: import cycle: a.js -> b.js -> a.js",
        ),
        (
            {"a.js": 'import "./gone.js?v=1";\n'},
            "stamp_card_imports: a.js imports missing file(s): gone.js",
        ),
    ],
)
def test_script_reports_a_bad_import_graph_in_one_line(
    tmp_path: Path, files: dict[str, str], message: str
) -> None:
    result = _run_script_on(tmp_path, files, "--check")
    assert result.returncode == 1
    assert result.stderr == f"{message}\n"
    assert result.stdout == ""


def test_script_says_ok_when_nothing_is_stale(tmp_path: Path) -> None:
    result = _run_script_on(tmp_path, {"a.js": "export const a = 1;\n"}, "--check")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "stamp_card_imports: ok ✓\n"


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
        env=_CHILD_ENV,
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
