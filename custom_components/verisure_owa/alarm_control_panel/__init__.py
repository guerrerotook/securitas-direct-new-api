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

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CODE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.util import slugify

from .. import DOMAIN, VerisureDevice, VerisureHub
from ..const import (
    CONF_ENABLE_ANNEX_PANEL,
    CONF_ENABLE_INTERIOR_PANEL,
    CONF_ENABLE_PERIMETER_PANEL,
)
from ..coordinators import AlarmCoordinator
from ..verisure_owa_api.models import Installation
from ._base import BaseVerisureOwaAlarmPanel, build_partial_disarm_target
from ._panels import (
    AnnexVerisureOwaAlarmPanel,
    CombinedVerisureOwaAlarmPanel,
    InteriorVerisureOwaAlarmPanel,
    PerimeterVerisureOwaAlarmPanel,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "AnnexVerisureOwaAlarmPanel",
    "BaseVerisureOwaAlarmPanel",
    "CombinedVerisureOwaAlarmPanel",
    "InteriorVerisureOwaAlarmPanel",
    "PerimeterVerisureOwaAlarmPanel",
    "_heal_combined_panel_entity_id",
    "_heal_subpanel_entity_id",
    "async_setup_entry",
    "build_partial_disarm_target",
]


async def _heal_combined_panel_entity_id(
    hass: HomeAssistant, installation: Installation
) -> None:
    """Move the combined alarm panel onto its canonical entity_id slot.

    The canonical slot is ``alarm_control_panel.<slugified-alias>`` (matching
    the v4 layout). Earlier v5 builds slugified the friendly name
    ``Main - <alias>`` and ended up at ``alarm_control_panel.<alias>_main_<alias>``;
    a downgrade-then-re-upgrade leaves a stale entity squatting on the
    canonical slot which pushes the new entity to ``_2``. This helper:

    1. Finds the entity registered under our v5 unique_id for this installation.
    2. If it is already at the canonical slot, returns.
    3. If the canonical slot is held by another verisure_owa entity (an orphan
       from a previous setup), removes the orphan to free the slot.
    4. Renames our entity into the canonical slot.

    A non-verisure_owa entity holding the slot is left untouched (we log a
    warning and skip the rename).
    """
    try:
        ent_reg = er.async_get(hass)
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # heal is best-effort; never fail setup
        return
    our_unique_id = f"v5_verisure_owa.{installation.number}"
    try:
        our_entity_id = ent_reg.async_get_entity_id(
            "alarm_control_panel", DOMAIN, our_unique_id
        )
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        return
    if our_entity_id is None:
        return
    canonical = f"alarm_control_panel.{slugify(installation.alias)}"
    if our_entity_id == canonical:
        return

    occupant = ent_reg.async_get(canonical)
    if occupant is not None and occupant.entity_id != our_entity_id:
        if occupant.platform == DOMAIN:
            _LOGGER.warning(
                "Removing stale alarm-panel entity %s (unique_id=%s) so "
                "installation %s can reclaim its canonical entity_id",
                canonical,
                occupant.unique_id,
                installation.number,
            )
            ent_reg.async_remove(canonical)
        else:
            _LOGGER.warning(
                "Cannot reclaim %s for installation %s: slot held by %s "
                "(domain %s); the alarm panel will stay at %s",
                canonical,
                installation.number,
                occupant.unique_id,
                occupant.platform,
                our_entity_id,
            )
            return

    _LOGGER.info("Renaming alarm-panel entity_id: %s -> %s", our_entity_id, canonical)
    ent_reg.async_update_entity(our_entity_id, new_entity_id=canonical)


async def _heal_subpanel_entity_id(
    hass: HomeAssistant, installation: Installation, suffix: str
) -> None:
    """Move a sub-panel onto its canonical ``<alias>_<circuit>`` slot.

    Counterpart to ``_heal_combined_panel_entity_id`` for the axis sub-panels.
    Without the ``suggested_object_id`` override now defined on each sub-panel,
    HA slugified the friendly name ``<circuit> - <alias>`` with the device
    name prepended and ended up at ``<alias>_<circuit>_<alias>``. Existing
    installs that enabled a sub-panel before the fix carry the broken slot in
    their registry; this helper relocates them to ``<alias>_<circuit>``.

    ``suffix`` is the unique_id suffix used by the sub-panel (e.g.
    ``"_interior"``); the canonical entity_id slug is the bare alias slug with
    the same suffix appended.
    """
    try:
        ent_reg = er.async_get(hass)
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # heal is best-effort; never fail setup
        return
    our_unique_id = f"v5_verisure_owa.{installation.number}{suffix}"
    try:
        our_entity_id = ent_reg.async_get_entity_id(
            "alarm_control_panel", DOMAIN, our_unique_id
        )
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        return
    if our_entity_id is None:
        return
    canonical = f"alarm_control_panel.{slugify(installation.alias)}{suffix}"
    if our_entity_id == canonical:
        return

    occupant = ent_reg.async_get(canonical)
    if occupant is not None and occupant.entity_id != our_entity_id:
        if occupant.platform == DOMAIN:
            _LOGGER.warning(
                "Removing stale alarm-subpanel entity %s (unique_id=%s) so "
                "installation %s can reclaim its canonical entity_id",
                canonical,
                occupant.unique_id,
                installation.number,
            )
            ent_reg.async_remove(canonical)
        else:
            _LOGGER.warning(
                "Cannot reclaim %s for installation %s: slot held by %s "
                "(domain %s); the sub-panel will stay at %s",
                canonical,
                installation.number,
                occupant.unique_id,
                occupant.platform,
                our_entity_id,
            )
            return

    _LOGGER.info(
        "Renaming alarm-subpanel entity_id: %s -> %s", our_entity_id, canonical
    )
    ent_reg.async_update_entity(our_entity_id, new_entity_id=canonical)


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
    # Reclaim the canonical alarm_control_panel.<alias> entity_id for the
    # combined panel before the platform creates its entities, so an upgrade
    # path that left a stale `<alias>_main_<alias>` or `_2`-suffixed slug in
    # the registry is healed transparently.
    for devices in securitas_devices:
        await _heal_combined_panel_entity_id(hass, devices.installation)
        # Sub-panels carry the same bug: ``<alias>_<circuit>_<alias>`` from
        # builds that registered them before the suggested_object_id fix.
        # Run unconditionally — if no broken (or any) entity exists for a
        # circuit the helper returns immediately.
        for suffix in ("_interior", "_perimeter", "_annex"):
            await _heal_subpanel_entity_id(hass, devices.installation, suffix)

    for devices in securitas_devices:
        combined = CombinedVerisureOwaAlarmPanel(
            devices.installation,
            client=client,
            hass=hass,
            coordinator=coordinator,
        )
        entry_data.setdefault("combined_alarm_panels", {})[
            devices.installation.number
        ] = combined
        alarms.append(combined)
        all_entities.append(combined)

        # Saved toggles are the source of truth — the options flow already
        # gates each toggle on capability, so a saved toggle implies the
        # capability was supported at config time. Don't gate entity creation
        # on coordinator.has_peri/has_annex here: a transient capability-
        # detection failure at startup (e.g. get_services 5xx) would otherwise
        # permanently hide opted-in entities until the user reloads, even
        # after the coordinator's later background refresh succeeds.
        axis_panels = entry_data.setdefault("axis_alarm_panels", {}).setdefault(
            devices.installation.number, {}
        )
        if enable_peri:
            peri_panel = PerimeterVerisureOwaAlarmPanel(
                devices.installation,
                client=client,
                hass=hass,
                coordinator=coordinator,
            )
            all_entities.append(peri_panel)
            axis_panels[peri_panel._AXIS] = peri_panel  # noqa: SLF001  # pylint: disable=protected-access

        if enable_annex:
            annex_panel = AnnexVerisureOwaAlarmPanel(
                devices.installation,
                client=client,
                hass=hass,
                coordinator=coordinator,
            )
            all_entities.append(annex_panel)
            axis_panels[annex_panel._AXIS] = annex_panel  # noqa: SLF001  # pylint: disable=protected-access

        if enable_interior:
            interior_panel = InteriorVerisureOwaAlarmPanel(
                devices.installation,
                client=client,
                hass=hass,
                coordinator=coordinator,
            )
            all_entities.append(interior_panel)
            axis_panels[interior_panel._AXIS] = interior_panel  # noqa: SLF001  # pylint: disable=protected-access

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
