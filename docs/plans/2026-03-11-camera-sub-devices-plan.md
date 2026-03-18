# Camera Sub-Devices Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give each Securitas camera its own child HA device so the camera card can
reliably find each camera's capture button via `device_id` matching.

**Architecture:** Add `camera_device_info(installation, camera_device)` to `entity.py`
that returns a `DeviceInfo` with `via_device` pointing to the installation device.
`SecuritasCamera` and `SecuritasCaptureButton` both use this new function instead of
`securitas_device_info`.  The card's `_findCaptureButton` reverts to the simple
device_id + icon lookup.

**Tech Stack:** Python/HA DeviceInfo, custom Lovelace card JS

---

### Task 1: Add `camera_device_info` to entity.py

**Files:**
- Modify: `custom_components/securitas/entity.py`
- Test: `tests/test_camera_platform.py`

**Step 1: Write the failing tests**

Add to `tests/test_camera_platform.py` (after the existing imports, before
`TestSecuritasCamera`):

```python
from custom_components.securitas import DOMAIN
from custom_components.securitas.entity import camera_device_info


class TestCameraDeviceInfo:
    def test_identifiers_include_zone_id(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert (DOMAIN, "v4_securitas_direct.2654190_camera_QR10") in info["identifiers"]

    def test_name_is_camera_device_name(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["name"] == "Salon"

    def test_manufacturer(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["manufacturer"] == "Securitas Direct"

    def test_model(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["model"] == "Camera"

    def test_via_device_points_to_installation(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["via_device"] == (DOMAIN, "v4_securitas_direct.2654190")
```

**Step 2: Run tests to confirm they fail**

```bash
cd /workspaces/securitas-direct-new-api/.worktrees/rewrite
python -m pytest tests/test_camera_platform.py::TestCameraDeviceInfo -v
```
Expected: ImportError or AttributeError — `camera_device_info` does not exist yet.

**Step 3: Implement `camera_device_info` in entity.py**

In `custom_components/securitas/entity.py`, add this import at the top alongside
`Installation`:

```python
from .securitas_direct_new_api.dataTypes import CameraDevice
```

Then add the new function after `securitas_device_info`:

```python
def camera_device_info(installation: Installation, camera_device: CameraDevice) -> DeviceInfo:
    """Build DeviceInfo for a per-camera child device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"v4_securitas_direct.{installation.number}_camera_{camera_device.zone_id}")},
        name=camera_device.name,
        manufacturer="Securitas Direct",
        model="Camera",
        via_device=(DOMAIN, f"v4_securitas_direct.{installation.number}"),
    )
```

**Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_camera_platform.py::TestCameraDeviceInfo -v
```
Expected: 5 PASSED.

**Step 5: Commit**

```bash
git add custom_components/securitas/entity.py tests/test_camera_platform.py
git commit -m "feat(camera): add camera_device_info for per-camera sub-devices"
```

---

### Task 2: Use `camera_device_info` in SecuritasCamera

**Files:**
- Modify: `custom_components/securitas/camera.py`
- Test: `tests/test_camera_platform.py`

**Step 1: Write the failing test**

Add to `TestSecuritasCamera` in `tests/test_camera_platform.py`:

```python
def test_device_info_uses_camera_sub_device(self, mock_hub, installation, camera_device):
    from custom_components.securitas.camera import SecuritasCamera
    from custom_components.securitas import DOMAIN

    cam = SecuritasCamera(mock_hub, installation, camera_device)
    info = cam.device_info
    assert (DOMAIN, "v4_securitas_direct.2654190_camera_QR10") in info["identifiers"]
    assert info.get("via_device") == (DOMAIN, "v4_securitas_direct.2654190")
```

**Step 2: Run test to confirm it fails**

```bash
python -m pytest tests/test_camera_platform.py::TestSecuritasCamera::test_device_info_uses_camera_sub_device -v
```
Expected: FAIL — `device_info` currently contains installation identifiers, not camera ones.

**Step 3: Update camera.py**

In `custom_components/securitas/camera.py`, add `camera_device_info` to the import:

```python
from .entity import securitas_device_info, camera_device_info
```

In `SecuritasCamera.__init__`, replace:

```python
self._attr_device_info = securitas_device_info(installation)
```

with:

```python
self._attr_device_info = camera_device_info(installation, camera_device)
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_camera_platform.py -v
```
Expected: all PASSED.

**Step 5: Commit**

```bash
git add custom_components/securitas/camera.py tests/test_camera_platform.py
git commit -m "feat(camera): SecuritasCamera uses camera sub-device"
```

---

### Task 3: Use `camera_device_info` in SecuritasCaptureButton

**Files:**
- Modify: `custom_components/securitas/button.py`
- Test: `tests/test_camera_platform.py`

**Step 1: Write the failing test**

Add to `TestSecuritasCaptureButton` in `tests/test_camera_platform.py`:

```python
def test_device_info_uses_camera_sub_device(self, mock_hub, installation, camera_device):
    from custom_components.securitas.button import SecuritasCaptureButton
    from custom_components.securitas import DOMAIN

    btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
    info = btn.device_info
    assert (DOMAIN, "v4_securitas_direct.2654190_camera_QR10") in info["identifiers"]
    assert info.get("via_device") == (DOMAIN, "v4_securitas_direct.2654190")
```

**Step 2: Run test to confirm it fails**

```bash
python -m pytest tests/test_camera_platform.py::TestSecuritasCaptureButton::test_device_info_uses_camera_sub_device -v
```
Expected: FAIL — `device_info` currently has installation identifiers (set by `SecuritasEntity.__init__`).

**Step 3: Update button.py**

In `custom_components/securitas/button.py`, add `camera_device_info` to the entity import:

```python
from .entity import SecuritasEntity, schedule_initial_updates, camera_device_info
```

In `SecuritasCaptureButton.__init__`, add one line after `self._attr_name`:

```python
self._attr_device_info = camera_device_info(installation, camera_device)
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_camera_platform.py tests/test_button.py -v
```
Expected: all PASSED. (`test_button.py` tests `SecuritasRefreshButton` which is unaffected.)

**Step 5: Commit**

```bash
git add custom_components/securitas/button.py tests/test_camera_platform.py
git commit -m "feat(camera): SecuritasCaptureButton uses camera sub-device"
```

---

### Task 4: Simplify `_findCaptureButton` in the card

**Files:**
- Modify: `custom_components/securitas/www/securitas-camera-card.js`

No unit tests for the card JS. Verify manually by loading two camera cards in HA
and confirming each shows its own refresh button.

**Step 1: Replace `_findCaptureButton`**

In `securitas-camera-card.js`, replace the current `_findCaptureButton` method with:

```javascript
_findCaptureButton(hass, cameraEntityId) {
  if (!hass?.entities || !cameraEntityId) return null;
  const cameraEntry = hass.entities[cameraEntityId];
  if (!cameraEntry?.device_id) return null;
  const deviceId = cameraEntry.device_id;
  // Camera and its capture button share the same per-camera sub-device.
  // There is exactly one mdi:camera button per camera device.
  for (const [eid, entry] of Object.entries(hass.entities)) {
    if (!eid.startsWith("button.")) continue;
    if (entry.device_id !== deviceId) continue;
    const stateObj = hass.states[eid];
    if (stateObj?.attributes?.icon === "mdi:camera") return eid;
  }
  return null;
}
```

**Step 2: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```
Expected: all PASSED.

**Step 3: Commit**

```bash
git add custom_components/securitas/www/securitas-camera-card.js
git commit -m "fix(camera-card): simplify _findCaptureButton using camera sub-device"
```

---

### Task 5: Deploy and verify

**Step 1: Deploy**

```bash
rsync -av --delete --exclude='__pycache__' \
  /workspaces/securitas-direct-new-api/.worktrees/rewrite/custom_components/securitas/ \
  /workspaces/homeassistant-core/config/custom_components/securitas/
```

**Step 2: Restart HA and verify**

- Each camera now appears as a child device under the installation in the HA device list
- Each camera card shows its own refresh button
- Clicking a refresh button triggers capture on the correct camera
