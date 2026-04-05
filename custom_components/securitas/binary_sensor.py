"""Securitas Direct binary sensor platform."""

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

from . import DOMAIN, SecuritasDirectDevice
from .coordinators import AlarmCoordinator, AlarmStatusData
from .entity import securitas_device_info
from .securitas_direct_new_api import Installation

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct binary sensor entities."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AlarmCoordinator = entry_data["alarm_coordinator"]
    securitas_devices: list[SecuritasDirectDevice] = entry_data["devices"]

    entities: list[BinarySensorEntity] = [
        WifiConnectedSensor(coordinator, device.installation)
        for device in securitas_devices
    ]
    async_add_entities(entities, False)


class WifiConnectedSensor(CoordinatorEntity[AlarmStatusData], BinarySensorEntity):
    """WiFi connection status from coordinator — no independent polling."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(
        self, coordinator: AlarmCoordinator, installation: Installation
    ) -> None:
        super().__init__(coordinator)
        self._installation = installation
        self._attr_unique_id = f"v4_{installation.number}_wifi_connected"
        self._attr_name = f"{installation.alias} WiFi Connected"
        self._attr_device_info = securitas_device_info(installation)

    @property
    def is_on(self) -> bool | None:
        """Return True if WiFi is connected."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.status.wifi_connected
