"""A failure on `beta` or `dev` does not fail the job, and a failed install warns.

An unreleased Home Assistant must not block a PR, and that includes a GitHub
outage or the install landing on the wrong version. These tests pin how
`tests.yaml` tolerates it. The `minimum` channel has its own install step, so
there the shared step reads "skipped": the later steps have to run on that.
"""

from pathlib import Path

import yaml

_WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "tests.yaml"
_TOLERATED = "matrix.ha-channel == 'beta' || matrix.ha-channel == 'dev'"
_NOT_FAILED = "steps.install.outcome != 'failure'"
_FAILED = "steps.install.outcome == 'failure'"


def _steps() -> list[dict]:
    return yaml.safe_load(_WORKFLOW.read_text())["jobs"]["test"]["steps"]


def _named(name_start: str) -> dict:
    return next(
        step for step in _steps() if step.get("name", "").startswith(name_start)
    )


def test_only_unreleased_channels_tolerate_a_failed_install() -> None:
    install = next(step for step in _steps() if step.get("id") == "install")
    assert "scripts/ci_ha_install.py" in install["run"]
    assert install["continue-on-error"] == "${{ " + _TOLERATED + " }}"


def test_other_fallible_steps_tolerate_failure_on_unreleased_channels() -> None:
    for name in (
        "Install system dependencies",
        "Show Home Assistant version",
        "Run ${{ matrix.suite }} tests",
        "Upload coverage data",
    ):
        assert _named(name)["continue-on-error"] == "${{ " + _TOLERATED + " }}", name


def test_a_failed_install_warns() -> None:
    warnings = [step for step in _steps() if step.get("if") == _FAILED]
    assert len(warnings) == 1
    assert warnings[0]["run"].startswith('echo "::warning::')


def test_later_steps_run_on_minimum_but_not_after_a_failed_install() -> None:
    for name in (
        "Show Home Assistant version",
        "Run ${{ matrix.suite }} tests",
        "Upload coverage data",
    ):
        assert _named(name)["if"] == _NOT_FAILED, name


def test_the_coverage_gate_reads_only_the_stable_channel() -> None:
    """A beta or dev leg that uploaded nothing cannot starve the gate."""
    gate = yaml.safe_load(_WORKFLOW.read_text())["jobs"]["coverage-gate"]["steps"]
    downloads = [
        step["with"]["name"]
        for step in gate
        if "with" in step and "name" in step["with"]
    ]
    assert downloads == ["coverage-stable-unit", "coverage-stable-integration"]
