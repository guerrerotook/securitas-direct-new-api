"""Command resolver for Securitas alarm state transitions.

Models alarm state as two independent axes (interior mode + perimeter)
and resolves transitions into command sequences with runtime fallback
discovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .const import SecuritasState


class InteriorMode(StrEnum):
    """Interior alarm mode."""

    OFF = "off"
    DAY = "day"
    NIGHT = "night"
    TOTAL = "total"


class PerimeterMode(StrEnum):
    """Perimeter alarm mode."""

    OFF = "off"
    ON = "on"


@dataclass(frozen=True)
class AlarmState:
    """Two-axis alarm state: interior mode + perimeter on/off."""

    interior: InteriorMode
    perimeter: PerimeterMode


# Proto response code -> AlarmState
PROTO_TO_ALARM_STATE: dict[str, AlarmState] = {
    "D": AlarmState(InteriorMode.OFF, PerimeterMode.OFF),
    "P": AlarmState(InteriorMode.DAY, PerimeterMode.OFF),
    "Q": AlarmState(InteriorMode.NIGHT, PerimeterMode.OFF),
    "T": AlarmState(InteriorMode.TOTAL, PerimeterMode.OFF),
    "E": AlarmState(InteriorMode.OFF, PerimeterMode.ON),
    "B": AlarmState(InteriorMode.DAY, PerimeterMode.ON),
    "C": AlarmState(InteriorMode.NIGHT, PerimeterMode.ON),
    "A": AlarmState(InteriorMode.TOTAL, PerimeterMode.ON),
}

# AlarmState -> proto response code
ALARM_STATE_TO_PROTO: dict[AlarmState, str] = {
    v: k for k, v in PROTO_TO_ALARM_STATE.items()
}

# SecuritasState (config/UI) -> AlarmState (resolver)
SECURITAS_STATE_TO_ALARM_STATE: dict[SecuritasState, AlarmState] = {
    SecuritasState.DISARMED: AlarmState(InteriorMode.OFF, PerimeterMode.OFF),
    SecuritasState.PARTIAL_DAY: AlarmState(InteriorMode.DAY, PerimeterMode.OFF),
    SecuritasState.PARTIAL_NIGHT: AlarmState(InteriorMode.NIGHT, PerimeterMode.OFF),
    SecuritasState.TOTAL: AlarmState(InteriorMode.TOTAL, PerimeterMode.OFF),
    SecuritasState.PERI_ONLY: AlarmState(InteriorMode.OFF, PerimeterMode.ON),
    SecuritasState.PARTIAL_DAY_PERI: AlarmState(InteriorMode.DAY, PerimeterMode.ON),
    SecuritasState.PARTIAL_NIGHT_PERI: AlarmState(InteriorMode.NIGHT, PerimeterMode.ON),
    SecuritasState.TOTAL_PERI: AlarmState(InteriorMode.TOTAL, PerimeterMode.ON),
}


@dataclass
class CommandStep:
    """A single logical operation with ordered command alternatives.

    The caller tries each command in order, skipping any already known
    to be unsupported. If all commands fail, the step has failed.

    Multi-step commands use + separator (e.g. "ARM1+PERI1" means
    send ARM1 then PERI1 as separate sequential API calls).
    """

    commands: list[str]


# Interior arm commands: InteriorMode -> command string
_INTERIOR_ARM: dict[InteriorMode, str] = {
    InteriorMode.DAY: "ARMDAY1",
    InteriorMode.NIGHT: "ARMNIGHT1",
    InteriorMode.TOTAL: "ARM1",
}

# Combined arm commands: interior mode -> [preferred compound commands]
# Order matters: ARMINTEXT1 first (Spanish WAF-safe), then ARM1PERI1 (Italian)
_COMBINED_ARM: dict[InteriorMode, list[str]] = {
    InteriorMode.TOTAL: ["ARMINTEXT1", "ARM1PERI1"],
    InteriorMode.DAY: ["ARMDAY1PERI1"],
    InteriorMode.NIGHT: ["ARMNIGHT1PERI1"],
}


class CommandResolver:
    """Resolves alarm state transitions into command sequences.

    Tracks which commands are unsupported by the panel (in-memory,
    resets on HA restart) and skips them in future resolutions.
    """

    def __init__(self, has_peri: bool) -> None:
        self._has_peri = has_peri
        self._unsupported: set[str] = set()

    def mark_unsupported(self, command: str) -> None:
        """Record that a command is not supported by this panel."""
        self._unsupported.add(command)

    @property
    def unsupported(self) -> frozenset[str]:
        """Return the set of unsupported commands."""
        return frozenset(self._unsupported)

    def resolve(self, current: AlarmState, target: AlarmState) -> list[CommandStep]:
        """Return ordered command steps to transition from current to target state."""
        if current == target:
            return []

        steps: list[CommandStep] = []

        interior_changes = current.interior != target.interior

        # Full disarm (target is off/off)
        if (
            target.interior == InteriorMode.OFF
            and target.perimeter == PerimeterMode.OFF
        ):
            steps.extend(self._resolve_disarm(current))
            return steps

        # Mode change: need to disarm first, then arm new mode
        if interior_changes and current.interior != InteriorMode.OFF:
            steps.extend(self._resolve_disarm(current))
            steps.extend(
                self._resolve_arm(
                    AlarmState(InteriorMode.OFF, PerimeterMode.OFF), target
                )
            )
            return steps

        # Arming from current state
        steps.extend(self._resolve_arm(current, target))
        return steps

    def _resolve_disarm(self, current: AlarmState) -> list[CommandStep]:
        """Resolve disarm-to-off commands based on what's currently armed."""
        has_interior = current.interior != InteriorMode.OFF
        has_peri = current.perimeter == PerimeterMode.ON

        if not has_interior and not has_peri:
            return []

        if not self._has_peri or not has_peri:
            return [CommandStep(commands=["DARM1"])]

        if has_interior and has_peri:
            cmds = self._filter_unsupported(["DARM1DARMPERI", "DARM1"])
            return [CommandStep(commands=cmds)]

        # Only perimeter armed
        cmds = self._filter_unsupported(["DPERI1", "DARM1"])
        return [CommandStep(commands=cmds)]

    def _resolve_arm(
        self, current: AlarmState, target: AlarmState
    ) -> list[CommandStep]:
        """Resolve arm commands from current to target state."""
        interior_changes = current.interior != target.interior
        peri_changes = current.perimeter != target.perimeter

        if not interior_changes and not peri_changes:
            return []

        # Only perimeter changes
        if not interior_changes and peri_changes:
            if target.perimeter == PerimeterMode.ON:
                return [CommandStep(commands=["PERI1"])]
            cmds = self._filter_unsupported(["DPERI1", "DARM1"])
            return [CommandStep(commands=cmds)]

        # Only interior changes
        if interior_changes and not peri_changes:
            arm_cmd = _INTERIOR_ARM[target.interior]
            return [CommandStep(commands=[arm_cmd])]

        # Both axes change: arm interior + enable perimeter
        if target.perimeter == PerimeterMode.ON and target.interior != InteriorMode.OFF:
            arm_cmd = _INTERIOR_ARM[target.interior]
            combined = _COMBINED_ARM.get(target.interior, [])
            all_cmds = list(combined) + [f"{arm_cmd}+PERI1"]
            cmds = self._filter_unsupported(all_cmds)
            return [CommandStep(commands=cmds)]

        if target.perimeter == PerimeterMode.ON:
            return [CommandStep(commands=["PERI1"])]

        return []

    def _filter_unsupported(self, commands: list[str]) -> list[str]:
        """Remove commands known to be unsupported."""
        return [c for c in commands if c not in self._unsupported]
