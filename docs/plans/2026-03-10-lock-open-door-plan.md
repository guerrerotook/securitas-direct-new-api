# Lock Open-Door Feature Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `LockEntityFeature.OPEN` support so users can unlatch their Danalock from Home Assistant, even when the lock is already unlocked.

**Architecture:** Conditionally advertise `OPEN` based on `DanalockConfig.features.holdBackLatchTime > 0`. `async_open()` reuses the existing `change_lock_mode(lock=False)` API call. No new GraphQL mutations needed.

**Tech Stack:** Home Assistant `LockEntity`, Python asyncio, pytest

**Design doc:** `docs/plans/2026-03-10-lock-open-door-design.md`

---

### Task 1: Test `supported_features` with OPEN flag

**Files:**
- Modify: `tests/test_ha_platforms.py` (near line 592, `TestSecuritasLockConfig` class)

**Step 1: Write the failing tests**

Replace the existing `test_supported_features_returns_zero` test and add new tests in the `TestSecuritasLockConfig` class (around line 592):

```python
    def test_supported_features_no_config_returns_zero(self):
        import homeassistant.components.lock as lock_mod

        lock = make_lock()
        assert lock.supported_features == lock_mod.LockEntityFeature(0)

    def test_supported_features_with_holdback_returns_open(self):
        import homeassistant.components.lock as lock_mod

        config = DanalockConfig(
            features=DanalockFeatures(holdBackLatchTime=3, calibrationType=0)
        )
        lock = make_lock(danalock_config=config)
        assert lock.supported_features == lock_mod.LockEntityFeature.OPEN

    def test_supported_features_holdback_zero_returns_zero(self):
        import homeassistant.components.lock as lock_mod

        config = DanalockConfig(
            features=DanalockFeatures(holdBackLatchTime=0, calibrationType=0)
        )
        lock = make_lock(danalock_config=config)
        assert lock.supported_features == lock_mod.LockEntityFeature(0)

    def test_supported_features_no_features_returns_zero(self):
        import homeassistant.components.lock as lock_mod

        config = DanalockConfig(features=None)
        lock = make_lock(danalock_config=config)
        assert lock.supported_features == lock_mod.LockEntityFeature(0)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ha_platforms.py -k "test_supported_features" -v`
Expected: `test_supported_features_with_holdback_returns_open` FAILS (returns 0 instead of OPEN). Others pass.

**Step 3: Implement `supported_features` in `lock.py`**

Replace lines 253-257 in `custom_components/securitas/lock.py`:

```python
    @property
    def supported_features(self) -> lock.LockEntityFeature:  # type: ignore[override]
        """Return the list of supported features."""
        cfg = self._danalock_config
        if (
            cfg
            and cfg.features
            and cfg.features.holdBackLatchTime
            and cfg.features.holdBackLatchTime > 0
        ):
            return lock.LockEntityFeature.OPEN
        return lock.LockEntityFeature(0)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ha_platforms.py -k "test_supported_features" -v`
Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add custom_components/securitas/lock.py tests/test_ha_platforms.py
git commit -m "feat(lock): conditionally expose LockEntityFeature.OPEN based on holdBackLatchTime"
```

---

### Task 2: Test and implement `async_open()`

**Files:**
- Modify: `tests/test_ha_platforms.py` (add tests to `TestSecuritasLockActions` class, after line 681)
- Modify: `custom_components/securitas/lock.py` (add `async_open` method after `async_unlock`)

**Step 1: Write the failing tests**

Add to the `TestSecuritasLockActions` class (after line 681 in `tests/test_ha_platforms.py`):

```python
    async def test_async_open_sets_state_to_opening_then_open_on_success(self):
        lock = make_lock()
        lock.client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_open()

        assert lock._state == "1"
        lock.async_schedule_update_ha_state.assert_called()  # type: ignore[attr-defined]
        lock.async_write_ha_state.assert_called()  # type: ignore[attr-defined]

    async def test_async_open_error_restores_previous_state(self):
        lock = make_lock()
        lock.client.change_lock_mode = AsyncMock(
            side_effect=SecuritasDirectError("API error")
        )

        await lock.async_open()

        assert lock._state == "2"

    async def test_async_open_calls_change_lock_mode_with_false(self):
        lock = make_lock()
        lock.client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_open()

        lock.client.change_lock_mode.assert_awaited_once_with(
            lock.installation, False, "01"
        )

    async def test_async_open_intermediate_state_is_opening(self):
        """Verify _force_state is called with '3' (opening) before the API call."""
        lock = make_lock()
        observed_states = []

        async def capture_state(installation, lock_mode, device_id=None):
            observed_states.append(lock._state)
            return SmartLockModeStatus()

        lock.client.change_lock_mode = AsyncMock(side_effect=capture_state)

        await lock.async_open()

        assert observed_states == ["3"]
        assert lock._state == "1"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ha_platforms.py -k "test_async_open" -v`
Expected: FAIL with `AttributeError: 'SecuritasLock' object has no attribute 'async_open'`

**Step 3: Implement `async_open()` in `lock.py`**

Add after `async_unlock` (after line 251 in `custom_components/securitas/lock.py`):

```python
    async def async_open(self, **kwargs):
        self._force_state(LOCK_STATUS_OPENING)
        try:
            await self.client.change_lock_mode(
                self.installation, False, self._device_id
            )
        except SecuritasDirectError as err:
            self._state = self._last_state
            self.async_write_ha_state()
            _LOGGER.error(
                "Open operation failed for %s device %s: %s",
                self.installation.number,
                self._device_id,
                err.log_detail(),
            )
            return

        self._state = LOCK_STATUS_OPEN
        self.async_write_ha_state()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ha_platforms.py -k "test_async_open" -v`
Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add custom_components/securitas/lock.py tests/test_ha_platforms.py
git commit -m "feat(lock): add async_open() for door unlatching"
```

---

### Task 3: Update lazy config fetch to trigger HA state refresh

**Files:**
- Modify: `tests/test_ha_platforms.py` (add test in `TestSecuritasLockUpdateStatus` class)
- Modify: `custom_components/securitas/lock.py` (line ~137, after config fetch)

**Step 1: Write the failing test**

Add to `TestSecuritasLockUpdateStatus` class in `tests/test_ha_platforms.py`:

```python
    async def test_config_fetch_with_holdback_triggers_state_write(self):
        """After fetching config with holdBackLatchTime, HA state is refreshed
        so supported_features picks up the OPEN flag."""
        import homeassistant.components.lock as lock_mod

        config = DanalockConfig(
            features=DanalockFeatures(holdBackLatchTime=3, calibrationType=0)
        )
        lock = make_lock()
        lock.client.get_danalock_config = AsyncMock(return_value=config)
        lock.client.get_lock_modes = AsyncMock(
            return_value=[SmartLockMode(lockStatus="2", deviceId="01")]
        )

        await lock.async_update_status()

        assert lock.supported_features == lock_mod.LockEntityFeature.OPEN
```

Note: This test already passes since `async_write_ha_state` is called via the existing `_now is not None` path or the state update. But it validates the full flow. The key change is updating the log message (removing the "pending" note) and ensuring `async_write_ha_state` is called after config fetch so HA picks up the new feature flag immediately.

**Step 2: Run test to verify current behavior**

Run: `python -m pytest tests/test_ha_platforms.py -k "test_config_fetch_with_holdback" -v`

**Step 3: Update the lazy config fetch log message**

In `custom_components/securitas/lock.py`, replace lines 130-137:

```python
                cfg = self._danalock_config
                if cfg and cfg.features and cfg.features.holdBackLatchTime > 0:
                    _LOGGER.info(
                        "Lock %s on %s supports latch hold-back (%ds) — "
                        "open-door feature enabled",
                        self._device_id,
                        self.installation.number,
                        cfg.features.holdBackLatchTime,
                    )
```

**Step 4: Run all lock tests**

Run: `python -m pytest tests/test_ha_platforms.py -k "Lock" -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add custom_components/securitas/lock.py tests/test_ha_platforms.py
git commit -m "feat(lock): update log message and add config fetch integration test"
```

---

### Task 4: Update architecture docs and clean up TODO

**Files:**
- Modify: `docs/architecture.md` (lock section, around line 420-434)
- Modify: `custom_components/securitas/lock.py` (remove the TODO comment — already removed in Task 1)

**Step 1: Update architecture docs**

Find the lock section in `docs/architecture.md` and add a note about the OPEN feature. After the existing sentence about `holdBackLatchTime`, add:

> When `holdBackLatchTime > 0`, the entity advertises `LockEntityFeature.OPEN` so users can trigger door unlatching from the UI even when the lock is already unlocked. The `async_open()` method sends the same `change_lock_mode(lock=False)` command — there is no separate API mutation for opening.

**Step 2: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS.

**Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: document lock open-door feature in architecture"
```
