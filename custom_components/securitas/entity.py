"""Shared base entity for Verisure OWA integration."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import DOMAIN
from .verisure_owa_api.models import CameraDevice, Installation

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .hub import VerisureHub
    from .verisure_owa_api.models import SmartLock


# `via_device` (the identifier-tuple form) is deprecated in HA 2026.8 and
# removed in 2027.8; its replacement is `via_device_id`, the parent device's
# registry id.  But `via_device_id` is only accepted by
# `async_get_or_create` — into which HA unpacks DeviceInfo — from 2026.8 on;
# on the older cores we still support (>= 2025.2) it raises TypeError.  Probe
# the real signature so one build works on both: the kwargs that method
# accepts are exactly what gates whether `via_device_id` is usable.
_SUPPORTS_VIA_DEVICE_ID: bool = (
    "via_device_id"
    in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters
)


def _link_to_installation(
    info: DeviceInfo,
    installation: Installation,
    hass: HomeAssistant | None,
    config_entry_id: str | None,
) -> None:
    """Point a child DeviceInfo at its installation parent, version-safely.

    On HA >= 2026.8 the deprecated `via_device` identifier tuple is replaced
    by `via_device_id`, resolved from the registry.  When the parent isn't
    registered yet (e.g. first setup, before the installation device exists)
    or its config-entry context is unavailable, we fall back to `via_device`
    so HA links the child exactly as before — no behaviour change. On older cores
    `via_device_id` isn't accepted, so `via_device` is always used.
    """
    parent = (DOMAIN, f"v4_securitas_direct.{installation.number}")
    if _SUPPORTS_VIA_DEVICE_ID and hass is not None and config_entry_id is not None:
        registry = dr.async_get(hass)
        get_device = getattr(registry, "async_get_device_by_identifier", None)
        if get_device is not None:
            device = get_device(parent, config_entry_id)
            if device is not None:
                info["via_device_id"] = device.id  # type: ignore[typeddict-unknown-key]
                return
    info["via_device"] = parent  # type: ignore[typeddict-unknown-key]


def securitas_device_info(installation: Installation) -> DeviceInfo:
    """Build DeviceInfo that groups entities under the installation device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"v4_securitas_direct.{installation.number}")},
        manufacturer="Verisure",
        model=installation.panel,
        name=installation.alias,
        hw_version=installation.type,
    )


def camera_device_info(
    installation: Installation,
    camera_device: CameraDevice,
    hass: HomeAssistant | None = None,
    *,
    config_entry_id: str | None = None,
) -> DeviceInfo:
    """Build DeviceInfo for a per-camera child device."""
    info = DeviceInfo(
        identifiers={
            (
                DOMAIN,
                f"v4_securitas_direct.{installation.number}_camera_{camera_device.zone_id}",
            )
        },
        name=camera_device.name,
        manufacturer="Verisure",
        model="Camera",
    )
    _link_to_installation(info, installation, hass, config_entry_id)
    return info


def lock_device_info(
    installation: Installation,
    device_id: str,
    name: str | None,
    lock_config: SmartLock | None,
    hass: HomeAssistant | None = None,
    *,
    config_entry_id: str | None = None,
) -> DeviceInfo:
    """Build DeviceInfo for a per-lock child device linked to the installation."""
    info = DeviceInfo(
        identifiers={
            (DOMAIN, f"v4_securitas_direct.{installation.number}_lock_{device_id}")
        },
        name=name,
        manufacturer="Verisure",
        model=lock_config.family if lock_config and lock_config.family else None,
        serial_number=(
            lock_config.serial_number
            if lock_config and lock_config.serial_number
            else None
        ),
    )
    _link_to_installation(info, installation, hass, config_entry_id)
    return info


class VerisureEntity(Entity):
    """Base class for Verisure OWA entities."""

    _attr_has_entity_name = False

    def __init__(
        self,
        installation: Installation,
        client: VerisureHub,
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
    def client(self) -> VerisureHub:
        """Return the client hub."""
        return self._client

    def _force_state(self, state: str | None) -> None:
        """Force entity state and schedule HA update."""
        self._last_state = self._state
        self._state = state
        if self.hass is not None:
            self.async_schedule_update_ha_state()
