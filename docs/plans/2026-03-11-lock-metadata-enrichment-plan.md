# Lock Metadata Enrichment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enrich `SmartLock` dataclass with API fields and give each lock its own HA device entry with proper metadata, linked to the installation as parent.

**Architecture:** Expand `SmartLock` fields, add `device_id` param to `get_smart_lock_config()`, fetch config during background discovery, override `device_info` on lock entity to create a child device.

**Tech Stack:** Home Assistant `DeviceInfo`, Python dataclasses, pytest

**Design doc:** `docs/plans/2026-03-11-lock-metadata-enrichment-design.md`

---

### Task 1: Enrich SmartLock dataclass and API parsing

**Files:**
- Modify: `custom_components/securitas/securitas_direct_new_api/dataTypes.py:128-134`
- Modify: `custom_components/securitas/securitas_direct_new_api/apimanager.py:779-804`
- Modify: `custom_components/securitas/securitas_direct_new_api/__init__.py:18-31`
- Test: `tests/test_smart_lock.py`

**Step 1: Write the failing tests**

In `tests/test_smart_lock.py`, update the existing `TestGetSmartLockConfig` class. The existing `test_success_returns_smart_lock` test (line 36) already has the API response with all fields but only asserts `res`, `location`, `type`. Add assertions for new fields and a new test for `device_id` parameter:

```python
    async def test_success_returns_all_fields(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetSmartlockConfig": {
                    "res": "OK",
                    "location": "Front Door",
                    "type": 1,
                    "referenceId": "ref1",
                    "zoneId": "z1",
                    "serialNumber": "SN001",
                    "family": "DR",
                    "label": "lock1",
                    "features": None,
                }
            }
        }

        result = await authed_api.get_smart_lock_config(installation)

        assert result.res == "OK"
        assert result.location == "Front Door"
        assert result.type == 1
        assert result.deviceId == ""  # not in response, uses default
        assert result.referenceId == "ref1"
        assert result.zoneId == "z1"
        assert result.serialNumber == "SN001"
        assert result.family == "DR"
        assert result.label == "lock1"

    async def test_device_id_passed_to_query(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetSmartlockConfig": {
                    "res": "OK",
                    "location": "Back Door",
                    "type": 1,
                }
            }
        }

        await authed_api.get_smart_lock_config(installation, device_id="02")

        call_args = mock_execute.call_args[0][0]
        devices = call_args["variables"]["devices"]
        assert devices[0]["deviceId"] == "02"

    async def test_missing_fields_use_defaults(
        self, authed_api, mock_execute, installation
    ):
        """Fields not in the response should use dataclass defaults."""
        mock_execute.return_value = {
            "data": {
                "xSGetSmartlockConfig": {
                    "res": "OK",
                    "location": "Hall",
                    "type": 2,
                }
            }
        }

        result = await authed_api.get_smart_lock_config(installation)

        assert result.res == "OK"
        assert result.location == "Hall"
        assert result.referenceId == ""
        assert result.serialNumber == ""
        assert result.family == ""
        assert result.label == ""
```

Replace the existing `test_success_returns_smart_lock` with `test_success_returns_all_fields` above.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_smart_lock.py::TestGetSmartLockConfig -v`
Expected: `test_success_returns_all_fields` FAILS (SmartLock has no `referenceId` attribute). `test_device_id_passed_to_query` FAILS (no `device_id` parameter).

**Step 3: Implement changes**

In `custom_components/securitas/securitas_direct_new_api/dataTypes.py`, replace lines 128-134:

```python
@dataclass
class SmartLock:
    """Smart lock discovery response."""

    res: str | None = None
    location: str | None = None
    type: int | None = None
    deviceId: str = ""
    referenceId: str = ""
    zoneId: str = ""
    serialNumber: str = ""
    family: str = ""
    label: str = ""
```

In `custom_components/securitas/securitas_direct_new_api/apimanager.py`, replace lines 779-804:

```python
    async def get_smart_lock_config(
        self, installation: Installation, device_id: str = SMARTLOCK_DEVICE_ID
    ) -> SmartLock:
        """Fetch smart lock configuration for the installation."""
        content = {
            "operationName": "xSGetSmartlockConfig",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "devices": [
                    {
                        "deviceType": SMARTLOCK_DEVICE_TYPE,
                        "deviceId": device_id,
                        "keytype": SMARTLOCK_KEY_TYPE,
                    }
                ],
            },
            "query": SMARTLOCK_CONFIG_QUERY,
        }
        await self._ensure_auth(installation)
        response = await self._execute_request(
            content, "xSGetSmartlockConfig", installation
        )

        raw_data = response.get("data", {}).get("xSGetSmartlockConfig")
        if raw_data is None:
            return SmartLock()
        return SmartLock(
            res=raw_data.get("res"),
            location=raw_data.get("location"),
            type=raw_data.get("type"),
            referenceId=raw_data.get("referenceId", ""),
            zoneId=raw_data.get("zoneId", ""),
            serialNumber=raw_data.get("serialNumber", ""),
            family=raw_data.get("family", ""),
            label=raw_data.get("label", ""),
        )
```

In `custom_components/securitas/securitas_direct_new_api/__init__.py`, add `SmartLock` to the imports (line 18-31):

```python
from .dataTypes import (  # noqa: F401
    Attribute,
    Attributes,
    CameraDevice,
    DanalockConfig,
    Installation,
    OperationStatus,
    OtpPhone,
    Service,
    SStatus,
    SmartLock,
    SmartLockMode,
    SmartLockModeStatus,
    ThumbnailResponse,
)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_smart_lock.py::TestGetSmartLockConfig -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add custom_components/securitas/securitas_direct_new_api/dataTypes.py \
       custom_components/securitas/securitas_direct_new_api/apimanager.py \
       custom_components/securitas/securitas_direct_new_api/__init__.py \
       tests/test_smart_lock.py
git commit -m "feat(lock): enrich SmartLock dataclass and add device_id param to get_smart_lock_config"
```

---

### Task 2: Add hub wrapper for get_smart_lock_config

**Files:**
- Modify: `custom_components/securitas/hub.py:614-623`
- Test: `tests/test_ha_platforms.py` (or verify via integration in Task 4)

**Step 1: Implement hub wrapper**

In `custom_components/securitas/hub.py`, add after `get_danalock_config` (after line 623):

```python
    async def get_smart_lock_config(
        self, installation: Installation, device_id: str
    ) -> Any:
        """Fetch smart lock config via queue-submitted API calls."""
        return await self._api_queue.submit(
            self.session.get_smart_lock_config,
            installation,
            device_id,
            priority=ApiQueue.FOREGROUND,
        )
```

Note: This follows the exact same pattern as `get_danalock_config` on line 614. No separate test needed — the pattern is proven and the underlying `get_smart_lock_config` is already tested in Task 1.

**Step 2: Run existing tests to verify no regressions**

Run: `python -m pytest tests/ -q`
Expected: All pass.

**Step 3: Commit**

```bash
git add custom_components/securitas/hub.py
git commit -m "feat(lock): add get_smart_lock_config hub wrapper"
```

---

### Task 3: Override device_info on SecuritasLock

**Files:**
- Modify: `custom_components/securitas/lock.py:58-93`
- Modify: `tests/test_ha_platforms.py` (update `make_lock`, update/replace device_info tests, add new tests)

**Step 1: Write the failing tests**

First, update `make_lock` in `tests/test_ha_platforms.py` (line 89) to accept `lock_config`:

```python
def make_lock(
    device_id: str = "01",
    initial_status: str = "2",
    danalock_config: DanalockConfig | None = None,
    lock_config: SmartLock | None = None,
):
    """Create a SecuritasLock with mocked dependencies."""
    installation = make_installation()
    client = MagicMock()
    client.config = {"scan_interval": 120}
    client.session = AsyncMock()
    client.change_lock_mode = AsyncMock()
    client.get_danalock_config = AsyncMock(return_value=None)
    hass = MagicMock()
    hass.async_create_task = MagicMock()
    hass.services = MagicMock()

    lock_entity = SecuritasLock(
        installation=installation,
        client=client,
        hass=hass,
        device_id=device_id,
        initial_status=initial_status,
        danalock_config=danalock_config,
        lock_config=lock_config,
    )
    lock_entity.entity_id = f"lock.securitas_{installation.number}_{device_id}"
    # Mock HA state-writing methods (no platform registered in unit tests)
    lock_entity.async_write_ha_state = MagicMock()
    lock_entity.async_schedule_update_ha_state = MagicMock()
    return lock_entity
```

Add `SmartLock` to the imports at the top of the test file:

```python
from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    ...existing imports...,
    SmartLock,
)
```

Then replace `test_device_info_groups_under_installation` (line 518) and add new tests in `TestSecuritasLockConfig`:

```python
    def test_device_info_creates_separate_lock_device_with_config(self):
        """Lock with config gets its own device with metadata."""
        config = SmartLock(
            res="OK",
            location="Front Door",
            family="DR",
            serialNumber="SN001",
        )
        lock = make_lock(device_id="01", lock_config=config)
        info = lock._attr_device_info
        assert info is not None
        assert info["identifiers"] == {
            ("securitas", "securitas_direct.123456_lock_01")
        }
        assert info["via_device"] == ("securitas", "securitas_direct.123456")
        assert info["name"] == "Front Door"
        assert info["model"] == "DR"
        assert info["serial_number"] == "SN001"
        assert info["manufacturer"] == "Securitas Direct"

    def test_device_info_fallback_without_config(self):
        """Lock without config falls back to installation-based device."""
        lock = make_lock(device_id="01")
        info = lock._attr_device_info
        assert info is not None
        assert info["identifiers"] == {
            ("securitas", "securitas_direct.123456_lock_01")
        }
        assert info["via_device"] == ("securitas", "securitas_direct.123456")
        assert info["name"] == "Home Lock 01"
        assert info["manufacturer"] == "Securitas Direct"

    def test_device_info_fallback_empty_location(self):
        """Lock with config but empty location uses installation alias."""
        config = SmartLock(res="OK", location="", family="DR")
        lock = make_lock(device_id="02", lock_config=config)
        info = lock._attr_device_info
        assert info["name"] == "Home Lock 02"
        assert info["model"] == "DR"

    def test_device_info_different_devices_have_different_identifiers(self):
        """Each lock gets its own device identifier."""
        lock01 = make_lock(device_id="01")
        lock02 = make_lock(device_id="02")
        assert (
            lock01._attr_device_info["identifiers"]
            != lock02._attr_device_info["identifiers"]
        )
        # But both link to the same parent
        assert (
            lock01._attr_device_info["via_device"]
            == lock02._attr_device_info["via_device"]
        )
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ha_platforms.py -k "test_device_info" -v`
Expected: FAIL — `SecuritasLock.__init__` doesn't accept `lock_config`, device_info still uses installation device.

**Step 3: Implement changes in lock.py**

Modify `SecuritasLock.__init__` (line 61-93) to accept `lock_config` and override `_attr_device_info`:

```python
    def __init__(
        self,
        installation: Installation,
        client: SecuritasHub,
        hass: HomeAssistant,
        device_id: str = SMARTLOCK_DEVICE_ID,
        initial_status: str = LOCK_STATUS_LOCKED,
        danalock_config: DanalockConfig | None = None,
        lock_config: SmartLock | None = None,
    ) -> None:
        super().__init__(installation, client)
        self._state = (
            initial_status
            if initial_status != LOCK_STATUS_UNKNOWN
            else LOCK_STATUS_LOCKED
        )
        self._last_state = self._state
        self._new_state: str = self._state
        self._changed_by: str = ""
        self._device: str = installation.address
        self._device_id: str = device_id
        self._danalock_config: DanalockConfig | None = danalock_config
        self._danalock_config_fetched: bool = danalock_config is not None
        self._lock_config: SmartLock | None = lock_config

        self._attr_name = (
            lock_config.location
            if lock_config and lock_config.location
            else f"{installation.alias} Lock {device_id}"
        )
        self._attr_unique_id = (
            f"securitas_direct.{installation.number}_lock_{device_id}"
        )

        # Override base class device_info: each lock is its own device,
        # linked to the installation device as parent.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"securitas_direct.{installation.number}_lock_{device_id}")},
            via_device=(DOMAIN, f"securitas_direct.{installation.number}"),
            name=self._attr_name,
            manufacturer="Securitas Direct",
            model=(
                lock_config.family
                if lock_config and lock_config.family
                else None
            ),
            serial_number=(
                lock_config.serialNumber
                if lock_config and lock_config.serialNumber
                else None
            ),
        )

        self.hass: HomeAssistant = hass
        scan_seconds = client.config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self._update_interval: timedelta = timedelta(seconds=scan_seconds)
        self._scan_seconds = scan_seconds
        self._update_unsub = None
```

Add `SmartLock` to the imports at the top of `lock.py`:

```python
from .securitas_direct_new_api import (
    DanalockConfig,
    Installation,
    SecuritasDirectError,
    SmartLock,
)
```

Also add `DeviceInfo` import:

```python
from homeassistant.helpers.device_registry import DeviceInfo
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ha_platforms.py -k "test_device_info or test_name" -v`
Expected: All PASS.

Also check `test_name_returns_installation_alias_with_device_id` still passes (no lock_config = fallback name).

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: All pass.

**Step 6: Commit**

```bash
git add custom_components/securitas/lock.py tests/test_ha_platforms.py
git commit -m "feat(lock): per-lock DeviceInfo with metadata from SmartLock config"
```

---

### Task 4: Fetch SmartLock config during discovery

**Files:**
- Modify: `custom_components/securitas/__init__.py:461-515`
- Test: Integration verified by existing + new tests

**Step 1: Update `_discover_locks()` in `__init__.py`**

Replace lines 461-515:

```python
async def _discover_locks(
    hass: HomeAssistant,
    hub: SecuritasHub,
    installation: Installation,
    entry_data: dict,
) -> None:
    """Discover lock devices for an installation and add entities."""
    from .entity import schedule_initial_updates
    from .lock import (
        DOORLOCK_SERVICE,
        LOCK_STATUS_UNKNOWN,
        SecuritasLock,
    )
    from .securitas_direct_new_api import SmartLock, SmartLockMode
    from .securitas_direct_new_api.apimanager import SMARTLOCK_DEVICE_ID

    try:
        services = await hub.get_services(installation)
    except Exception:  # pylint: disable=broad-exception-caught  # background discovery must not crash
        _LOGGER.warning("Failed to get services for %s", installation.number)
        return

    has_doorlock = any(s.request == DOORLOCK_SERVICE for s in services)
    if not has_doorlock:
        return

    try:
        lock_modes: list[SmartLockMode] = await hub.get_lock_modes(installation)
    except Exception:  # pylint: disable=broad-exception-caught  # background discovery must not crash
        _LOGGER.warning("Failed to get lock modes for %s", installation.number)
        lock_modes = []

    if not lock_modes:
        lock_modes = [
            SmartLockMode(
                res=None,
                lockStatus=LOCK_STATUS_UNKNOWN,
                deviceId=SMARTLOCK_DEVICE_ID,
            )
        ]

    lock_add = entry_data.get("lock_add_entities")
    if lock_add:
        locks = []
        for mode in lock_modes:
            device_id = mode.deviceId or SMARTLOCK_DEVICE_ID
            lock_config: SmartLock | None = None
            try:
                lock_config = await hub.get_smart_lock_config(
                    installation, device_id
                )
            except Exception:  # pylint: disable=broad-exception-caught
                _LOGGER.debug(
                    "Could not fetch smart lock config for %s device %s",
                    installation.number,
                    device_id,
                )
            locks.append(
                SecuritasLock(
                    installation,
                    client=hub,
                    hass=hass,
                    device_id=device_id,
                    initial_status=mode.lockStatus,
                    lock_config=lock_config,
                )
            )
        lock_add(locks, False)
        schedule_initial_updates(hass, locks)
```

**Step 2: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: All pass.

**Step 3: Commit**

```bash
git add custom_components/securitas/__init__.py
git commit -m "feat(lock): fetch SmartLock config during background discovery"
```

---

### Task 5: Update architecture docs

**Files:**
- Modify: `docs/architecture.md` (lock section)

**Step 1: Update docs**

Find the lock discovery section in `docs/architecture.md` and update it to mention:
- `get_smart_lock_config(device_id)` is called per lock during background discovery
- Each lock creates a separate HA device with `via_device` linking to the installation
- Lock device metadata comes from the `xSGetSmartlockConfig` API (location, serial, family)
- Config fetch is optional; failure produces a lock with fallback metadata

**Step 2: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: document per-lock DeviceInfo and metadata enrichment"
```
