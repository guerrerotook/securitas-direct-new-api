"""Securitas Direct WiFi connectivity diagnostic sensor."""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CONF_INSTALLATION_KEY, DOMAIN, SecuritasDirectDevice, SecuritasHub
from .securitas_direct_new_api import Installation, SecuritasDirectError, SStatus

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct diagnostic binary sensors."""
    client: SecuritasHub = hass.data[DOMAIN][SecuritasHub.__name__]
    entities = []
    securitas_devices: list[SecuritasDirectDevice] = hass.data[DOMAIN].get(
        CONF_INSTALLATION_KEY
    )
    for device in securitas_devices:
        try:
            status: SStatus = await client.session.check_general_status(
                device.installation
            )
        except SecuritasDirectError:
            _LOGGER.warning(
                "Could not get diagnostic data for installation %s",
                device.installation.number,
            )
            continue

        if status.wifi_connected is not None:
            entities.append(
                SecuritasWifiConnected(device.installation, client, status)
            )

    if entities:
        async_add_entities(entities, True)


class SecuritasWifiConnected(BinarySensorEntity):
    """WiFi connectivity diagnostic sensor."""

    def __init__(
        self,
        installation: Installation,
        client: SecuritasHub,
        status: SStatus,
    ) -> None:
        self._attr_name = f"WiFi {installation.alias}"
        self._attr_unique_id = f"securitas_direct.{installation.number}_wifi_connected"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._installation = installation
        self._client = client
        self._attr_is_on = status.wifi_connected
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"securitas_direct.{installation.number}")},
            manufacturer="Securitas Direct",
            model=installation.panel,
            name=installation.alias,
            hw_version=installation.type,
        )

    async def async_update(self) -> None:
        try:
            status = await self._client.session.check_general_status(
                self._installation
            )
            self._attr_is_on = status.wifi_connected
        except SecuritasDirectError as err:
            _LOGGER.error("Error updating WiFi status: %s", err)
