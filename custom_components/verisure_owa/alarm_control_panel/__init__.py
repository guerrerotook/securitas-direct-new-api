"""Support for Verisure OWA alarm control panels.

The platform's HA-facing entry point ``async_setup_entry`` lives here.
The actual entity classes are split across two private modules so the
file is easier to navigate:

- ``_base.py`` — ``BaseVerisureOwaAlarmPanel``: coordinator integration,
  arm/disarm flow, force-arm context, arming-exception notifications.
- ``_panels.py`` — concrete panels: combined household panel and the
  three single-axis sub-panels (Interior, Perimeter, Annex).
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CODE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)

from .. import DOMAIN, VerisureDevice, VerisureHub
from ..const import (
    CONF_ENABLE_ANNEX_PANEL,
    CONF_ENABLE_INTERIOR_PANEL,
    CONF_ENABLE_PERIMETER_PANEL,
)
from ..coordinators import AlarmCoordinator
from ._base import BaseVerisureOwaAlarmPanel
from ._panels import (
    AnnexVerisureOwaAlarmPanel,
    CombinedVerisureOwaAlarmPanel,
    InteriorVerisureOwaAlarmPanel,
    PerimeterVerisureOwaAlarmPanel,
)

__all__ = [
    "AnnexVerisureOwaAlarmPanel",
    "BaseVerisureOwaAlarmPanel",
    "CombinedVerisureOwaAlarmPanel",
    "InteriorVerisureOwaAlarmPanel",
    "PerimeterVerisureOwaAlarmPanel",
    "async_setup_entry",
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Verisure OWA alarm entities based on config_entry.

    No API calls are made here.  Entities start with unknown state;
    the coordinator drives periodic updates.
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    client: VerisureHub = entry_data["hub"]
    coordinator: AlarmCoordinator = entry_data["alarm_coordinator"]
    options = entry.options

    enable_peri: bool = options.get(CONF_ENABLE_PERIMETER_PANEL, False)
    enable_annex: bool = options.get(CONF_ENABLE_ANNEX_PANEL, False)
    enable_interior: bool = options.get(CONF_ENABLE_INTERIOR_PANEL, False)

    alarms: list[CombinedVerisureOwaAlarmPanel] = []
    all_entities: list[BaseVerisureOwaAlarmPanel] = []
    securitas_devices: list[VerisureDevice] = entry_data["devices"]
    for devices in securitas_devices:
        combined = CombinedVerisureOwaAlarmPanel(
            devices.installation,
            client=client,
            hass=hass,
            coordinator=coordinator,
        )
        alarms.append(combined)
        all_entities.append(combined)

        # Saved toggles are the source of truth — the options flow already
        # gates each toggle on capability, so a saved toggle implies the
        # capability was supported at config time. Don't gate entity creation
        # on coordinator.has_peri/has_annex here: a transient capability-
        # detection failure at startup (e.g. get_services 5xx) would otherwise
        # permanently hide opted-in entities until the user reloads, even
        # after the coordinator's later background refresh succeeds.
        if enable_peri:
            all_entities.append(
                PerimeterVerisureOwaAlarmPanel(
                    devices.installation,
                    client=client,
                    hass=hass,
                    coordinator=coordinator,
                )
            )

        if enable_annex:
            all_entities.append(
                AnnexVerisureOwaAlarmPanel(
                    devices.installation,
                    client=client,
                    hass=hass,
                    coordinator=coordinator,
                )
            )

        if enable_interior:
            all_entities.append(
                InteriorVerisureOwaAlarmPanel(
                    devices.installation,
                    client=client,
                    hass=hass,
                    coordinator=coordinator,
                )
            )

    async_add_entities(all_entities, False)
    hass.data[DOMAIN]["alarm_entities"] = {a.installation.number: a for a in alarms}

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "force_arm",
        {vol.Optional(CONF_CODE): cv.string},
        "async_force_arm",
    )
    platform.async_register_entity_service(
        "force_arm_cancel",
        {},
        "async_force_arm_cancel",
    )
