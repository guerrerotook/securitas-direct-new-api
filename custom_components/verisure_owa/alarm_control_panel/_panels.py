"""Combined and per-axis Verisure OWA alarm panels.

The Combined panel drives all three axes (interior/perimeter/annex) via
the user's HA-state mappings, while the sub-panels (Interior, Perimeter,
Annex) project the coordinator's joint state onto a single axis and
preserve the others when computing target states.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntityFeature,  # type: ignore[attr-defined]
)
from homeassistant.components.alarm_control_panel.const import AlarmControlPanelState

from ..const import (
    CIRCUIT_ANNEX,
    CIRCUIT_INTERIOR,
    CIRCUIT_PERIMETER,
    DOMAIN,
)
from ..coordinators import AlarmStatusData
from ..verisure_owa_api import (
    OperationStatus,
    VerisureOwaError,
    VerisureOwaState,
    is_proto_letter,
)
from ..verisure_owa_api.command_resolver import (
    AlarmState,
    AnnexMode,
    InteriorMode,
    PerimeterMode,
    PROTO_TO_ALARM_STATE,
    VERISURE_OWA_STATE_TO_ALARM_STATE,
)
from ._base import BaseVerisureOwaAlarmPanel, build_partial_disarm_target

_LOGGER = logging.getLogger(__name__)


class CombinedVerisureOwaAlarmPanel(BaseVerisureOwaAlarmPanel):
    """The household-intent panel — drives all three axes via the user's
    HA-state-to-VerisureOwaState mapping configured in options."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_name = f"Main - {self._installation.alias}"

    @property
    def suggested_object_id(self) -> str:
        """Force the entity_id slug to ``<alias>``, matching the v4 layout.

        With ``has_entity_name = False`` the default would slugify the friendly
        name ``Main - <alias>`` and produce ``main_<alias>``, which both
        breaks v4 dashboards and (when an old entity already occupies that
        name) lands on the doubled-alias collision form. Returning the bare
        installation alias here is what HA seeds the entity_id from on first
        registration.
        """
        return self._installation.alias

    def _resolve_target_state(self, ha_state: str) -> AlarmState:
        """Convert an HA alarm mode to an AlarmState using the verisure state map."""
        if ha_state == AlarmControlPanelState.DISARMED:
            return VERISURE_OWA_STATE_TO_ALARM_STATE[VerisureOwaState.DISARMED]
        securitas_state = self._securitas_state_map.get(ha_state)
        if securitas_state is None:
            raise VerisureOwaError(f"Unsupported alarm mode: {ha_state}")
        return VERISURE_OWA_STATE_TO_ALARM_STATE[securitas_state]

    def _extract_state(self, joint_state: AlarmState) -> AlarmControlPanelState | None:
        """For the combined panel, map joint state back to HA via user mappings."""
        for ha_state, sec_state in self._securitas_state_map.items():
            if VERISURE_OWA_STATE_TO_ALARM_STATE.get(sec_state) == joint_state:
                try:
                    return AlarmControlPanelState(ha_state)
                except ValueError:
                    return None
        return None

    async def execute_partial_disarm(self, circuits: list[str]) -> bool:
        """Disarm the specified circuits, leaving others unchanged.

        Returns True on success, False on VerisureOwaError. Empty
        ``circuits`` is a no-op success.

        Drives the same optimistic-state lifecycle as a user-initiated disarm
        on each affected entity (this combined panel + any registered axis
        sub-panel for the listed circuits): DISARMING during the transition,
        post-result state on success, rollback on failure. Concludes with a
        coordinator refresh so other observers don't have to wait for the
        next poll to see the change.
        """
        if not circuits:
            return True
        current = self.coordinator.alarm_state
        target = build_partial_disarm_target(current, circuits)
        if target == current:
            return True

        affected = [self, *self._affected_axis_subpanels(circuits)]
        for entity in affected:
            entity._operation_in_progress = True  # noqa: SLF001  # pylint: disable=protected-access
            entity._operation_epoch += 1  # noqa: SLF001  # pylint: disable=protected-access
            entity._force_state(AlarmControlPanelState.DISARMING)  # noqa: SLF001  # pylint: disable=protected-access
        try:
            result = await self._execute_transition(target)
        except VerisureOwaError as err:
            for entity in affected:
                entity._state = entity._last_state  # noqa: SLF001  # pylint: disable=protected-access
                entity._operation_in_progress = False  # noqa: SLF001  # pylint: disable=protected-access
                entity.async_write_ha_state()
            _LOGGER.error(
                "Partial disarm failed for %s circuits %s: %s",
                self._installation.number,
                circuits,
                err.log_detail(),
            )
            return False
        for entity in affected:
            entity.update_status_alarm(result)
            entity._operation_in_progress = False  # noqa: SLF001  # pylint: disable=protected-access
            entity.async_write_ha_state()
        await self.coordinator.async_request_refresh()
        return True

    def _affected_axis_subpanels(
        self, circuits: list[str]
    ) -> list[BaseVerisureOwaAlarmPanel]:
        """Look up registered sub-panel entities matching the given circuits.

        Returns an empty list when there is no entry_data registration (test
        contexts) or when the circuits don't map to any active sub-panel.
        """
        if self.hass is None:
            return []
        config_entry = getattr(self._client, "config_entry", None)
        entry_id = getattr(config_entry, "entry_id", None)
        if entry_id is None:
            return []
        domain_data = self.hass.data.get(DOMAIN, {})
        entry_data = domain_data.get(entry_id)
        if not isinstance(entry_data, dict):
            return []
        axis_panels = entry_data.get("axis_alarm_panels", {}).get(
            self._installation.number, {}
        )
        return [axis_panels[c] for c in circuits if c in axis_panels]


class _AxisSubPanelMixin:
    """Mixin that routes state updates through _extract_state(joint_state).

    Sub-panels override _extract_state() to project the coordinator's joint
    AlarmState onto a single axis.  The base-class _update_from_coordinator()
    and update_status_alarm() use _status_map (the combined-panel user-mapping)
    which is wrong for axis sub-panels.  This mixin replaces both paths.
    """

    # Sub-panels don't expose user-editable state mappings, so a
    # panel-rejected command can't be worked around in options — the
    # right action is to drop the feature and tell the user it's been
    # disabled. The Main panel keeps the default (True) and points users
    # at the mappings UI instead.
    _is_mappable: bool = False

    @property
    def suggested_object_id(self) -> str:
        """Force the entity_id slug to ``<alias>_<circuit>`` on fresh installs.

        ``_SUFFIX`` is the *unique-id* suffix (``_interior`` / ``_perimeter``
        / ``_annex``) — kept as-is so existing registry entries keep the same
        unique_id. The *display* slug returned here uses a **space**
        separator (``"<alias> interior"``), not the unique-id underscore, for
        the HA 2026.5+ entity-registry path:

        HA 2026.5 unconditionally prepends the device name onto the
        registry's ``object_id_base`` for entities with
        ``has_entity_name=False``, then runs a strip-prefix heuristic to
        avoid doubling. That heuristic only recognises space/dash/colon as
        the separator following the matched prefix — an underscore between
        ``<alias>`` and ``_<circuit>`` is not stripped, so the device name
        ends up prepended twice and the entity_id comes out as
        ``alarm_control_panel.<alias>_<alias>_<circuit>`` (the
        "doubled-alias collision form"). Returning a space-separated value
        here keeps the heuristic happy and produces the canonical
        ``alarm_control_panel.<alias>_<circuit>`` after HA's own slugify
        pass. The same value still works on HA < 2026.5 (which never
        prepends the device name when ``has_entity_name=False``) because
        slugify maps space → ``_`` in either case.

        The ``_heal_subpanel_entity_id`` helper relocates already-broken
        entries on existing installs that got the underscore-form slug
        before this fix landed.
        """
        circuit = self._SUFFIX.lstrip("_")  # type: ignore[attr-defined]
        return f"{self._installation.alias} {circuit}"  # type: ignore[attr-defined]

    def _update_from_coordinator(self, data: AlarmStatusData) -> None:  # type: ignore[override]
        """Project the coordinator's joint state onto this panel's axis.

        Stores any well-formed proto code (single uppercase letter) so that the
        refuse-on-unknown-state gate in _execute_transition fires for codes we
        don't yet model.  For codes we do model, also project the coordinator's
        joint state onto this axis; unknown codes preserve the previous _state
        because coordinator.alarm_state defaults to all-OFF for them, which
        would otherwise make the sub-panel silently report DISARMED while the
        system is actually armed.
        """
        # Refresh resolver capabilities — they may have been populated late.
        self._resolver.update_capabilities(  # type: ignore[attr-defined]
            has_peri=self.coordinator.has_peri  # type: ignore[attr-defined]
        )
        status = data.status
        if not status.status:
            return
        proto_code = status.status
        if not is_proto_letter(proto_code):
            return
        self._last_proto_code = proto_code  # type: ignore[attr-defined]
        if proto_code not in PROTO_TO_ALARM_STATE:
            return
        joint = self.coordinator.alarm_state  # type: ignore[attr-defined]
        self._state = self._extract_state(joint)  # type: ignore[attr-defined]

    def update_status_alarm(  # type: ignore[override]
        self, status: OperationStatus | None = None
    ) -> None:
        """Update state after an arm/disarm operation using the joint-state projection."""
        if not self._store_operation_status_metadata(status):  # type: ignore[attr-defined]
            return
        assert status is not None  # narrowed by _store_operation_status_metadata
        # The coordinator hasn't refreshed yet at this point, so reconstruct the
        # AlarmState from the proto code; if unknown, fall back to the (stale)
        # coordinator joint state to preserve the most recent known projection.
        joint = PROTO_TO_ALARM_STATE.get(
            status.protom_response,
            self.coordinator.alarm_state,  # type: ignore[attr-defined]
        )
        self._state = self._extract_state(joint)  # type: ignore[attr-defined]


class InteriorVerisureOwaAlarmPanel(_AxisSubPanelMixin, BaseVerisureOwaAlarmPanel):
    """Sub-panel driving only the interior axis.

    Capabilities (ARMDAY, ARMNIGHT, ARM) gate which HA states are exposed.
    The perimeter and annex axes are preserved from the coordinator's current
    joint state when computing target states.
    """

    _SUFFIX = "_interior"
    _AXIS = CIRCUIT_INTERIOR

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_unique_id = f"{self._attr_unique_id}{self._SUFFIX}"
        self._attr_name = f"Interior - {self._installation.alias}"

    @property
    def supported_features(self) -> AlarmControlPanelEntityFeature:  # type: ignore[override]
        """Return interior arming features, minus any the panel has rejected.

        We deliberately do NOT gate on the JWT capability set: empirically (Italian
        SDVECU OWNER) the JWT 'cap' claim can be both incomplete and wrong about
        which arming commands the panel accepts — e.g. claiming ARMNIGHT while
        the panel rejects ARMNIGHT1 with "not valid for Central Unit", and
        omitting ARMDAY while the panel happily accepts ARMDAY1. Gating on the
        cap set therefore hides modes that work and exposes modes that don't.

        Instead we start with all three interior modes and remove ones whose
        underlying command has been rejected at runtime (via
        ``resolver.mark_unsupported``). The rejection set is hydrated from
        persisted state on setup, so a mode disabled once stays disabled
        across HA restarts.
        """
        features = AlarmControlPanelEntityFeature(0)
        if self._resolver.can_reach_interior(InteriorMode.DAY):
            features |= AlarmControlPanelEntityFeature.ARM_HOME
        if self._resolver.can_reach_interior(InteriorMode.NIGHT):
            features |= AlarmControlPanelEntityFeature.ARM_NIGHT
        if self._resolver.can_reach_interior(InteriorMode.TOTAL):
            features |= AlarmControlPanelEntityFeature.ARM_AWAY
        return features

    def _resolve_target_state(self, ha_state: str) -> AlarmState:
        """Map an HA state to a target AlarmState that touches only the interior axis."""
        interior_target_map: dict[str, InteriorMode] = {
            AlarmControlPanelState.ARMED_HOME: InteriorMode.DAY,
            AlarmControlPanelState.ARMED_NIGHT: InteriorMode.NIGHT,
            AlarmControlPanelState.ARMED_AWAY: InteriorMode.TOTAL,
            AlarmControlPanelState.DISARMED: InteriorMode.OFF,
        }
        if ha_state not in interior_target_map:
            raise VerisureOwaError(
                f"Unsupported alarm mode for Interior panel: {ha_state}"
            )
        current = self.coordinator.alarm_state
        return AlarmState(
            interior=interior_target_map[ha_state],
            perimeter=current.perimeter,
            annex=current.annex,
        )

    def _extract_state(self, joint_state: AlarmState) -> AlarmControlPanelState | None:
        """Project the joint state onto the interior axis only."""
        mapping = {
            InteriorMode.OFF: AlarmControlPanelState.DISARMED,
            InteriorMode.DAY: AlarmControlPanelState.ARMED_HOME,
            InteriorMode.NIGHT: AlarmControlPanelState.ARMED_NIGHT,
            InteriorMode.TOTAL: AlarmControlPanelState.ARMED_AWAY,
        }
        return mapping.get(joint_state.interior)


class PerimeterVerisureOwaAlarmPanel(_AxisSubPanelMixin, BaseVerisureOwaAlarmPanel):
    """Sub-panel driving only the perimeter axis.

    Perimeter is binary (ON/OFF). The interior and annex axes are preserved
    from the coordinator's current joint state when computing target states.
    """

    _SUFFIX = "_perimeter"
    _AXIS = CIRCUIT_PERIMETER

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_unique_id = f"{self._attr_unique_id}{self._SUFFIX}"
        self._attr_name = f"Perimeter - {self._installation.alias}"

    @property
    def supported_features(self) -> AlarmControlPanelEntityFeature:  # type: ignore[override]
        """Return supported features for perimeter (binary axis, ARM_AWAY only)."""
        return AlarmControlPanelEntityFeature.ARM_AWAY

    def _resolve_target_state(self, ha_state: str) -> AlarmState:
        """Map an HA state to a target AlarmState that touches only the perimeter axis."""
        perimeter_target_map: dict[str, PerimeterMode] = {
            AlarmControlPanelState.ARMED_AWAY: PerimeterMode.ON,
            AlarmControlPanelState.DISARMED: PerimeterMode.OFF,
        }
        if ha_state not in perimeter_target_map:
            raise VerisureOwaError(
                f"Unsupported alarm mode for Perimeter panel: {ha_state}"
            )
        current = self.coordinator.alarm_state
        return AlarmState(
            interior=current.interior,
            perimeter=perimeter_target_map[ha_state],
            annex=current.annex,
        )

    def _extract_state(self, joint_state: AlarmState) -> AlarmControlPanelState | None:
        """Project the joint state onto the perimeter axis only."""
        mapping = {
            PerimeterMode.OFF: AlarmControlPanelState.DISARMED,
            PerimeterMode.ON: AlarmControlPanelState.ARMED_AWAY,
        }
        return mapping.get(joint_state.perimeter)


class AnnexVerisureOwaAlarmPanel(_AxisSubPanelMixin, BaseVerisureOwaAlarmPanel):
    """Sub-panel driving only the annex axis.

    Annex is binary (ON/OFF). The interior and perimeter axes are preserved
    from the coordinator's current joint state when computing target states.
    """

    _SUFFIX = "_annex"
    _AXIS = CIRCUIT_ANNEX

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_unique_id = f"{self._attr_unique_id}{self._SUFFIX}"
        self._attr_name = f"Annex - {self._installation.alias}"

    @property
    def supported_features(self) -> AlarmControlPanelEntityFeature:  # type: ignore[override]
        """Return supported features for annex (binary axis, ARM_AWAY only)."""
        return AlarmControlPanelEntityFeature.ARM_AWAY

    def _resolve_target_state(self, ha_state: str) -> AlarmState:
        """Map an HA state to a target AlarmState that touches only the annex axis."""
        annex_target_map: dict[str, AnnexMode] = {
            AlarmControlPanelState.ARMED_AWAY: AnnexMode.ON,
            AlarmControlPanelState.DISARMED: AnnexMode.OFF,
        }
        if ha_state not in annex_target_map:
            raise VerisureOwaError(
                f"Unsupported alarm mode for Annex panel: {ha_state}"
            )
        current = self.coordinator.alarm_state
        return AlarmState(
            interior=current.interior,
            perimeter=current.perimeter,
            annex=annex_target_map[ha_state],
        )

    def _extract_state(self, joint_state: AlarmState) -> AlarmControlPanelState | None:
        """Project the joint state onto the annex axis only."""
        mapping = {
            AnnexMode.OFF: AlarmControlPanelState.DISARMED,
            AnnexMode.ON: AlarmControlPanelState.ARMED_AWAY,
        }
        return mapping.get(joint_state.annex)
