"""Command resolver for Securitas alarm state transitions.

Models alarm state as two independent axes (interior mode + perimeter)
and resolves transitions into command sequences with runtime fallback
discovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
