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
        self._attr_name = f"Rafraîchir {installation.alias}"
        self._attr_unique_id = f"refresh_button_{installation.number}"
        self.installation = installation
        self.client = client
        self.hass = hass
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{installation.alias}")},
            manufacturer="Securitas Direct",
            model=installation.panel,
            name=installation.alias,
        )

    async def async_press(self) -> None:
        """Update alarm status when button pressed."""
        try:
            # Obtenir un nouveau référence_id pour forcer une mise à jour complète
            reference_id = await self.client.session.check_alarm(self.installation)
            # Court délai pour laisser le temps à l'API de traiter la demande
            await asyncio.sleep(1)
            # Récupérer le statut de l'alarme avec le nouveau référence_id
            alarm_status = await self.client.session.check_alarm_status(self.installation, reference_id)
            
            # Mettre à jour le statut dans l'API
            self.client.session.protom_response = alarm_status.protomResponse
            
            _LOGGER.info("Statut de l'alarme obtenu avec succès pour l'installation %s: %s", 
                       self.installation.number, alarm_status.protomResponse)
                       
            # Rechercher toutes les entités d'alarme qui pourraient correspondre à notre installation
            found_entity = False
            
            # Méthode 1: Vérifier les entités dans le domaine
            if DOMAIN in self.hass.data:
                for device_key, device_data in self.hass.data.get(DOMAIN, {}).items():
                    if hasattr(device_data, "update_status_alarm") and hasattr(device_data, "installation"):
                        if device_data.installation.number == self.installation.number:
                            _LOGGER.debug("Entité d'alarme trouvée via domaine: %s", device_key)
                            device_data.update_status_alarm(alarm_status)
                            device_data.async_write_ha_state()
                            found_entity = True
                            _LOGGER.info("État de l'entité d'alarme mis à jour directement via domaine")
            
            # Méthode 2: Essayer de trouver l'entité par son ID
            alarm_entity_id = f"securitas_direct.{self.installation.number}"
            if not found_entity and self.hass.states.get(alarm_entity_id) is not None:
                # Trouver l'entité dans le registre des entités
                from homeassistant.helpers import entity_registry as er
                entity_registry = er.async_get(self.hass)
                
                for entity_id, entity_entry in entity_registry.entities.items():
                    if entity_id == alarm_entity_id or f"securitas_direct_{self.installation.number}" in entity_id:
                        # Essayer de forcer une mise à jour
                        await self.hass.services.async_call(
                            "homeassistant",
                            "update_entity",
                            {"entity_id": entity_id},
                            blocking=True
                        )
                        found_entity = True
                        _LOGGER.info("Essai de mise à jour de l'entité via update_entity: %s", entity_id)
            
            # Méthode 3: Forcer une mise à jour de toutes les entités d'alarme
            if not found_entity:
                for entity_id in self.hass.states.async_entity_ids("alarm_control_panel"):
                    if "securitas" in entity_id:
                        await self.hass.services.async_call(
                            "homeassistant",
                            "update_entity",
                            {"entity_id": entity_id},
                            blocking=True
                        )
                        _LOGGER.info("Forçage de la mise à jour de toutes les entités d'alarme Securitas: %s", entity_id)
                
                # Envoyer un événement pour que d'autres composants puissent réagir
                self.hass.bus.async_fire(f"{DOMAIN}_alarm_updated", {
                    "installation_id": self.installation.number,
                    "status": alarm_status.protomResponse
                })
                
        except SecuritasDirectError as err:
            _LOGGER.error("Erreur lors de la mise à jour du statut de l'alarme: %s", str(err))