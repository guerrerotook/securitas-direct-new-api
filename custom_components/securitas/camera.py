"""Verisure OWA camera platform."""

import asyncio
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

from . import DOMAIN, SIGNAL_CAMERA_STATE, VerisureHub
from .coordinators import CameraCoordinator
from .entity import camera_device_info
from .events import inject_ha_event
from .verisure_owa_api import Installation
from .verisure_owa_api.exceptions import VerisureOwaError
from .verisure_owa_api.models import ActivityCategory, CameraDevice

_LOGGER = logging.getLogger(__name__)

_PLACEHOLDER_IMAGE_PATH = Path(__file__).parent / "placeholder.jpg"
# Cache for the placeholder JPEG bytes — populated on first access via the
# event loop's executor to avoid sync file I/O during integration startup.
_PLACEHOLDER_IMAGE: bytes | None = None
_placeholder_lock: asyncio.Lock | None = None


async def _get_placeholder_image(hass: HomeAssistant) -> bytes:
    """Return the placeholder JPEG, reading the file once via the executor."""
    global _PLACEHOLDER_IMAGE, _placeholder_lock  # pylint: disable=global-statement
    cached = _PLACEHOLDER_IMAGE
    if cached is not None:
        return cached
    if _placeholder_lock is None:
        _placeholder_lock = asyncio.Lock()
    async with _placeholder_lock:
        if _PLACEHOLDER_IMAGE is None:
            loaded: bytes = await hass.async_add_executor_job(
                _PLACEHOLDER_IMAGE_PATH.read_bytes
            )
            _PLACEHOLDER_IMAGE = loaded
            return loaded
        return _PLACEHOLDER_IMAGE


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Verisure OWA camera entities.

    No API calls are made here.  Camera devices are discovered
    asynchronously after startup and added via the stored callback.
    The verisure_owa.capture_image entity service is registered
    globally in __init__.py via register_v5_entity_services — it
    dispatches to this platform's entities' async_manual_capture method.
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    entry_data["camera_add_entities"] = async_add_entities


class VerisureCamera(CoordinatorEntity[CameraCoordinator], Camera):
    """A Verisure OWA camera entity.

    Subclass-controlled mode: `_mode = "thumbnail"` reads
    `coordinator.data.thumbnails` and exposes the `capturing` state attribute
    plus a SIGNAL_CAMERA_STATE listener; `_mode = "full"` reads
    `coordinator.data.full_images` instead.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _mode: str = "thumbnail"

    def __init__(
        self,
        coordinator: CameraCoordinator,
        hub: VerisureHub,
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
        suffix = "_full" if self._mode == "full" else ""
        self._attr_unique_id = (
            f"v4_securitas_direct.{installation.number}"
            f"_camera{suffix}_{camera_device.zone_id}"
        )
        if self._mode == "full":
            self._attr_name = "Full Image"
        self._attr_device_info = camera_device_info(installation, camera_device)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the relevant image for this mode, or a placeholder."""
        if self.coordinator.data is None:
            return await _get_placeholder_image(self.hass)
        if self._mode == "full":
            image = self.coordinator.data.full_images.get(self._zone_id)
            if image is None:
                return await _get_placeholder_image(self.hass)
            return image
        thumb = self.coordinator.data.thumbnails.get(self._zone_id)
        if thumb is None or not thumb.image:
            return await _get_placeholder_image(self.hass)
        try:
            image_bytes = base64.b64decode(thumb.image)
        except (ValueError, TypeError):
            return await _get_placeholder_image(self.hass)
        if not image_bytes.startswith(b"\xff\xd8"):
            return await _get_placeholder_image(self.hass)
        return image_bytes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:  # type: ignore[override]
        """Return extra state attributes."""
        timestamp: str | None = None
        if self.coordinator.data is not None:
            thumb = self.coordinator.data.thumbnails.get(self._zone_id)
            if thumb is not None:
                timestamp = thumb.timestamp
        attrs: dict[str, Any] = {"image_timestamp": timestamp}
        if self._mode == "thumbnail":
            attrs["capturing"] = self._client.is_capturing(
                self._installation.number, self._camera_device.zone_id
            )
        return attrs

    async def async_manual_capture(self) -> None:
        """Request a new image capture and inject the activity event.

        Backs both the `verisure_owa.capture_image` entity service and the
        deprecated VerisureCaptureButton.  Errors from the hub layer are
        swallowed (already logged there) — we just skip the event injection.
        """
        try:
            _, thumbnail = await self._client.capture_image(
                self._installation, self._camera_device
            )
        except VerisureOwaError as err:
            _LOGGER.warning(
                "Failed to capture image from %s: %s",
                self._camera_device.name,
                err,
            )
            return
        id_signal = thumbnail.id_signal if thumbnail else None
        signal_type = thumbnail.signal_type if thumbnail else None
        await inject_ha_event(
            self.hass,
            self._installation,
            category=ActivityCategory.IMAGE_REQUEST,
            alias="Image request",
            device=self._camera_device.zone_id,
            device_name=self._camera_device.name,
            context=self._context,
            id_signal=id_signal,
            signal_type=signal_type,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator — rotate token so frontend re-fetches."""
        self.async_update_token()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to camera state signal (thumbnail mode only)."""
        await super().async_added_to_hass()
        if self._mode == "thumbnail":
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass, SIGNAL_CAMERA_STATE, self._handle_state
                )
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


class VerisureCameraFull(VerisureCamera):
    """Full-resolution variant of VerisureCamera."""

    _mode = "full"
