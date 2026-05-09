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

# Options available when perimeter is NOT configured.
# NOT_USED is intentionally absent — the mapping form represents "not used"
# as a cleared field rather than a dropdown choice. Pre-v5 saved values of
# "not_used" are still accepted on read (panel skips them) for backwards
# compatibility with existing config entries.
STD_OPTIONS: list[VerisureOwaState] = [
    VerisureOwaState.PARTIAL_DAY,
    VerisureOwaState.PARTIAL_NIGHT,
    VerisureOwaState.TOTAL,
]

# Options available when perimeter IS configured
PERI_OPTIONS: list[VerisureOwaState] = [
    VerisureOwaState.PARTIAL_DAY,
    VerisureOwaState.PARTIAL_NIGHT,
    VerisureOwaState.TOTAL,
    VerisureOwaState.PERI_ONLY,
    VerisureOwaState.PARTIAL_DAY_PERI,
    VerisureOwaState.PARTIAL_NIGHT_PERI,
    VerisureOwaState.TOTAL_PERI,
]

# Annex variants offered when annex is configured (no perimeter)
_ANNEX_ONLY_OPTIONS: list[VerisureOwaState] = [
    VerisureOwaState.ANNEX_ONLY,
    VerisureOwaState.PARTIAL_DAY_ANNEX,
    VerisureOwaState.PARTIAL_NIGHT_ANNEX,
    VerisureOwaState.TOTAL_ANNEX,
]

# Annex+perimeter combinations offered when both are configured
_PERI_ANNEX_OPTIONS: list[VerisureOwaState] = [
    VerisureOwaState.PERI_ANNEX,
    VerisureOwaState.PARTIAL_DAY_PERI_ANNEX,
    VerisureOwaState.PARTIAL_NIGHT_PERI_ANNEX,
    VerisureOwaState.TOTAL_PERI_ANNEX,
]


def dropdown_options(*, has_peri: bool, has_annex: bool) -> list[VerisureOwaState]:
    """Return the alarm-mode options offered in the state-mappings dropdown.

    Always offers the four interior modes. Adds peri-bearing variants when
    has_peri, annex-bearing variants when has_annex, and peri+annex variants
    when both are set. The combined-panel mappings cover every interior ×
    perimeter × annex combination the panel can sit in, so users can map
    any HA button to any reachable state.
    """
    options: list[VerisureOwaState] = list(STD_OPTIONS)
    if has_peri:
        options.extend(s for s in PERI_OPTIONS if s not in STD_OPTIONS)
    if has_annex:
        options.extend(_ANNEX_ONLY_OPTIONS)
    if has_peri and has_annex:
        options.extend(_PERI_ANNEX_OPTIONS)
    return options


# Default mappings keyed by HA button name. Entries are present only for
# buttons that should arrive pre-filled in the form; map_custom and
# map_vacation are intentionally absent on standard installations so they
# render as blank ("not used") and the user opts in.
STD_DEFAULTS: dict[str, str] = {
    "map_home": VerisureOwaState.PARTIAL_DAY.value,
    "map_away": VerisureOwaState.TOTAL.value,
    "map_night": VerisureOwaState.PARTIAL_NIGHT.value,
}

PERI_DEFAULTS: dict[str, str] = {
    "map_home": VerisureOwaState.PARTIAL_DAY.value,
    "map_away": VerisureOwaState.TOTAL_PERI.value,
    "map_night": VerisureOwaState.PARTIAL_NIGHT.value,
    "map_custom": VerisureOwaState.PERI_ONLY.value,
}
