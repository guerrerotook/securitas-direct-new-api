"""Support for Verisure OWA refresh and capture buttons (both deprecated).

These button entities are kept so existing automations and Lovelace
button cards continue to work.  New code paths (cards, services) use
the `verisure_owa.refresh_alarm` and `verisure_owa.capture_image`
entity services on the alarm panel / camera entities directly.
"""

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, VerisureDevice, VerisureHub
from .entity import VerisureEntity, camera_device_info
from .verisure_owa_api import Installation
from .verisure_owa_api.models import CameraDevice

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
    """Verisure OWA refresh button — DEPRECATED.

    Superseded by the ``verisure_owa.refresh_alarm`` entity service on
    the alarm panel entity, which the alarm card now calls directly.
    Kept so existing automations and Lovelace button cards continue to
    work; will be removed in a future release.
    """

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
        self._attr_unique_id = (
            f"v4_securitas_direct.{installation.number}_refresh_button"
        )
        self._entry_id = entry_id
        self.hass = hass

    def _get_alarm_entity(self):
        """Return the alarm entity for this installation, if available."""
        alarm_entities = self.hass.data.get(DOMAIN, {}).get("alarm_entities", {})
        return alarm_entities.get(self._installation.number)

    async def async_press(self) -> None:
        """Delegate to the alarm panel's async_manual_refresh.

        Logs a one-line deprecation notice; automations and button cards
        that still call ``button.press`` continue to work.
        """
        _LOGGER.warning(
            "%s: button.press is deprecated — call "
            "verisure_owa.refresh_alarm on the alarm_control_panel "
            "entity instead.  This button will be removed in a future release.",
            self.entity_id or self._attr_unique_id,
        )
        if self.hass is None:
            return
        alarm_entity = self._get_alarm_entity()
        if alarm_entity is None:
            return
        # Surface the button's HA context to the alarm entity so the
        # downstream inject_ha_event call attributes the action to the
        # user who pressed the button.
        alarm_entity.async_set_context(self._context)
        await alarm_entity.async_manual_refresh()


class VerisureCaptureButton(VerisureEntity, ButtonEntity):
    """Capture button for a Verisure camera — DEPRECATED.

    Superseded by the ``verisure_owa.capture_image`` entity service on
    the camera entity, which the camera card now calls directly.
    Kept so existing automations and Lovelace button cards continue to
    work; will be removed in a future release.
    """

    _attr_icon = "mdi:camera"
    _attr_has_entity_name = True
    _attr_name = "Capture"

    def __init__(
        self,
        client: VerisureHub,
        installation: Installation,
        camera_device: CameraDevice,
        *,
        camera_entity: Any | None = None,
    ) -> None:
        """Initialize the capture button.

        ``camera_entity`` is the matching VerisureCamera (thumbnail mode)
        the button delegates to.  Optional only so legacy tests that
        instantiate the button without one continue to work — production
        wiring in discovery.py always supplies it.
        """
        super().__init__(installation, client)
        self._camera_device = camera_device
        self._camera_entity = camera_entity
        self._attr_unique_id = (
            f"v4_securitas_direct.{installation.number}_capture_{camera_device.zone_id}"
        )
        self._attr_device_info = camera_device_info(installation, camera_device)

    async def async_press(self) -> None:
        """Delegate to the camera entity's async_manual_capture."""
        _LOGGER.warning(
            "%s: button.press is deprecated — call "
            "verisure_owa.capture_image on the camera entity instead.  "
            "This button will be removed in a future release.",
            self.entity_id or self._attr_unique_id,
        )
        if self._camera_entity is None:
            return
        self._camera_entity.async_set_context(self._context)
        await self._camera_entity.async_manual_capture()
