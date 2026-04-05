"""Securitas Direct camera platform."""

import base64
import logging
from pathlib import Path
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, SIGNAL_CAMERA_STATE, SecuritasHub
from .coordinators import CameraCoordinator, CameraData
from .entity import camera_device_info
from .securitas_direct_new_api import Installation
from .securitas_direct_new_api.models import CameraDevice

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


class SecuritasCamera(CoordinatorEntity[CameraData], Camera):
    """A Securitas Direct camera entity showing the last captured image."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CameraCoordinator,
        hub: SecuritasHub,
        installation: Installation,
        camera_device: CameraDevice,
    ) -> None:
        """Initialize the camera entity."""
        super().__init__(coordinator)
        Camera.__init__(self)
        self._client = hub
        self._installation = installation
        self._camera_device = camera_device
        self._zone_id = camera_device.zone_id
        self._attr_unique_id = (
            f"v4_{installation.number}_camera_{camera_device.zone_id}"
        )
        self._attr_device_info = camera_device_info(installation, camera_device)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the last captured image, or a placeholder if none exists."""
        if self.coordinator.data is None:
            return _PLACEHOLDER_IMAGE
        thumb = self.coordinator.data.thumbnails.get(self._zone_id)
        if thumb is None or not thumb.image:
            return _PLACEHOLDER_IMAGE
        try:
            image_bytes = base64.b64decode(thumb.image)
        except (ValueError, TypeError):
            return _PLACEHOLDER_IMAGE
        if not image_bytes.startswith(b"\xff\xd8"):
            return _PLACEHOLDER_IMAGE
        return image_bytes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:  # type: ignore[override]
        """Return extra state attributes."""
        timestamp: str | None = None
        if self.coordinator.data is not None:
            thumb = self.coordinator.data.thumbnails.get(self._zone_id)
            if thumb is not None:
                timestamp = thumb.timestamp
        capturing = self._client.is_capturing(
            self._installation.number, self._camera_device.zone_id
        )
        return {"image_timestamp": timestamp, "capturing": capturing}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator — rotate token so frontend re-fetches."""
        self.async_update_token()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to camera state signal and set up coordinator listener."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CAMERA_STATE, self._handle_state)
        )

    @callback
    def _handle_state(self, installation_number: str, zone_id: str) -> None:
        """Handle capturing state change — write state without rotating token."""
        if (
            installation_number != self._installation.number
            or zone_id != self._camera_device.zone_id
        ):
            return
        self.async_write_ha_state()


class SecuritasCameraFull(CoordinatorEntity[CameraData], Camera):
    """A Securitas Direct camera entity showing the last full-resolution image."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CameraCoordinator,
        hub: SecuritasHub,
        installation: Installation,
        camera_device: CameraDevice,
    ) -> None:
        """Initialize the full-resolution camera entity."""
        super().__init__(coordinator)
        Camera.__init__(self)
        self._client = hub
        self._installation = installation
        self._camera_device = camera_device
        self._zone_id = camera_device.zone_id
        self._attr_unique_id = (
            f"v4_{installation.number}_camera_full_{camera_device.zone_id}"
        )
        self._attr_name = "Full Image"
        self._attr_device_info = camera_device_info(installation, camera_device)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the last full-resolution image, or a placeholder if none exists."""
        if self.coordinator.data is None:
            return _PLACEHOLDER_IMAGE
        image = self.coordinator.data.full_images.get(self._zone_id)
        return image if image is not None else _PLACEHOLDER_IMAGE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:  # type: ignore[override]
        """Return extra state attributes."""
        timestamp: str | None = None
        if self.coordinator.data is not None:
            thumb = self.coordinator.data.thumbnails.get(self._zone_id)
            if thumb is not None:
                timestamp = thumb.timestamp
        return {"image_timestamp": timestamp}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator — rotate token so frontend re-fetches."""
        self.async_update_token()
        self.async_write_ha_state()
