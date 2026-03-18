# Code / Doc / Test Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Write missing tests for identified coverage gaps, merge `constants.py` into `const.py`, then update `architecture.md` to reflect the final state.

**Architecture:** Tests first (highest value), then the trivial constants refactor, then a single doc pass once everything is settled. Each task is independently committable.

**Tech Stack:** Python/pytest, pytest-homeassistant-custom-component, unittest.mock

---

## Task 1: Camera lazy-fetch tests

Two test cases are missing from `tests/test_camera_platform.py`. The `SecuritasCamera` class has an `_initial_fetch_done` flag — `async_camera_image()` calls `fetch_latest_thumbnail` on the **first** call only. The existing tests exercise this path but never assert the fetch happened or that it is skipped on the second call.

**Files:**
- Modify: `tests/test_camera_platform.py`

**Step 1: Write the failing tests**

Add inside `class TestSecuritasCamera` (after the existing `test_camera_image_returns_placeholder_when_empty` test):

```python
@pytest.mark.asyncio
async def test_camera_image_calls_fetch_on_first_call(
    self, mock_hub, installation, camera_device
):
    from custom_components.securitas.camera import SecuritasCamera

    mock_hub.get_camera_image.return_value = b"\xff\xd8"
    cam = SecuritasCamera(mock_hub, installation, camera_device)
    assert cam._initial_fetch_done is False

    await cam.async_camera_image()

    mock_hub.fetch_latest_thumbnail.assert_awaited_once_with(installation, camera_device)
    assert cam._initial_fetch_done is True

@pytest.mark.asyncio
async def test_camera_image_skips_fetch_on_subsequent_calls(
    self, mock_hub, installation, camera_device
):
    from custom_components.securitas.camera import SecuritasCamera

    mock_hub.get_camera_image.return_value = b"\xff\xd8"
    cam = SecuritasCamera(mock_hub, installation, camera_device)

    # First call — triggers the lazy fetch
    await cam.async_camera_image()
    assert mock_hub.fetch_latest_thumbnail.await_count == 1

    # Second call — must NOT trigger fetch again
    await cam.async_camera_image()
    assert mock_hub.fetch_latest_thumbnail.await_count == 1
```

**Step 2: Run to verify they fail**

```bash
cd /workspaces/securitas-direct-new-api/.worktrees/rewrite
python -m pytest tests/test_camera_platform.py::TestSecuritasCamera::test_camera_image_calls_fetch_on_first_call tests/test_camera_platform.py::TestSecuritasCamera::test_camera_image_skips_fetch_on_subsequent_calls -v
```

Expected: FAIL — `AssertionError` because the existing tests don't assert on `fetch_latest_thumbnail` calls.

**Step 3: Run to verify they pass (no production code change needed)**

The production code already works correctly — these tests just document and verify existing behaviour. They should pass immediately. If they fail, re-read `camera.py:62-75` to check the `_initial_fetch_done` logic.

```bash
python -m pytest tests/test_camera_platform.py -v
```

Expected: All PASS.

**Step 4: Commit**

```bash
git add tests/test_camera_platform.py
git commit -m "test(camera): add lazy-fetch assertion tests for async_camera_image"
```

---

## Task 2: Lock Danalock lazy-fetch second-call test

`TestSecuritasLockUpdateStatus` already tests that `get_danalock_config` is called lazily on the first `async_update_status()` call. Missing: a test that verifies it is **not** called again on the second call (the `_danalock_config_fetched` guard).

**Files:**
- Modify: `tests/test_ha_platforms.py`

**Step 1: Write the failing test**

Add inside `class TestSecuritasLockUpdateStatus` (after the existing `test_config_fetch_with_holdback_triggers_state_write` test):

```python
async def test_danalock_config_fetched_only_once(self):
    """get_danalock_config must be called exactly once even across multiple updates."""
    lock = make_lock()
    lock.client.get_danalock_config = AsyncMock(return_value=None)
    lock.client.get_lock_modes = AsyncMock(
        return_value=[SmartLockMode(lockStatus="2", deviceId="01")]
    )

    await lock.async_update_status()
    await lock.async_update_status()

    lock.client.get_danalock_config.assert_awaited_once()
```

**Step 2: Run to verify it fails**

```bash
python -m pytest "tests/test_ha_platforms.py::TestSecuritasLockUpdateStatus::test_danalock_config_fetched_only_once" -v
```

Expected: PASS immediately (if the production logic is correct). If it fails, the `_danalock_config_fetched` guard in `lock.py:150-151` is broken — investigate before continuing.

**Step 3: Run the full lock test suite**

```bash
python -m pytest tests/test_ha_platforms.py -v
```

Expected: All PASS.

**Step 4: Commit**

```bash
git add tests/test_ha_platforms.py
git commit -m "test(lock): verify Danalock config is fetched exactly once"
```

---

## Task 3: `_discover_cameras` tests

`_discover_cameras` (in `custom_components/securitas/__init__.py:437`) has no tests. It handles two edge cases: (1) empty camera list — must not crash and must not call `camera_add`, (2) exception from `hub.get_camera_devices()` — must log a warning and leave `cameras` as `[]`.

**Files:**
- Modify: `tests/test_init.py`

**Step 1: Write the failing tests**

Add a new test class at the bottom of `tests/test_init.py` (before the last line of the file):

```python
# ===========================================================================
# _discover_cameras tests
# ===========================================================================


class TestDiscoverCameras:
    """Tests for _discover_cameras() background discovery function."""

    @pytest.mark.asyncio
    async def test_empty_camera_list_adds_no_entities(self):
        """When no cameras are found, camera_add_entities must not be called."""
        from custom_components.securitas import _discover_cameras
        from tests.conftest import make_installation

        hub = MagicMock()
        hub.get_camera_devices = AsyncMock(return_value=[])
        camera_add = MagicMock()
        button_add = MagicMock()
        entry_data = {
            "camera_add_entities": camera_add,
            "button_add_entities": button_add,
        }

        await _discover_cameras(hub, make_installation(), entry_data)

        camera_add.assert_not_called()
        button_add.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_from_get_camera_devices_is_caught(self):
        """An exception in get_camera_devices must not propagate — log and continue."""
        from custom_components.securitas import _discover_cameras
        from tests.conftest import make_installation

        hub = MagicMock()
        hub.get_camera_devices = AsyncMock(
            side_effect=Exception("network failure")
        )
        camera_add = MagicMock()
        button_add = MagicMock()
        entry_data = {
            "camera_add_entities": camera_add,
            "button_add_entities": button_add,
        }

        # Must not raise
        await _discover_cameras(hub, make_installation(), entry_data)

        # And must not have added any entities
        camera_add.assert_not_called()
        button_add.assert_not_called()
```

**Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_init.py::TestDiscoverCameras -v
```

Expected: FAIL with `ImportError` or `AttributeError` because `_discover_cameras` may not be importable (check if it is exported in `__init__.py`).

**Step 3: Verify `_discover_cameras` is importable**

Check `custom_components/securitas/__init__.py` — `_discover_cameras` is a module-level `async def`. It is importable directly. If the import fails with a different error, re-read the imports at the top of the test class.

**Step 4: Run to verify they pass**

```bash
python -m pytest tests/test_init.py::TestDiscoverCameras -v
```

Expected: All PASS.

**Step 5: Run the full init test suite**

```bash
python -m pytest tests/test_init.py -v
```

Expected: All PASS.

**Step 6: Commit**

```bash
git add tests/test_init.py
git commit -m "test(init): add _discover_cameras edge case tests"
```

---

## Task 4: Merge `constants.py` into `const.py`

`constants.py` contains only `SentinelName`. Two files import it: `sensor.py` and `tests/test_constants.py`.

**Files:**
- Modify: `custom_components/securitas/const.py`
- Modify: `custom_components/securitas/sensor.py`
- Modify: `tests/test_constants.py`
- Delete: `custom_components/securitas/constants.py`

**Step 1: Move `SentinelName` into `const.py`**

Open `custom_components/securitas/const.py` and append at the end (after the `PLATFORMS` list):

```python


class SentinelName:
    """Define the sentinel string name for each language."""

    def __init__(self) -> None:
        """Define default constructor."""
        self.sentinel_name = {
            "default": "CONFORT",
            "es": "CONFORT",
            "br": "COMFORTO",
            "pt": "COMFORTO",
        }

    def get_sentinel_name(self, language: str) -> str:
        """Get the sentinel string for the language."""
        return self.sentinel_name.get(language, self.sentinel_name["default"])
```

**Step 2: Update `sensor.py` import**

In `custom_components/securitas/sensor.py` line 14, change:

```python
from .constants import SentinelName
```

to:

```python
from .const import SentinelName
```

**Step 3: Update `tests/test_constants.py` import**

In `tests/test_constants.py` line 5, change:

```python
from custom_components.securitas.constants import SentinelName
```

to:

```python
from custom_components.securitas.const import SentinelName
```

**Step 4: Delete `constants.py`**

```bash
rm custom_components/securitas/constants.py
```

**Step 5: Run the constants tests and full suite**

```bash
python -m pytest tests/test_constants.py -v
python -m pytest tests/ -v --tb=short -q
```

Expected: All PASS. If any test fails with `ModuleNotFoundError: No module named 'custom_components.securitas.constants'`, there is a third import site — search with:

```bash
grep -r "from .constants\|from custom_components.securitas.constants" .
```

**Step 6: Commit**

```bash
git add custom_components/securitas/const.py
git add custom_components/securitas/sensor.py
git add tests/test_constants.py
git rm custom_components/securitas/constants.py
git commit -m "refactor: merge SentinelName from constants.py into const.py"
```

---

## Task 5: Run full test suite and check coverage

Before updating the docs, get the current numbers.

**Step 1: Run with coverage**

```bash
cd /workspaces/securitas-direct-new-api/.worktrees/rewrite
python -m pytest tests/ --cov=custom_components/securitas --cov-report=term-missing -q 2>&1 | tail -40
```

Note the total test count and the per-module coverage percentages. You will use these in the next task.

**Step 2: Confirm coverage is ≥ 90%**

If coverage drops below 90%, investigate which lines are uncovered (`--cov-report=term-missing`) and fix before proceeding.

---

## Task 6: Update `architecture.md`

**Files:**
- Modify: `docs/architecture.md`

**Step 1: Update the testing overview section**

Find the paragraph that says "The test suite has 737 tests achieving 90% overall coverage" (around line 570). Update the test count to match the actual number from Task 5.

**Step 2: Update the test architecture list**

The `tests/` directory listing in the architecture doc should be accurate. Verify each file still exists and the descriptions match. No new test files were added in this work (all tests were added to existing files).

**Step 3: Update the coverage table**

The table starting around line 699 lists per-module coverage. Update:
- `camera.py` — should be higher after Task 1 tests
- `lock.py` — should be higher or equal after Task 2 test
- `__init__.py` — should be slightly higher after Task 3 tests
- Remove `constants.py` row (deleted in Task 4)
- Add note in `const.py` row: "`SentinelName` moved here from `constants.py`"

Use the coverage output from Task 5 for the actual percentages.

**Step 4: Update the file reference table**

The table at the bottom (around line 732) has a `constants.py` row. Remove it. Update the `const.py` row to note that `SentinelName` now lives here. Update line counts for any files that changed.

**Step 5: Run the tests one final time to confirm nothing broke**

```bash
python -m pytest tests/ -q --tb=short
```

Expected: All PASS, coverage ≥ 90%.

**Step 6: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: update architecture.md to reflect current test count, coverage, and constants merge"
```

---

## Final verification

```bash
python -m pytest tests/ --cov=custom_components/securitas --cov-fail-under=90 -q
ruff check custom_components/ tests/
pyright custom_components/
```

All three must pass cleanly.
