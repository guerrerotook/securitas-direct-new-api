"""Support for Verisure OWA refresh and capture buttons."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, VerisureDevice, VerisureHub, _async_notify
from .entity import VerisureEntity, camera_device_info
from .events import inject_ha_event
from .verisure_owa_api import (
    Installation,
    VerisureOwaError,
)
from .verisure_owa_api.exceptions import OperationTimeoutError
from .verisure_owa_api.models import ActivityCategory, CameraDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Verisure OWA Refresh Button based on config_entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    client: VerisureHub = entry_data["hub"]
    buttons = []
    securitas_devices: list[VerisureDevice] = entry_data["devices"]
    for device in securitas_devices:
        buttons.append(
            VerisureRefreshButton(device.installation, client, hass, entry.entry_id)
        )
    async_add_entities(buttons, True)

    # Store callback for deferred camera capture button discovery
    entry_data["button_add_entities"] = async_add_entities


class VerisureRefreshButton(VerisureEntity, ButtonEntity):
    """Representation of a Verisure OWA refresh button."""

    _attr_has_entity_name = True
    _attr_name = "Refresh"

    def __init__(
        self,
        installation: Installation,
        client: VerisureHub,
        hass: HomeAssistant,
        entry_id: str,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(installation, client)
        self._attr_unique_id = f"v5_verisure_owa.{installation.number}_refresh_button"
        self._entry_id = entry_id
        self.hass = hass

    def _get_alarm_entity(self):
        """Return the alarm entity for this installation, if available."""
        alarm_entities = self.hass.data.get(DOMAIN, {}).get("alarm_entities", {})
        return alarm_entities.get(self._installation.number)

    async def async_press(self) -> None:
        """Full alarm status refresh via CheckAlarm + poll.

        This triggers an authoritative round-trip with the panel, not just
        a lightweight xSStatus read.
        """
        if self.hass is None:
            return
        try:
            alarm_status = await self._client.refresh_alarm_status(self._installation)

            self._client.client.protom_response = alarm_status.protom_response

            _LOGGER.info(
                "Status of the Alarm via API: %s installation id: %s",
                alarm_status.protom_response,
                self._installation.number,
            )

            alarm_entity = self._get_alarm_entity()
            if alarm_entity is not None:
                alarm_entity._set_refresh_failed(False)  # noqa: SLF001  # pylint: disable=protected-access
                alarm_entity.async_write_ha_state()
                alarm_entity.async_schedule_update_ha_state(force_refresh=True)

        except OperationTimeoutError:
            _LOGGER.warning("Refresh timed out for %s", self._installation.number)
            alarm_entity = self._get_alarm_entity()
            if alarm_entity is not None:
                alarm_entity._set_refresh_failed(True)  # noqa: SLF001  # pylint: disable=protected-access
                alarm_entity.async_write_ha_state()

        except VerisureOwaError as err:
            _LOGGER.error(
                "Error refreshing alarm status for %s: %s",
                self._installation.number,
                err.log_detail(),
            )
            if getattr(err, "http_status", None) == 403:
                await _async_notify(
                    self.hass,
                    f"rate_limited_{self._installation.number}",
                    "rate_limited",
                )
                alarm_entity = self._get_alarm_entity()
                if alarm_entity is not None:
                    alarm_entity._set_waf_blocked(True)  # noqa: SLF001  # pylint: disable=protected-access
                    alarm_entity.async_write_ha_state()


class VerisureCaptureButton(VerisureEntity, ButtonEntity):
    """Button to capture a new image from a Verisure camera."""

    _attr_icon = "mdi:camera"
    _attr_has_entity_name = True
    _attr_name = "Capture"

    def __init__(
        self,
        client: VerisureHub,
        installation: Installation,
        camera_device: CameraDevice,
    ) -> None:
        """Initialize the capture button."""
        super().__init__(installation, client)
        self._camera_device = camera_device
        self._attr_unique_id = (
            f"v5_verisure_owa.{installation.number}_capture_{camera_device.zone_id}"
        )
        self._attr_device_info = camera_device_info(installation, camera_device)

    async def async_press(self) -> None:
        """Request a new image capture."""
        # Capture the calling user's context up-front — HA expires
        # `self._context` ~1 s after async_set_context.
        user_context = self._context
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
        # Use the real server-side ids (when available) so the card's
        # follow-up xSGetPhotoImages fetch resolves to this capture.
        id_signal = thumbnail.id_signal if thumbnail else None
        signal_type = thumbnail.signal_type if thumbnail else None
        await inject_ha_event(
            self.hass,
            self._installation,
            category=ActivityCategory.IMAGE_REQUEST,
            alias="Image request",
            device=self._camera_device.zone_id,
            device_name=self._camera_device.name,
            context=user_context,
            id_signal=id_signal,
            signal_type=signal_type,
        )
