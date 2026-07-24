"""Magnetic contact domain: device discovery and opening state."""

from __future__ import annotations

from ..graphql_queries import CONTACT_STATUS_QUERY, DEVICE_LIST_QUERY
from ..models import ContactDevice, ContactState, Installation
from ..responses import ContactStatusEnvelope, DeviceListEnvelope
from ._base import _ClientBase

CONTACT_DEVICE_TYPES = {"MG", "MR"}


class _ContactMixin(_ClientBase):
    """Magnetic contact discovery and state fetch."""

    async def get_contact_devices(
        self, installation: Installation
    ) -> list[ContactDevice]:
        """Return active magnetic opening contacts for an installation."""
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
        devices = envelope.data.xSDeviceList.devices or []
        seen: set[str] = set()
        result: list[ContactDevice] = []
        for device in devices:
            device_type = str(device.get("type") or "")
            if (
                device_type not in CONTACT_DEVICE_TYPES
                or device.get("isActive") is False
            ):
                continue
            raw_code = str(device.get("code") or "")
            code = int(raw_code) if raw_code.isdigit() else 0
            zone_id = str(device.get("zoneId") or "")
            if not zone_id:
                zone_id = f"{device_type}{code:02d}" if code else str(device["id"])
            if zone_id in seen:
                continue
            seen.add(zone_id)
            result.append(
                ContactDevice(
                    id=str(device.get("id") or zone_id),
                    code=code,
                    zone_id=zone_id,
                    name=str(device.get("name") or zone_id),
                    device_type=device_type,
                )
            )
        return result

    async def get_contact_states(
        self, installation: Installation
    ) -> list[ContactState]:
        """Return the latest DSR magnetic states for an installation."""
        content = {
            "operationName": "xSGetDSRDevicesInfo",
            "variables": {"numinst": installation.number},
            "query": CONTACT_STATUS_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "xSGetDSRDevicesInfo",
            ContactStatusEnvelope,
            installation=installation,
        )
        return envelope.data.xSGetDSRDevicesInfo.devices or []
