"""Shared base entity for Securitas Direct integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import DOMAIN
from .securitas_direct_new_api.models import CameraDevice, Installation

if TYPE_CHECKING:
    from .hub import SecuritasHub


def securitas_device_info(installation: Installation) -> DeviceInfo:
    """Build DeviceInfo that groups entities under the installation device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"v4_securitas_direct.{installation.number}")},
        manufacturer="Securitas Direct",
        model=installation.panel,
        name=installation.alias,
        hw_version=installation.type,
    )


def camera_device_info(
    installation: Installation, camera_device: CameraDevice
) -> DeviceInfo:
    """Build DeviceInfo for a per-camera child device."""
    return DeviceInfo(
        identifiers={
            (
                DOMAIN,
                f"v4_securitas_direct.{installation.number}_camera_{camera_device.zone_id}",
            )
        },
        name=camera_device.name,
        manufacturer="Securitas Direct",
        model="Camera",
        via_device=(DOMAIN, f"v4_securitas_direct.{installation.number}"),
    )


class SecuritasEntity(Entity):
    """Base class for Securitas Direct entities."""

    _attr_has_entity_name = False

    def __init__(
        self,
        installation: Installation,
        client: SecuritasHub,
    ) -> None:
        """Initialize common entity attributes."""
        self._installation = installation
        self._client = client
        self._attr_device_info = securitas_device_info(installation)
        self._state: str | None = None
        self._last_state: str | None = None

    @property
    def installation(self) -> Installation:
        """Return the installation."""
        return self._installation

    @property
    def client(self) -> SecuritasHub:
        """Return the client hub."""
        return self._client

    def _force_state(self, state: str | None) -> None:
        """Force entity state and schedule HA update."""
        self._last_state = self._state
        self._state = state
        if self.hass is not None:
            self.async_schedule_update_ha_state()

