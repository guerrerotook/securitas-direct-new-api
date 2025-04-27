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
            
            _LOGGER.info("Statut de l'alarme obtenu via API: %s pour l'installation %s", 
                       alarm_status.protomResponse, self.installation.number)
            
            # Méthode 1: Chercher l'entité d'alarme dans les devices CONF_INSTALLATION_KEY
            found_entity = False
            if CONF_INSTALLATION_KEY in self.hass.data.get(DOMAIN, {}):
                for device in self.hass.data[DOMAIN][CONF_INSTALLATION_KEY]:
                    if device.installation.number == self.installation.number:
                        # Trouvé le bon device, maintenant trouver l'entité associée
                        for entity_id in self.hass.states.async_entity_ids("alarm_control_panel"):
                            if f"securitas_direct.{device.installation.number}" in entity_id:
                                # Trouver l'entité à partir de son ID
                                alarm_entity = None
                                for component in self.hass.data.get("alarm_control_panel", {}).values():
                                    if hasattr(component, "entities"):
                                        for entity in component.entities:
                                            if entity.entity_id == entity_id:
                                                alarm_entity = entity
                                                break
                                
                                if alarm_entity:
                                    # Nous avons trouvé l'entité, mettre à jour son état
                                    _LOGGER.info("Entité d'alarme trouvée, mise à jour de son état")
                                    alarm_entity.update_status_alarm(alarm_status)
                                    alarm_entity.async_write_ha_state()
                                    found_entity = True
            
            # Méthode 2: Force une mise à jour de l'entité via set_arm_state
            if not found_entity:
                # Chercher dans tous les composants d'alarme
                alarm_entities = []
                for platform in self.hass.data.get("entity_component", {}).get("alarm_control_panel", {}).get("entities", []):
                    for entity in platform.entities:
                        if hasattr(entity, "installation") and entity.installation.number == self.installation.number:
                            alarm_entities.append(entity)
                
                if alarm_entities:
                    # Mettre à jour directement
                    for entity in alarm_entities:
                        _LOGGER.info("Mise à jour de l'entité d'alarme via set_arm_state")
                        # Déterminer le mode en fonction de protomResponse
                        current_mode = None
                        if alarm_status.protomResponse == "T":
                            current_mode = "ARMED_AWAY"
                        elif alarm_status.protomResponse == "D":
                            current_mode = "DISARMED"
                        elif alarm_status.protomResponse == "P":
                            current_mode = "ARMED_HOME"
                        elif alarm_status.protomResponse == "Q":
                            current_mode = "ARMED_NIGHT"
                        
                        if current_mode:
                            # Cette approche fonctionne car set_arm_state va mettre à jour l'entité
                            await entity.set_arm_state(current_mode)
                            found_entity = True
            
            # Méthode 3: Dernière tentative - force update_entity sur toutes les entités
            if not found_entity:
                _LOGGER.warning("Aucune entité correspondante trouvée par les méthodes directes, utilisation de update_entity")
                for entity_id in self.hass.states.async_entity_ids("alarm_control_panel"):
                    if "securitas" in entity_id:
                        await self.hass.services.async_call(
                            "homeassistant",
                            "update_entity",
                            {"entity_id": entity_id},
                            blocking=True
                        )
                # Enregistrer le status pour les futures mises à jour
                self.hass.data[f"{DOMAIN}_last_status_{self.installation.number}"] = alarm_status
                
        except SecuritasDirectError as err:
            _LOGGER.error("Erreur lors de la mise à jour du statut de l'alarme: %s", str(err))