"""Securitas Direct camera platform."""

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, SIGNAL_CAMERA_STATE, SIGNAL_CAMERA_UPDATE, SecuritasHub
from .entity import camera_device_info
from .securitas_direct_new_api import Installation
from .securitas_direct_new_api.dataTypes import CameraDevice

_LOGGER = logging.getLogger(__name__)

_PLACEHOLDER_IMAGE = (Path(__file__).parent / "placeholder.jpg").read_bytes()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct camera entities.

    No API calls are made here.  Camera devices are discovered
    asynchronously after startup and added via the stored callback.
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    entry_data["camera_add_entities"] = async_add_entities


class SecuritasCamera(Camera):
    """A Securitas Direct camera entity showing the last captured image."""

    _attr_should_poll = False

    def __init__(
        self,
        client: SecuritasHub,
        installation: Installation,
        camera_device: CameraDevice,
    ) -> None:
        """Initialize the camera entity."""
        super().__init__()
        self._client = client
        self._installation = installation
        self._camera_device = camera_device
        self._attr_unique_id = (
            f"v4_{installation.number}_camera_{camera_device.zone_id}"
        )
        self._attr_name = f"{installation.alias} {camera_device.name}"
        self._attr_device_info = camera_device_info(installation, camera_device)
        self._initial_fetch_done = False

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the last captured image, or a placeholder if none exists."""
        # Lazy-fetch the latest thumbnail on first request from the frontend
        if not self._initial_fetch_done:
            self._initial_fetch_done = True
            await self._client.fetch_latest_thumbnail(
                self._installation, self._camera_device
            )
        image = self._client.get_camera_image(
            self._installation.number, self._camera_device.zone_id
        )
        return image if image is not None else _PLACEHOLDER_IMAGE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:  # type: ignore[override]
        """Return extra state attributes."""
        timestamp = self._client.get_camera_timestamp(
            self._installation.number, self._camera_device.zone_id
        )
        capturing = self._client.is_capturing(
            self._installation.number, self._camera_device.zone_id
        )
        return {"image_timestamp": timestamp, "capturing": capturing}

    async def async_added_to_hass(self) -> None:
        """Subscribe to camera update signals."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CAMERA_UPDATE, self._handle_update
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CAMERA_STATE, self._handle_state)
        )

    @callback
    def _handle_update(self, installation_number: str, zone_id: str) -> None:
        """Handle new image availability — rotate token so frontend re-fetches."""
        if (
            installation_number != self._installation.number
            or zone_id != self._camera_device.zone_id
        ):
            return
        # Rotate the access token so the frontend knows the image changed
        # and re-fetches from the proxy endpoint.
        self.async_update_token()
        self.async_write_ha_state()

    @callback
    def _handle_state(self, installation_number: str, zone_id: str) -> None:
        """Handle capturing state change — write state without rotating token."""
        if (
            installation_number != self._installation.number
            or zone_id != self._camera_device.zone_id
        ):
            return
        self.async_write_ha_state()
