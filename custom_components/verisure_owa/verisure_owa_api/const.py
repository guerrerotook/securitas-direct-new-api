"""Define constants for Verisure OWA API."""

from enum import StrEnum


class CommandType(StrEnum):
    """Legacy command type enum - kept for migration from old config."""

    STD = "std"
    PERI = "peri"


class VerisureOwaState(StrEnum):
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


# Map VerisureOwaState -> API arm command string
STATE_TO_COMMAND: dict[VerisureOwaState, str] = {
    VerisureOwaState.DISARMED: "DARM1",
    VerisureOwaState.DISARMED_PERI: "DARM1DARMPERI",
    VerisureOwaState.PARTIAL_DAY: "ARMDAY1",
    VerisureOwaState.PARTIAL_NIGHT: "ARMNIGHT1",
    VerisureOwaState.TOTAL: "ARM1",
    VerisureOwaState.PERI_ONLY: "PERI1",
    VerisureOwaState.PARTIAL_DAY_PERI: "ARMDAY1PERI1",
    VerisureOwaState.PARTIAL_NIGHT_PERI: "ARMNIGHT1PERI1",
    VerisureOwaState.TOTAL_PERI: "ARM1PERI1",
}
# Proto response code for the disarmed state (handled separately from PROTO_TO_STATE
# in alarm_control_panel.py because it applies unconditionally regardless of mapping)
PROTO_DISARMED = "D"

# Map protomResponse code -> VerisureOwaState
PROTO_TO_STATE: dict[str, VerisureOwaState] = {
    # Same as DISARMED_PERI but alarm_control_panel.py already handles
    # the disarmed case without using this map
    "D": VerisureOwaState.DISARMED,
    "E": VerisureOwaState.PERI_ONLY,
    "P": VerisureOwaState.PARTIAL_DAY,
    "Q": VerisureOwaState.PARTIAL_NIGHT,
    "B": VerisureOwaState.PARTIAL_DAY_PERI,
    "C": VerisureOwaState.PARTIAL_NIGHT_PERI,
    "T": VerisureOwaState.TOTAL,
    "A": VerisureOwaState.TOTAL_PERI,
    # Annex-armed codes (interior-mode-bit × annex-bit, no perimeter).
    # Source: issue #441 status-code table.
    "X": VerisureOwaState.ANNEX_ONLY,  # main disarmed,  annex armed
    "R": VerisureOwaState.PARTIAL_DAY_ANNEX,  # main day,       annex armed
    "S": VerisureOwaState.PARTIAL_NIGHT_ANNEX,  # main night,     annex armed
    "O": VerisureOwaState.TOTAL_ANNEX,  # main total,     annex armed
    # Annex + perimeter combinations (PERI_ANNEX, PARTIAL_DAY_PERI_ANNEX,
    # PARTIAL_NIGHT_PERI_ANNEX, TOTAL_PERI_ANNEX) haven't been observed in
    # any capture yet so are not yet mapped.
}

# Human-readable labels for the config UI
STATE_LABELS: dict[VerisureOwaState, str] = {
    VerisureOwaState.NOT_USED: "Not used",
    VerisureOwaState.DISARMED: "Disarmed",
    VerisureOwaState.DISARMED_PERI: "Disarmed",
    VerisureOwaState.PARTIAL_DAY: "Partial Day",
    VerisureOwaState.PARTIAL_NIGHT: "Partial Night",
    VerisureOwaState.TOTAL: "Total",
    VerisureOwaState.PERI_ONLY: "Perimeter only",
    VerisureOwaState.PARTIAL_DAY_PERI: "Partial Day + Perimeter",
    VerisureOwaState.PARTIAL_NIGHT_PERI: "Partial Night + Perimeter",
    VerisureOwaState.TOTAL_PERI: "Total + Perimeter",
    # Annex-bearing variants
    VerisureOwaState.ANNEX_ONLY: "Annex only",
    VerisureOwaState.PARTIAL_DAY_ANNEX: "Partial Day + Annex",
    VerisureOwaState.PARTIAL_NIGHT_ANNEX: "Partial Night + Annex",
    VerisureOwaState.TOTAL_ANNEX: "Total + Annex",
    VerisureOwaState.PERI_ANNEX: "Perimeter + Annex",
    VerisureOwaState.PARTIAL_DAY_PERI_ANNEX: "Partial Day + Perimeter + Annex",
    VerisureOwaState.PARTIAL_NIGHT_PERI_ANNEX: "Partial Night + Perimeter + Annex",
    VerisureOwaState.TOTAL_PERI_ANNEX: "Total + Perimeter + Annex",
}

# Options available when perimeter is NOT configured
STD_OPTIONS: list[VerisureOwaState] = [
    VerisureOwaState.NOT_USED,
    VerisureOwaState.PARTIAL_DAY,
    VerisureOwaState.PARTIAL_NIGHT,
    VerisureOwaState.TOTAL,
]

# Options available when perimeter IS configured
PERI_OPTIONS: list[VerisureOwaState] = [
    VerisureOwaState.NOT_USED,
    VerisureOwaState.PARTIAL_DAY,
    VerisureOwaState.PARTIAL_NIGHT,
    VerisureOwaState.TOTAL,
    VerisureOwaState.PERI_ONLY,
    VerisureOwaState.PARTIAL_DAY_PERI,
    VerisureOwaState.PARTIAL_NIGHT_PERI,
    VerisureOwaState.TOTAL_PERI,
]

# Default mappings matching current behavior (keyed by HA button name)
STD_DEFAULTS: dict[str, str] = {
    "map_home": VerisureOwaState.PARTIAL_DAY.value,
    "map_away": VerisureOwaState.TOTAL.value,
    "map_night": VerisureOwaState.PARTIAL_NIGHT.value,
    "map_custom": VerisureOwaState.NOT_USED.value,
    "map_vacation": VerisureOwaState.NOT_USED.value,
}

PERI_DEFAULTS: dict[str, str] = {
    "map_home": VerisureOwaState.PARTIAL_DAY.value,
    "map_away": VerisureOwaState.TOTAL_PERI.value,
    "map_night": VerisureOwaState.PARTIAL_NIGHT.value,
    "map_custom": VerisureOwaState.PERI_ONLY.value,
    "map_vacation": VerisureOwaState.NOT_USED.value,
}
