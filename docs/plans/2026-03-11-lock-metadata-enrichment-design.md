# Lock Metadata Enrichment & Per-Lock DeviceInfo

Inspired by: PR #388

## Problem

Lock entities share the installation's `DeviceInfo` (alarm panel model/name). They don't have their own device identity, and the `SmartLock` dataclass discards most of the data the API already returns (location, serial number, family, label).

## Design

### Data layer (`dataTypes.py`)

Enrich `SmartLock` with fields the `xSGetSmartlockConfig` API already returns:

```python
@dataclass
class SmartLock:
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

### API layer (`apimanager.py`)

`get_smart_lock_config()`:
- Add optional `device_id` parameter (default `SMARTLOCK_DEVICE_ID`)
- Parse all new fields from the API response

### Hub layer (`hub.py`)

Add `get_smart_lock_config(installation, device_id)` wrapper with queue serialization, matching the pattern of `get_danalock_config`.

### Discovery (`__init__.py`)

In `_discover_locks()`, after fetching lock modes:
- Call `hub.get_smart_lock_config(installation, device_id=X)` per discovered lock
- Pass the `SmartLock` config to `SecuritasLock` constructor
- Tolerate failure gracefully (create entity with `None` config)

### Entity (`lock.py`)

- Add `lock_config: SmartLock | None` constructor parameter
- Override `device_info` property to create a separate child device:
  - `identifiers`: `{(DOMAIN, f"securitas_direct.{installation.number}_lock_{device_id}")}`
  - `via_device`: `(DOMAIN, f"securitas_direct.{installation.number}")` (parent installation)
  - `name`: `lock_config.location` or fallback `f"{installation.alias} Lock {device_id}"`
  - `model`: `lock_config.family` or `"Danalock"`
  - `serial_number`: `lock_config.serialNumber` or `None`
  - `manufacturer`: `"Securitas Direct"`

### Exports (`securitas_direct_new_api/__init__.py`)

Re-export `SmartLock` from the package.

## Backward Compatibility

- `unique_id` stays as `securitas_direct.{number}_lock_{device_id}` -- no change
- Existing entities gain a new parent device on next restart; entity IDs unchanged
- If `get_smart_lock_config` fails, entity still works with fallback metadata

## Tests

- `SmartLock` dataclass parsing with all new fields
- `get_smart_lock_config()` with `device_id` parameter
- `SecuritasLock.device_info` returns separate device with lock metadata
- `SecuritasLock.device_info` fallback when `lock_config` is `None`
- `_discover_locks()` passes config to entity constructor
