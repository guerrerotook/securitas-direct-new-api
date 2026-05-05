"""Command resolver for Securitas alarm state transitions.

Models alarm state as two independent axes (interior mode + perimeter)
and resolves transitions into command sequences with runtime fallback
discovery.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import SecuritasState
from .models import (
    AlarmState,
    AnnexMode,
    InteriorMode,
    PerimeterMode,
    ProtoCode,
    PROTO_TO_STATE,
)

# Re-export for backward compatibility
PROTO_TO_ALARM_STATE: dict[str, AlarmState] = {
    code.value: state for code, state in PROTO_TO_STATE.items()
}
ALARM_STATE_TO_PROTO: dict[AlarmState, str] = {
    state: code.value for code, state in PROTO_TO_STATE.items()
}

# SecuritasState (config/UI) -> AlarmState (resolver)
SECURITAS_STATE_TO_ALARM_STATE: dict[SecuritasState, AlarmState] = {
    SecuritasState.DISARMED: PROTO_TO_STATE[ProtoCode.DISARMED],
    SecuritasState.PARTIAL_DAY: PROTO_TO_STATE[ProtoCode.PARTIAL_DAY],
    SecuritasState.PARTIAL_NIGHT: PROTO_TO_STATE[ProtoCode.PARTIAL_NIGHT],
    SecuritasState.TOTAL: PROTO_TO_STATE[ProtoCode.TOTAL],
    SecuritasState.PERI_ONLY: PROTO_TO_STATE[ProtoCode.PERIMETER_ONLY],
    SecuritasState.PARTIAL_DAY_PERI: PROTO_TO_STATE[ProtoCode.PARTIAL_DAY_PERIMETER],
    SecuritasState.PARTIAL_NIGHT_PERI: PROTO_TO_STATE[
        ProtoCode.PARTIAL_NIGHT_PERIMETER
    ],
    SecuritasState.TOTAL_PERI: PROTO_TO_STATE[ProtoCode.TOTAL_PERIMETER],
    # Annex variants — the four known letters reuse PROTO_TO_STATE entries
    SecuritasState.ANNEX_ONLY: PROTO_TO_STATE[ProtoCode.ANNEX_ONLY],
    SecuritasState.PARTIAL_DAY_ANNEX: PROTO_TO_STATE[ProtoCode.PARTIAL_DAY_ANNEX],
    SecuritasState.PARTIAL_NIGHT_ANNEX: PROTO_TO_STATE[ProtoCode.PARTIAL_NIGHT_ANNEX],
    SecuritasState.TOTAL_ANNEX: PROTO_TO_STATE[ProtoCode.TOTAL_ANNEX],
    # Perimeter+annex combinations (no proto code yet — discovered via Custom Override)
    SecuritasState.PERI_ANNEX: AlarmState(
        interior=InteriorMode.OFF, perimeter=PerimeterMode.ON, annex=AnnexMode.ON
    ),
    SecuritasState.PARTIAL_DAY_PERI_ANNEX: AlarmState(
        interior=InteriorMode.DAY, perimeter=PerimeterMode.ON, annex=AnnexMode.ON
    ),
    SecuritasState.PARTIAL_NIGHT_PERI_ANNEX: AlarmState(
        interior=InteriorMode.NIGHT, perimeter=PerimeterMode.ON, annex=AnnexMode.ON
    ),
    SecuritasState.TOTAL_PERI_ANNEX: AlarmState(
        interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON, annex=AnnexMode.ON
    ),
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

    def __init__(self, has_peri: bool, has_annex: bool = False) -> None:
        self._has_peri = has_peri
        self._has_annex = has_annex
        self._unsupported: set[str] = set()

    def mark_unsupported(self, command: str) -> None:
        """Record that a command is not supported by this panel."""
        self._unsupported.add(command)

    @property
    def unsupported(self) -> frozenset[str]:
        """Return the set of unsupported commands."""
        return frozenset(self._unsupported)

    def _resolve_annex(
        self, current_annex: AnnexMode, target_annex: AnnexMode
    ) -> list[CommandStep]:
        """Resolve a pure-annex transition (interior + peri both unchanged)."""
        if current_annex == target_annex:
            return []
        if target_annex == AnnexMode.ON:
            return [CommandStep(commands=["ARMANNEX"])]
        return [CommandStep(commands=["DARMANNEX"])]

    def resolve(self, current: AlarmState, target: AlarmState) -> list[CommandStep]:
        """Return ordered command steps to transition from current to target state."""
        if current == target:
            return []

        # Pure annex-axis change with interior/perimeter equal
        if (
            current.interior == target.interior
            and current.perimeter == target.perimeter
            and current.annex != target.annex
        ):
            return self._resolve_annex(current.annex, target.annex)

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
                    AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF),
                    target,
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
        cmds = self._filter_unsupported(["DARMPERI", "DARM1"])
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
            cmds = self._filter_unsupported(["DARMPERI", "DARM1"])
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
