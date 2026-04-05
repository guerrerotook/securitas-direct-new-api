"""Support for Securitas Direct refresh button."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, SecuritasDirectDevice, SecuritasHub
from .entity import SecuritasEntity, camera_device_info
from .securitas_direct_new_api import (
    Installation,
    SecuritasDirectError,
)
from .securitas_direct_new_api.models import CameraDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct Refresh Button based on config_entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    client: SecuritasHub = entry_data["hub"]
    buttons = []
    securitas_devices: list[SecuritasDirectDevice] = entry_data["devices"]
    for device in securitas_devices:
        buttons.append(
            SecuritasRefreshButton(device.installation, client, hass, entry.entry_id)
        )
    async_add_entities(buttons, True)

    # Store callback for deferred camera capture button discovery
    entry_data["button_add_entities"] = async_add_entities


class SecuritasRefreshButton(SecuritasEntity, ButtonEntity):
    """Representation of a Securitas refresh button."""

    def __init__(
        self,
        installation: Installation,
        client: SecuritasHub,
        hass: HomeAssistant,
        entry_id: str,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(installation, client)
        self._attr_name = f"Refresh {installation.alias}"
        self._attr_unique_id = f"v4_refresh_button_{installation.number}"
        self._entry_id = entry_id
        self.hass = hass

    async def async_press(self) -> None:
        """Request a coordinator refresh when button pressed."""
        if self.hass is None:
            return
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id)
        if entry_data is None:
            return
        alarm_coord = entry_data.get("alarm_coordinator")
        if alarm_coord is not None:
            await alarm_coord.async_request_refresh()


class SecuritasCaptureButton(SecuritasEntity, ButtonEntity):
    """Button to capture a new image from a Securitas camera."""

    _attr_icon = "mdi:camera"
    _attr_has_entity_name = True
    _attr_name = "Capture"

    def __init__(
        self,
        client: SecuritasHub,
        installation: Installation,
        camera_device: CameraDevice,
    ) -> None:
        """Initialize the capture button."""
        super().__init__(installation, client)
        self._camera_device = camera_device
        self._attr_unique_id = (
            f"v4_{installation.number}_capture_{camera_device.zone_id}"
        )
        self._attr_device_info = camera_device_info(installation, camera_device)

    async def async_press(self) -> None:
        """Request a new image capture."""
        try:
            await self._client.capture_image(self._installation, self._camera_device)
        except SecuritasDirectError as err:
            _LOGGER.warning(
                "Failed to capture image from %s: %s",
                self._camera_device.name,
                err,
            )
