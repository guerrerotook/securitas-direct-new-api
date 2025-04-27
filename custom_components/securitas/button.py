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
        # Utiliser le même identifiant d'appareil que celui du panneau d'alarme
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
            # Obtenir un nouveau référence_id pour forcer une mise à jour complète
            reference_id = await self.client.session.check_alarm(self.installation)
            # Court délai pour laisser le temps à l'API de traiter la demande
            await asyncio.sleep(1)
            # Récupérer le statut de l'alarme avec le nouveau référence_id
            alarm_status = await self.client.session.check_alarm_status(self.installation, reference_id)
            
            # Mettre à jour le statut dans l'API
            self.client.session.protom_response = alarm_status.protomResponse
            
            _LOGGER.info("Statut de l'alarme obtenu via API: %s pour l'installation %s", 
                       alarm_status.protomResponse, self.installation.number)
            
            # Méthode 1: Accéder directement aux entités d'alarme via le registre d'entités
            from homeassistant.helpers import entity_registry as er
            alarm_entity_id = f"alarm_control_panel.securitas_direct_{self.installation.number}"
            
            # Trouver l'entité dans le registre
            entity_registry = er.async_get(self.hass)
            entity_entry = None
            
            for entity_id, entry in entity_registry.entities.items():
                if entity_id.endswith(self.installation.number) and "securitas" in entity_id:
                    entity_entry = entry
                    _LOGGER.debug("Entité trouvée dans le registre: %s", entity_id)
                    break
            
            if entity_entry:
                # Trouver l'entité réelle à partir de l'entrée du registre
                from homeassistant.helpers.entity_component import EntityComponent
                alarm_component = self.hass.data.get("entity_component", {}).get("alarm_control_panel")
                
                if alarm_component and hasattr(alarm_component, "entities"):
                    for entity in alarm_component.entities:
                        if entity.entity_id == entity_entry.entity_id:
                            _LOGGER.info("Entité trouvée, mise à jour directe")
                            # Mise à jour directe de l'entité en appelant la fonction qui met à jour l'état
                            if hasattr(entity, "update_status_alarm"):
                                entity.update_status_alarm(alarm_status)
                                entity.async_write_ha_state()
                                return
            
            # Méthode 2: Chercher directement dans les données du domaine
            _LOGGER.info("Recherche directe dans les données du domaine")
            if DOMAIN in self.hass.data:
                domain_data = self.hass.data[DOMAIN]
                if "entities" in domain_data:
                    for entity in domain_data["entities"]:
                        if hasattr(entity, "installation") and entity.installation.number == self.installation.number:
                            _LOGGER.info("Entité trouvée dans les données du domaine")
                            entity.update_status_alarm(alarm_status)
                            entity.async_write_ha_state()
                            return
            
            # Méthode 3: Force l'actualisation de l'état par le service securitas.refresh_alarm_status
            # Nous savons que ce service existe et fonctionne avec l'identifiant de l'installation
            _LOGGER.info("Appel du service refresh_alarm_status")
            await self.hass.services.async_call(
                DOMAIN,
                "refresh_alarm_status",
                {"instalation_id": int(self.installation.number)},
                blocking=True
            )
            
            # En dernier recours, mettre à jour toutes les entités d'alarme
            _LOGGER.info("En dernier recours, mise à jour de toutes les entités d'alarme")
            for entity_id in self.hass.states.async_entity_ids("alarm_control_panel"):
                if "securitas" in entity_id or "alarm_control_panel" in entity_id:
                    await self.hass.services.async_call(
                        "homeassistant",
                        "update_entity",
                        {"entity_id": entity_id},
                        blocking=True
                    )
            
        except SecuritasDirectError as err:
            _LOGGER.error("Erreur lors de la mise à jour du statut de l'alarme: %s", str(err))
        except Exception as ex:
            _LOGGER.error("Erreur inattendue: %s", str(ex))