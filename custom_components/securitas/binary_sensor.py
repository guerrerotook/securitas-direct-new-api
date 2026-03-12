"""Securitas Direct binary sensor platform."""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, SIGNAL_XSSTATUS_UPDATE, SecuritasDirectDevice, SecuritasHub
from .entity import SecuritasEntity
from .securitas_direct_new_api import Installation

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct binary sensor entities."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    client: SecuritasHub = entry_data["hub"]
    securitas_devices: list[SecuritasDirectDevice] = entry_data["devices"]

    entities: list[BinarySensorEntity] = [
        WifiConnectedSensor(client, device.installation) for device in securitas_devices
    ]
    async_add_entities(entities, False)


class WifiConnectedSensor(SecuritasEntity, BinarySensorEntity):
    """WiFi connection status from xSStatus — updated via dispatcher, no polling."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, client: SecuritasHub, installation: Installation) -> None:
        super().__init__(installation, client)
        self._attr_unique_id = f"v4_{installation.number}_wifi_connected"
        self._attr_name = f"{installation.alias} WiFi Connected"

    async def async_added_to_hass(self) -> None:
        """Register dispatcher listener."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_XSSTATUS_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self, installation_number: str) -> None:
        """Handle xSStatus update."""
        if installation_number != self._installation.number:
            return
        status = self._client.xsstatus.get(self._installation.number)
        if status and status.wifi_connected is not None:
            self._attr_is_on = status.wifi_connected
            self.async_write_ha_state()
