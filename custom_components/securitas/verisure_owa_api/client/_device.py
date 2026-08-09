"""Peripheral inventory domain: the shared xSDeviceList fetch and its filters."""

from __future__ import annotations

import logging
from typing import Any

from ..graphql_queries import DEVICE_LIST_QUERY
from ..models import CameraDevice, Installation, PanelDevice
from ..responses import DeviceListEnvelope
from ._base import _ClientBase

_LOGGER = logging.getLogger(__name__)

# Camera device types. Kept here (rather than in _camera) because the shared
# filters below are what actually apply it, and _camera re-exports the name
# for the callers that already import it from there.
CAMERA_DEVICE_TYPES = {"QR", "YR", "YP", "QP"}

# Peripheral types eligible to become per-zone binary sensors.
#
# Only MG (magnetic door/window contact) for now: it is the only type ever
# observed in an xSStatus/xSGetExceptions payload, and the only type in a real
# xSDeviceList capture that isn't already an entity (DR is a lock, QR/YP are
# cameras, VV is an unidentified keypad-like device).
#
# To promote another type: capture a real exceptions payload containing it
# (docs/new_operations.md), confirm the alias matches this inventory's `name`,
# then add it here. Until then such a device still reaches the user through the
# orphan-alias path, so nothing is silently lost.
ZONE_DEVICE_TYPES = frozenset({"MG"})


def _parse_device(raw: dict[str, Any]) -> PanelDevice:
    """Build a PanelDevice from one raw xSDeviceList row.

    ``code`` is numeric-as-string in every observed response but is guarded
    anyway; a non-numeric code becomes 0 (it would be unusable for image
    capture regardless). ``zoneId`` can be null, so it falls back to the
    synthesised ``<type><code>`` form and finally to the row index ``id``.
    """
    code = int(raw["code"]) if str(raw.get("code", "")).isdigit() else None
    device_type = raw.get("type") or ""
    zone_id = raw.get("zoneId") or (
        f"{device_type}{code:02d}" if code is not None else raw.get("id") or ""
    )
    return PanelDevice(
        id=raw.get("id") or "",
        code=code or 0,
        zone_id=zone_id,
        name=raw.get("name") or "",
        device_type=device_type,
        is_active=raw.get("isActive"),
        serial_number=raw.get("serialNumber"),
    )


def _active_of_type(
    devices: list[PanelDevice], types: frozenset[str] | set[str]
) -> list[PanelDevice]:
    """Filter to active devices of the given types, deduplicated.

    Annex installations can return the same physical device twice in
    xSDeviceList (once per panel-view: main + annex sub-panel). The two rows
    share name + type + code; only the row index `id` differs. Without dedup
    HA's entity registry rejects the second row as a duplicate unique_id and
    silently drops the entity.
    See https://github.com/guerrerotook/securitas-direct-new-api/issues/441.

    ``is_active`` is rejected only when explicitly False — a null means the
    panel didn't report it, not that the device is disabled.
    """
    seen: set[tuple[str, int]] = set()
    result: list[PanelDevice] = []
    for device in devices:
        if device.device_type not in types or device.is_active is False:
            continue
        dedup_key = (device.device_type, device.code)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        result.append(device)
    return result


def filter_camera_devices(devices: list[PanelDevice]) -> list[CameraDevice]:
    """Narrow a full inventory to the camera devices."""
    return [
        CameraDevice(
            id=device.id,
            code=device.code,
            zone_id=device.zone_id,
            name=device.name,
            device_type=device.device_type,
            serial_number=device.serial_number,
        )
        for device in _active_of_type(devices, CAMERA_DEVICE_TYPES)
    ]


def filter_zone_devices(devices: list[PanelDevice]) -> list[PanelDevice]:
    """Narrow a full inventory to the peripherals that become zone sensors."""
    return _active_of_type(devices, ZONE_DEVICE_TYPES)


class _DeviceMixin(_ClientBase):
    """Whole-inventory peripheral discovery."""

    async def get_devices(self, installation: Installation) -> list[PanelDevice]:
        """Get every peripheral paired with the panel.

        One fetch serves both camera and zone discovery — apply
        ``filter_camera_devices`` / ``filter_zone_devices`` to narrow it.

        Returns:
            A list of PanelDevice instances, unfiltered and undeduplicated.
        """
        content = {
            "operationName": "xSDeviceList",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
            },
            "query": DEVICE_LIST_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "xSDeviceList",
            DeviceListEnvelope,
            installation=installation,
        )
        return [_parse_device(d) for d in envelope.data.xSDeviceList.devices or []]
