"""Verisure OWA binary sensor platform."""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, VerisureDevice
from .coordinators import AlarmCoordinator, ContactCoordinator
from .entity import securitas_device_info
from .verisure_owa_api import ContactDevice, Installation

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Verisure OWA binary sensor entities."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AlarmCoordinator = entry_data["alarm_coordinator"]
    securitas_devices: list[VerisureDevice] = entry_data["devices"]

    entities: list[BinarySensorEntity] = [
        WifiConnectedSensor(coordinator, device.installation)
        for device in securitas_devices
    ]
    async_add_entities(entities, False)

    # Contacts are discovered after platform setup so a transient Verisure
    # device-list failure cannot delay or prevent integration startup.
    entry_data["binary_sensor_add_entities"] = async_add_entities


class WifiConnectedSensor(  # type: ignore[override]
    CoordinatorEntity[AlarmCoordinator],
    BinarySensorEntity,
):
    """WiFi connection status from coordinator — no independent polling."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "WiFi Connected"
    _attr_should_poll = False

    def __init__(
        self, coordinator: AlarmCoordinator, installation: Installation
    ) -> None:
        super().__init__(coordinator)
        self._installation = installation
        self._attr_unique_id = (
            f"v4_securitas_direct.{installation.number}_wifi_connected"
        )
        self._attr_device_info = securitas_device_info(installation)

    @property
    def is_on(self) -> bool | None:  # type: ignore[override]
        """Return True if WiFi is connected."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.status.wifi_connected


class ContactOpeningSensor(  # type: ignore[override]
    CoordinatorEntity[ContactCoordinator],
    BinarySensorEntity,
):
    """Magnetic door/window contact exposed as an opening sensor."""

    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: ContactCoordinator,
        installation: Installation,
        contact: ContactDevice,
    ) -> None:
        super().__init__(coordinator)
        self._zone_id = contact.zone_id
        self._attr_name = contact.name
        self._attr_unique_id = (
            f"v4_securitas_direct.{installation.number}_contact_{contact.zone_id}"
        )
        self._attr_device_info = securitas_device_info(installation)

    @property
    def is_on(self) -> bool | None:  # type: ignore[override]
        """Return True when the magnetic contact reports open."""
        if self.coordinator.data is None:
            return None
        state = self.coordinator.data.states.get(self._zone_id)
        return state.is_open if state is not None else None
