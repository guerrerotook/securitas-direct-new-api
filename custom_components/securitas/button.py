"""Support for Securitas Direct refresh button."""
import asyncio
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CONF_INSTALLATION_KEY, DOMAIN, SecuritasDirectDevice, SecuritasHub
from .securitas_direct_new_api import CheckAlarmStatus, Installation, SecuritasDirectError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct Refresh Button based on config_entry."""
    client: SecuritasHub = hass.data[DOMAIN][SecuritasHub.__name__]
    buttons = []
    securitas_devices: list[SecuritasDirectDevice] = hass.data[DOMAIN].get(
        CONF_INSTALLATION_KEY
    )
    for device in securitas_devices:
        buttons.append(
            SecuritasRefreshButton(device.installation, client, hass)
        )
    async_add_entities(buttons, True)


class SecuritasRefreshButton(ButtonEntity):
    """Representation of a Securitas refresh button."""

    def __init__(
        self,
        installation: Installation,
        client: SecuritasHub,
        hass: HomeAssistant,
    ) -> None:
        """Initialize the refresh button."""
        self._attr_name = f"Refresh {installation.alias}"
        self._attr_unique_id = f"refresh_button_{installation.number}"
        self.installation = installation
        self.client = client
        self.hass = hass
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"securitas_direct.{installation.number}")},
            manufacturer="Securitas Direct",
            model=installation.panel,
            name=installation.alias,
            hw_version=installation.type,
        )

    async def async_press(self) -> None:
        """Update alarm status when button pressed."""
        try:
            reference_id = await self.client.session.check_alarm(self.installation)
            await asyncio.sleep(1)
            alarm_status = await self.client.session.check_alarm_status(self.installation, reference_id)
            
            self.client.session.protom_response = alarm_status.protomResponse
            
            _LOGGER.info("Status of the Alarm via API: %s installation id: %s", 
                       alarm_status.protomResponse, self.installation.number)
            
            _LOGGER.info("Update entity alarm panel securitas")
            for entity_id in self.hass.states.async_entity_ids("alarm_control_panel"):
                if "securitas" in entity_id or "alarm_control_panel" in entity_id:
                    await self.hass.services.async_call(
                        "homeassistant",
                        "update_entity",
                        {"entity_id": entity_id},
                        blocking=True
                    )
            
        except SecuritasDirectError as err:
            _LOGGER.error("Error calling the securitas direct API: %s", str(err))
        except Exception as ex:
            _LOGGER.error("Erreur inattendue: %s", str(ex))