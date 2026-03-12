# Code / Doc / Test Audit Design

**Date:** 2026-03-12
**Branch:** rewrite/v_four

## Goal

Bring the codebase, documentation, and test suite into alignment by:

1. Writing missing tests for identified coverage gaps
2. Merging `constants.py` into `const.py` (redundant module)
3. Updating `architecture.md` to reflect the current code state

## Approach

Tests first, constants merge second, docs last — so the architecture doc is updated in a single pass after the code is settled and test counts are final.

---

## Section 1: Missing tests

### Lock (`test_ha_platforms.py`)

- **Danalock config lazy-loading** — `async_update()` on first call fetches `get_danalock_config()` and populates `extra_state_attributes` (battery threshold, auto-lock settings, arm-lock policies, latch hold-back time). Subsequent calls do not re-fetch.
- **`holdBackLatchTime > 0` → OPEN feature** — when `holdBackLatchTime > 0`, `supported_features` includes `LockEntityFeature.OPEN`. When `holdBackLatchTime == 0`, it does not.
- **Error recovery** — `SecuritasDirectError` raised during `async_lock()` / `async_unlock()` reverts entity state to the pre-operation value and calls `_notify_error`.

### Camera (`test_camera_platform.py`)

- **Lazy thumbnail fetch** — `async_camera_image()` calls `fetch_latest_thumbnail()` on first call when no cached image exists.
- **Cached image returned on subsequent calls** — second call returns cached bytes without re-fetching.
- **30-minute refresh timer** — `async_added_to_hass()` registers an `async_track_time_interval` callback at 30-minute interval.

### Init (`test_init.py`)

- **Empty camera list** — `_async_discover_devices` with `get_camera_devices()` returning `[]` adds no entities and does not crash.
- **Camera discovery exception** — `_async_discover_devices` when `get_camera_devices()` raises `SecuritasDirectError` logs a warning and continues to lock discovery (does not abort the whole task).

---

## Section 2: `constants.py` merge

`constants.py` contains only the `SentinelName` class (21 lines). It is imported solely by `sensor.py`.

- Move `SentinelName` into `const.py`
- Update `sensor.py` import: `from .const import SentinelName`
- Delete `constants.py`

---

## Section 3: `architecture.md` update

After the above changes are complete, do a single pass on `architecture.md`:

- **File reference table** — update line counts (they drift as code evolves), remove `constants.py` row, note `SentinelName` moved to `const.py`
- **Test count** — update from the stale "737 tests" to the actual current count
- **Coverage table** — add `hub.py` and `entity.py` rows (currently blank), update `camera.py` and lock coverage percentages after new tests land
- **Setup flow table** — verify camera and lock rows are still accurate

---

## Success criteria

- `pytest` passes with coverage ≥ 90%
- No import errors after `constants.py` deletion
- `architecture.md` file reference table, test count, and coverage table match reality
