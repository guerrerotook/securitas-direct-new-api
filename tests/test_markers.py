"""Meta-test pinning which test files belong in the `integration` bucket.

The `integration` marker is auto-applied by `conftest.pytest_collection_modifyitems`
to tests whose source file imports `homeassistant` or `tests.mock_graphql`, or
that request the `mock_server` fixture.

This file does NOT verify the hook itself fires at collection time (that would
require running a sub-pytest). Instead it verifies the *invariant the hook
depends on*: that every file in `EXPECTED_INTEGRATION_FILES` actually has those
imports, and that no other test file does. If the hook is ever deleted, the CI
integration job will collect 0 tests and fail loudly.
"""

from __future__ import annotations

from pathlib import Path

TESTS_DIR = Path(__file__).parent

EXPECTED_INTEGRATION_FILES = frozenset(
    {
        "test_alarm_panel.py",
        "test_binary_sensor.py",
        "test_camera_platform.py",
        "test_config_flow.py",
        "test_coordinators.py",
        "test_ha_platforms.py",
        "test_hub.py",
        "test_init.py",
        "test_integration.py",
        "test_migrate_unique_ids.py",
        "test_orphan_directory_repair.py",
        "test_services.py",
    }
)

INTEGRATION_MARKERS = ("from homeassistant", "import homeassistant", "mock_graphql")


def _has_integration_imports(path: Path) -> bool:
    source = path.read_text()
    return any(marker in source for marker in INTEGRATION_MARKERS)


def test_expected_integration_files_have_integration_imports() -> None:
    """Every file we expect to be integration actually has the qualifying imports."""
    missing_imports = [
        name
        for name in sorted(EXPECTED_INTEGRATION_FILES)
        if not _has_integration_imports(TESTS_DIR / name)
    ]
    assert not missing_imports, (
        f"Files listed in EXPECTED_INTEGRATION_FILES no longer import "
        f"homeassistant or mock_graphql — remove them from the expected set: "
        f"{missing_imports}"
    )


def test_no_unlisted_test_file_has_integration_imports() -> None:
    """Every test_*.py file with HA or mock_graphql imports is in the expected set."""
    unlisted_with_imports: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name in EXPECTED_INTEGRATION_FILES or path.name == "test_markers.py":
            continue
        if _has_integration_imports(path):
            unlisted_with_imports.append(path.name)
    assert not unlisted_with_imports, (
        f"These files import homeassistant or mock_graphql but are not in "
        f"EXPECTED_INTEGRATION_FILES. Add them to the set so the integration "
        f"marker stays in sync: {unlisted_with_imports}"
    )
