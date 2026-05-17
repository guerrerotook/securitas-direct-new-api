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


def _is_broken_upgrade_slug(entity_id: str, alias_slug: str, middle: str) -> bool:
    """Return True when ``entity_id`` matches the known upgrade-path-broken slug.

    Heals exactly one pattern:
    ``alarm_control_panel.<alias_slug>_<middle>_<alias_slug>`` — the v5
    doubled-alias bug where HA slugified the friendly name
    ``<Middle> - <alias>`` and prepended the device name, ending up with the
    alias twice. ``middle`` is ``"main"`` for the combined panel and the
    circuit name (``"interior"`` / ``"perimeter"`` / ``"annex"``) for the axis
    sub-panels.

    A ``<canonical>_<N>`` collision-suffix heal used to exist for the v4→v5
    upgrade scenario where a stale v4 entity squatted on the canonical slot.
    That window has closed, and matching ``_<N>`` had a false-positive failure
    mode: two installations sharing an alias legitimately produce
    ``<canonical>_<N>`` for the second one, which is NOT broken. Anything
    other than the doubled-alias pattern is treated as user customization (or
    a legitimate collision) and left alone.
    """
    return entity_id == f"alarm_control_panel.{alias_slug}_{middle}_{alias_slug}"


async def _heal_combined_panel_entity_id(
    hass: HomeAssistant, installation: Installation
) -> None:
    """Move the combined alarm panel onto its canonical entity_id slot.

    The canonical slot is ``alarm_control_panel.<slugified-alias>`` (matching
    the v4 layout). Earlier v5 builds slugified the friendly name
    ``Main - <alias>`` and ended up at ``alarm_control_panel.<alias>_main_<alias>``;
    a downgrade-then-re-upgrade leaves a stale entity squatting on the
    canonical slot which pushes the new entity to ``_2``.

    Also rewrites the ``deleted_entities`` tombstone if one is present with
    a known-broken entity_id, so a delete/re-add cycle doesn't reintroduce
    a stale slug from HA's ``async_get_or_create`` restoration path.

    The healer is **pattern-precise** — it only relocates entity_ids matching
    the two known-broken patterns enumerated in ``_is_broken_upgrade_slug``.
    Anything else (notably entity_ids the user renamed via HA's UI) is treated
    as user customization and left where it is.

    This helper:

    1. Finds the entity registered under our v5 unique_id for this installation.
    2. If it is already at the canonical slot, returns.
    3. If its current entity_id is NOT a known-broken pattern, returns
       (user-customized slug, do not touch).
    4. If the canonical slot is held by another verisure_owa entity (an orphan
       from a previous setup), removes the orphan to free the slot.
    5. Renames our entity into the canonical slot.

    A non-verisure_owa entity holding the slot is left untouched (we log a
    warning and skip the rename).
    """
    try:
        ent_reg = er.async_get(hass)
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # heal is best-effort; never fail setup
        return
    our_unique_id = f"v4_securitas_direct.{installation.number}"
    alias_slug = slugify(installation.alias)
    canonical = f"alarm_control_panel.{alias_slug}"

    _rewrite_tombstone_entity_id(ent_reg, our_unique_id, canonical, alias_slug, "main")

    try:
        our_entity_id = ent_reg.async_get_entity_id(
            "alarm_control_panel", DOMAIN, our_unique_id
        )
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        return
    if our_entity_id is None or our_entity_id == canonical:
        return
    if not _is_broken_upgrade_slug(our_entity_id, alias_slug, "main"):
        # User-customized entity_id — leave it alone.
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

    Also rewrites the ``deleted_entities`` tombstone if one is present with
    the broken entity_id: HA's ``async_get_or_create`` restores a removed
    entity onto its previous ``entity_id`` (bypassing ``suggested_object_id``
    entirely), so deleting and re-adding a sub-panel that had the doubled
    slug would otherwise re-introduce it on every cycle until a subsequent
    HA restart triggered the healer.

    ``suffix`` is the unique_id suffix used by the sub-panel (e.g.
    ``"_interior"``); the canonical entity_id slug is the bare alias slug with
    the same suffix appended.
    """
    try:
        ent_reg = er.async_get(hass)
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # heal is best-effort; never fail setup
        return
    our_unique_id = f"v4_securitas_direct.{installation.number}{suffix}"
    alias_slug = slugify(installation.alias)
    canonical = f"alarm_control_panel.{alias_slug}{suffix}"
    circuit = suffix.lstrip("_")

    # Rewrite the tombstone first — if the entity is also live (a partial
    # state where both exist on different ids), the live-rename below picks
    # up the canonical slot afterwards.
    _rewrite_tombstone_entity_id(ent_reg, our_unique_id, canonical, alias_slug, circuit)

    try:
        our_entity_id = ent_reg.async_get_entity_id(
            "alarm_control_panel", DOMAIN, our_unique_id
        )
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        return
    if our_entity_id is None or our_entity_id == canonical:
        return
    if not _is_broken_upgrade_slug(our_entity_id, alias_slug, circuit):
        # User-customized sub-panel entity_id — leave it alone.
        return

    occupant = ent_reg.async_get(canonical)
    if occupant is not None and occupant.entity_id != our_entity_id:
        # Skip rather than evict: unlike the combined panel (which has a
        # v4 legacy to displace), sub-panels are v5-only and there is no
        # known stale-squatter scenario worth evicting for. The occupant
        # is most likely another installation that happens to share the
        # alias slug, and removing it would silently delete that
        # installation's sub-panel.
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


def _rewrite_tombstone_entity_id(
    ent_reg: er.EntityRegistry,
    unique_id: str,
    canonical: str,
    alias_slug: str,
    middle: str,
) -> None:
    """Rewrite a known-broken ``entity_id`` on a deleted-entity tombstone.

    HA stores deleted entities in ``ent_reg.deleted_entities`` so that user
    customisations (area, name, options) survive a delete/re-add cycle. On
    re-add ``async_get_or_create`` pops the tombstone and restores its
    ``entity_id`` directly — ignoring the entity's ``suggested_object_id``.

    For alarm panels removed from a pre-healer install, the tombstone's
    entity_id is the broken ``<alias>_main_<alias>`` /
    ``<alias>_<circuit>_<alias>`` form. Rewrite it to canonical here
    (preserving every other field) so the next re-add lands on the correct
    slot from the first registration, not after a follow-up restart's
    healer pass.

    Only rewrites when the tombstone's entity_id matches a known upgrade-path-
    broken pattern (see ``_is_broken_upgrade_slug``). A tombstone holding a
    user-customized entity_id is left untouched so a delete/re-add cycle
    preserves the user's chosen slug.
    """
    import attr

    deleted = getattr(ent_reg, "deleted_entities", None)
    if deleted is None:
        return
    key = ("alarm_control_panel", DOMAIN, unique_id)
    tombstone = deleted.get(key)
    if tombstone is None or tombstone.entity_id == canonical:
        return
    if not _is_broken_upgrade_slug(tombstone.entity_id, alias_slug, middle):
        return
    _LOGGER.info(
        "Rewriting deleted alarm-panel tombstone: %s -> %s",
        tombstone.entity_id,
        canonical,
    )
    deleted[key] = attr.evolve(tombstone, entity_id=canonical)


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
    # verisure_owa.refresh_alarm (the v5+ supersession of the deprecated
    # VerisureRefreshButton) is registered globally in __init__.py via
    # register_v5_entity_services — it dispatches to this platform's
    # entities' async_manual_refresh method.
