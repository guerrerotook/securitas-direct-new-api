"""Define constants for Securitas Direct API."""

from enum import StrEnum


class CommandType(StrEnum):
    """Legacy command type enum - kept for migration from old config."""

    STD = "std"
    PERI = "peri"


class SecuritasState(StrEnum):
    """Verisure alarm states - combinations of interior mode and perimeter."""

    NOT_USED = "not_used"
    DISARMED = "disarmed"
    DISARMED_PERI = "disarmed_peri"
    PARTIAL_DAY = "partial_day"
    PARTIAL_NIGHT = "partial_night"
    TOTAL = "total"
    PERI_ONLY = "peri_only"
    PARTIAL_DAY_PERI = "partial_day_peri"
    PARTIAL_NIGHT_PERI = "partial_night_peri"
    TOTAL_PERI = "total_peri"
    # Annex-bearing variants (combined-panel mappings for installations with annex)
    ANNEX_ONLY = "annex_only"
    PARTIAL_DAY_ANNEX = "partial_day_annex"
    PARTIAL_NIGHT_ANNEX = "partial_night_annex"
    TOTAL_ANNEX = "total_annex"
    PERI_ANNEX = "peri_annex"
    PARTIAL_DAY_PERI_ANNEX = "partial_day_peri_annex"
    PARTIAL_NIGHT_PERI_ANNEX = "partial_night_peri_annex"
    TOTAL_PERI_ANNEX = "total_peri_annex"


# Map SecuritasState -> API arm command string
STATE_TO_COMMAND: dict[SecuritasState, str] = {
    SecuritasState.DISARMED: "DARM1",
    SecuritasState.DISARMED_PERI: "DARM1DARMPERI",
    SecuritasState.PARTIAL_DAY: "ARMDAY1",
    SecuritasState.PARTIAL_NIGHT: "ARMNIGHT1",
    SecuritasState.TOTAL: "ARM1",
    SecuritasState.PERI_ONLY: "PERI1",
    SecuritasState.PARTIAL_DAY_PERI: "ARMDAY1PERI1",
    SecuritasState.PARTIAL_NIGHT_PERI: "ARMNIGHT1PERI1",
    SecuritasState.TOTAL_PERI: "ARM1PERI1",
}
# Proto response code for the disarmed state (handled separately from PROTO_TO_STATE
# in alarm_control_panel.py because it applies unconditionally regardless of mapping)
PROTO_DISARMED = "D"

# Map protomResponse code -> SecuritasState
PROTO_TO_STATE: dict[str, SecuritasState] = {
    # Same as DISARMED_PERI but alarm_control_panel.py already handles
    # the disarmed case without using this map
    "D": SecuritasState.DISARMED,
    "E": SecuritasState.PERI_ONLY,
    "P": SecuritasState.PARTIAL_DAY,
    "Q": SecuritasState.PARTIAL_NIGHT,
    "B": SecuritasState.PARTIAL_DAY_PERI,
    "C": SecuritasState.PARTIAL_NIGHT_PERI,
    "T": SecuritasState.TOTAL,
    "A": SecuritasState.TOTAL_PERI,
}

# Human-readable labels for the config UI
STATE_LABELS: dict[SecuritasState, str] = {
    SecuritasState.NOT_USED: "Not used",
    SecuritasState.DISARMED: "Disarmed",
    SecuritasState.DISARMED_PERI: "Disarmed",
    SecuritasState.PARTIAL_DAY: "Partial Day",
    SecuritasState.PARTIAL_NIGHT: "Partial Night",
    SecuritasState.TOTAL: "Total",
    SecuritasState.PERI_ONLY: "Perimeter only",
    SecuritasState.PARTIAL_DAY_PERI: "Partial Day + Perimeter",
    SecuritasState.PARTIAL_NIGHT_PERI: "Partial Night + Perimeter",
    SecuritasState.TOTAL_PERI: "Total + Perimeter",
    # Annex variants
    SecuritasState.ANNEX_ONLY: "Annex only",
    SecuritasState.PARTIAL_DAY_ANNEX: "Partial Day + Annex",
    SecuritasState.PARTIAL_NIGHT_ANNEX: "Partial Night + Annex",
    SecuritasState.TOTAL_ANNEX: "Total + Annex",
    SecuritasState.PERI_ANNEX: "Perimeter + Annex",
    SecuritasState.PARTIAL_DAY_PERI_ANNEX: "Partial Day + Perimeter + Annex",
    SecuritasState.PARTIAL_NIGHT_PERI_ANNEX: "Partial Night + Perimeter + Annex",
    SecuritasState.TOTAL_PERI_ANNEX: "Total + Perimeter + Annex",
}

# Options available when perimeter is NOT configured
STD_OPTIONS: list[SecuritasState] = [
    SecuritasState.NOT_USED,
    SecuritasState.PARTIAL_DAY,
    SecuritasState.PARTIAL_NIGHT,
    SecuritasState.TOTAL,
]

# Options available when perimeter IS configured
PERI_OPTIONS: list[SecuritasState] = [
    SecuritasState.NOT_USED,
    SecuritasState.PARTIAL_DAY,
    SecuritasState.PARTIAL_NIGHT,
    SecuritasState.TOTAL,
    SecuritasState.PERI_ONLY,
    SecuritasState.PARTIAL_DAY_PERI,
    SecuritasState.PARTIAL_NIGHT_PERI,
    SecuritasState.TOTAL_PERI,
]

# Default mappings matching current behavior (keyed by HA button name)
STD_DEFAULTS: dict[str, str] = {
    "map_home": SecuritasState.PARTIAL_DAY.value,
    "map_away": SecuritasState.TOTAL.value,
    "map_night": SecuritasState.PARTIAL_NIGHT.value,
    "map_custom": SecuritasState.NOT_USED.value,
    "map_vacation": SecuritasState.NOT_USED.value,
}

PERI_DEFAULTS: dict[str, str] = {
    "map_home": SecuritasState.PARTIAL_DAY.value,
    "map_away": SecuritasState.TOTAL_PERI.value,
    "map_night": SecuritasState.PARTIAL_NIGHT.value,
    "map_custom": SecuritasState.PERI_ONLY.value,
    "map_vacation": SecuritasState.NOT_USED.value,
}
