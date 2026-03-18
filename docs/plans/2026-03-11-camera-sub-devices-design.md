# Camera Sub-Devices Design

## Problem

All Securitas entities — alarm panel, cameras, capture buttons, locks — are grouped
under a single HA device per installation (`v4_securitas_direct.{number}`).  When an
installation has multiple cameras, every camera card's `_findCaptureButton` matches
on the shared `device_id` and always returns the *first* `mdi:camera` button it
encounters, regardless of which camera the card is showing.

## Decision

Give each camera its own child HA device.  The camera entity and its capture button
both belong to this per-camera device.  The device is linked to the installation
device via `via_device`.

Backwards compatibility is not a concern for this change.

## Device Identifier Scheme

| Device | Identifier |
|--------|-----------|
| Installation (existing) | `v4_securitas_direct.{installation.number}` |
| Camera sub-device (new) | `v4_securitas_direct.{installation.number}_camera_{zone_id}` |

## Component Changes

### `entity.py`

Add `camera_device_info(installation, camera_device) → DeviceInfo` alongside the
existing `securitas_device_info`:

```python
DeviceInfo(
    identifiers={(DOMAIN, f"v4_securitas_direct.{installation.number}_camera_{camera_device.zone_id}")},
    name=camera_device.name,
    manufacturer="Securitas Direct",
    model="Camera",
    via_device=(DOMAIN, f"v4_securitas_direct.{installation.number}"),
)
```

### `camera.py`

Replace `securitas_device_info(installation)` with
`camera_device_info(installation, camera_device)` in `SecuritasCamera.__init__`.

### `button.py`

`SecuritasCaptureButton.__init__` overrides `_attr_device_info` after calling
`super().__init__()`:

```python
self._attr_device_info = camera_device_info(installation, camera_device)
```

### `www/securitas-camera-card.js`

Revert `_findCaptureButton` to the simple `device_id` + `mdi:camera` icon approach.
Since each camera sub-device now contains exactly one capture button, the first
match is always correct — no name heuristics needed.

## Entity IDs

Entity names and unique IDs are unchanged.  HA's entity registry keys entities by
`unique_id`, so entity IDs remain stable and existing automations are unaffected.
Only the device grouping in the UI changes (entities move from the installation
device to the new per-camera child device).

## UX Impact

- Each camera appears as a named child device under the installation in the HA
  device list
- Users can assign different areas to individual cameras
- The installation device retains the alarm panel, locks, and non-camera entities
