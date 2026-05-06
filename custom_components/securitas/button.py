"""Support for Securitas Direct refresh button."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, SecuritasDirectDevice, SecuritasHub, _async_notify
from .entity import SecuritasEntity, camera_device_info
from .events import inject_ha_event
from .securitas_direct_new_api import (
    Installation,
    SecuritasDirectError,
)
from .securitas_direct_new_api.exceptions import OperationTimeoutError
from .securitas_direct_new_api.models import ActivityCategory, CameraDevice

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

        except SecuritasDirectError as err:
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
        # Capture the calling user's context up-front — HA expires
        # `self._context` ~1 s after async_set_context.
        user_context = self._context
        try:
            await self._client.capture_image(self._installation, self._camera_device)
        except SecuritasDirectError as err:
            _LOGGER.warning(
                "Failed to capture image from %s: %s",
                self._camera_device.name,
                err,
            )
            return
        await inject_ha_event(
            self.hass,
            self._installation,
            category=ActivityCategory.IMAGE_REQUEST,
            alias="Image request",
            device=self._camera_device.zone_id,
            device_name=self._camera_device.name,
            context=user_context,
        )
