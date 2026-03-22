# YP (PIR) camera support

## Problem

The `xSDeviceList` API returns perimetral exterior cameras with `type: "YP"`, but the integration only processes `{"QR", "YR"}` device types. These YP cameras are silently skipped, causing users to see only 2 of 3 cameras (issue #398).

## Evidence

HAR capture from @kytos22 confirms:

- `xSDeviceList` returns `{"id": "4", "code": "3", "zoneId": "YP03", "name": "Fachada", "type": "YP", "isActive": true}`
- `mkGetAllCameras` returns the same device under `pir[]` with `type: "YP"`, `deviceId: "03"`, `code: "3"`
- `mkGetThumbnail` works with `device: "YP"`, `zoneId: "YP03"` -- returns images
- `RequestImages` uses `deviceType: 103` for YP cameras (vs `106` for QR)

## Changes

### 1. Add `device_type` field to `CameraDevice`

In `dataTypes.py`, add `device_type: str = ""` to the `CameraDevice` dataclass. Populated from `d["type"]` during `get_device_list`.

### 2. Add `"YP"` to `CAMERA_DEVICE_TYPES`

In `apimanager.py`, change from `{"QR", "YR"}` to `{"QR", "YR", "YP"}`.

### 3. Replace `IMAGE_DEVICE_TYPE` constant with a mapping

```python
IMAGE_DEVICE_TYPE_MAP = {"QR": 106, "YR": 106, "YP": 103}
```

### 4. Update `request_images()` signature

Add `device_type: str` parameter. Look up `IMAGE_DEVICE_TYPE_MAP[device_type]` instead of using the constant.

### 5. Pass device type to `get_thumbnail()`

The `device` GraphQL variable should be the type code (`"QR"`, `"YP"`), not the camera alias. Hub calls change from `device.name` to `device.device_type`.

### 6. Update hub `capture_image` and `fetch_latest_thumbnail`

Pass `device.device_type` where the API needs the type code. Pass `device.device_type` to `request_images`.

### 7. Tests

Extend existing camera tests to cover YP device type, including the `deviceType` mapping.

## What stays the same

- `CameraDevice.name` still stores the alias (logging, HA entity naming)
- `zone_id` fallback logic (already handles null)
- Hub capture polling flow
- Entity creation and signals
- GraphQL queries (no schema changes needed)
