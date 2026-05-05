"""Tests for integration and securitas_direct_new_api constants."""

import pytest

from custom_components.securitas.const import SENTINEL_SERVICE_NAMES
from custom_components.securitas.securitas_direct_new_api.const import (
    CommandType,
    PERI_DEFAULTS,
    PERI_OPTIONS,
    PROTO_TO_STATE,
    STATE_LABELS,
    STATE_TO_COMMAND,
    STD_DEFAULTS,
    STD_OPTIONS,
    SecuritasState,
)


# ── SENTINEL_SERVICE_NAMES ───────────────────────────────────────────────────


class TestSentinelServiceNames:
    """Tests for sentinel service name discovery."""

    def test_contains_known_names(self):
        assert "CONFORT" in SENTINEL_SERVICE_NAMES
        assert "COMFORTO" in SENTINEL_SERVICE_NAMES
        assert "COMFORT" in SENTINEL_SERVICE_NAMES

    def test_is_frozenset(self):
        assert isinstance(SENTINEL_SERVICE_NAMES, frozenset)

    def test_unrelated_service_not_matched(self):
        assert "ALARM" not in SENTINEL_SERVICE_NAMES
        assert "confort" not in SENTINEL_SERVICE_NAMES


# ── CommandType ──────────────────────────────────────────────────────────────


class TestCommandType:
    """Tests for CommandType enum."""

    def test_std_value(self):
        assert CommandType.STD == "std"

    def test_peri_value(self):
        assert CommandType.PERI == "peri"

    def test_has_exactly_two_members(self):
        assert len(CommandType) == 2


# ── SecuritasState ───────────────────────────────────────────────────────────


class TestSecuritasState:
    """Tests for SecuritasState enum."""

    EXPECTED_MEMBERS = {
        "NOT_USED": "not_used",
        "DISARMED": "disarmed",
        "DISARMED_PERI": "disarmed_peri",
        "PARTIAL_DAY": "partial_day",
        "PARTIAL_NIGHT": "partial_night",
        "TOTAL": "total",
        "PERI_ONLY": "peri_only",
        "PARTIAL_DAY_PERI": "partial_day_peri",
        "PARTIAL_NIGHT_PERI": "partial_night_peri",
        "TOTAL_PERI": "total_peri",
        "ANNEX_ONLY": "annex_only",
        "PARTIAL_DAY_ANNEX": "partial_day_annex",
        "PARTIAL_NIGHT_ANNEX": "partial_night_annex",
        "TOTAL_ANNEX": "total_annex",
        "PERI_ANNEX": "peri_annex",
        "PARTIAL_DAY_PERI_ANNEX": "partial_day_peri_annex",
        "PARTIAL_NIGHT_PERI_ANNEX": "partial_night_peri_annex",
        "TOTAL_PERI_ANNEX": "total_peri_annex",
    }

    def test_has_all_eighteen_states(self):
        assert len(SecuritasState) == 18

    @pytest.mark.parametrize(
        ("member_name", "expected_value"),
        EXPECTED_MEMBERS.items(),
        ids=EXPECTED_MEMBERS.keys(),
    )
    def test_member_value(self, member_name, expected_value):
        assert SecuritasState[member_name].value == expected_value

    def test_is_str_enum(self):
        """Every member should be directly usable as a string."""
        for state in SecuritasState:
            assert isinstance(state, str)


# ── STATE_TO_COMMAND ─────────────────────────────────────────────────────────


class TestStateToCommand:
    """Tests for STATE_TO_COMMAND mapping."""

    def test_maps_every_state_except_not_used_and_annex_variants(self):
        """STATE_TO_COMMAND maps all states except NOT_USED and annex variants.

        Annex variants are handled via SECURITAS_STATE_TO_ALARM_STATE mapping
        in command_resolver.py rather than direct API commands.
        """
        states_with_commands = set(STATE_TO_COMMAND.keys())
        all_states = set(SecuritasState)
        annex_states = {
            SecuritasState.ANNEX_ONLY,
            SecuritasState.PARTIAL_DAY_ANNEX,
            SecuritasState.PARTIAL_NIGHT_ANNEX,
            SecuritasState.TOTAL_ANNEX,
            SecuritasState.PERI_ANNEX,
            SecuritasState.PARTIAL_DAY_PERI_ANNEX,
            SecuritasState.PARTIAL_NIGHT_PERI_ANNEX,
            SecuritasState.TOTAL_PERI_ANNEX,
        }
        assert states_with_commands == all_states - {SecuritasState.NOT_USED} - annex_states

    def test_not_used_is_not_in_map(self):
        assert SecuritasState.NOT_USED not in STATE_TO_COMMAND

    @pytest.mark.parametrize(
        ("state", "expected_cmd"),
        [
            (SecuritasState.DISARMED, "DARM1"),
            (SecuritasState.DISARMED_PERI, "DARM1DARMPERI"),
            (SecuritasState.PARTIAL_DAY, "ARMDAY1"),
            (SecuritasState.PARTIAL_NIGHT, "ARMNIGHT1"),
            (SecuritasState.TOTAL, "ARM1"),
            (SecuritasState.PERI_ONLY, "PERI1"),
            (SecuritasState.PARTIAL_DAY_PERI, "ARMDAY1PERI1"),
            (SecuritasState.PARTIAL_NIGHT_PERI, "ARMNIGHT1PERI1"),
            (SecuritasState.TOTAL_PERI, "ARM1PERI1"),
        ],
    )
    def test_specific_command_string(self, state, expected_cmd):
        assert STATE_TO_COMMAND[state] == expected_cmd

    def test_all_command_strings_are_non_empty(self):
        for cmd in STATE_TO_COMMAND.values():
            assert isinstance(cmd, str)
            assert len(cmd) > 0


# ── PROTO_TO_STATE ───────────────────────────────────────────────────────────


class TestProtoToState:
    """Tests for PROTO_TO_STATE mapping."""

    EXPECTED_PROTO_MAP = {
        "D": SecuritasState.DISARMED,
        "E": SecuritasState.PERI_ONLY,
        "P": SecuritasState.PARTIAL_DAY,
        "Q": SecuritasState.PARTIAL_NIGHT,
        "B": SecuritasState.PARTIAL_DAY_PERI,
        "C": SecuritasState.PARTIAL_NIGHT_PERI,
        "T": SecuritasState.TOTAL,
        "A": SecuritasState.TOTAL_PERI,
    }

    def test_has_eight_protocol_codes(self):
        assert len(PROTO_TO_STATE) == 8

    @pytest.mark.parametrize(
        ("code", "expected_state"),
        EXPECTED_PROTO_MAP.items(),
        ids=EXPECTED_PROTO_MAP.keys(),
    )
    def test_code_maps_to_correct_state(self, code, expected_state):
        assert PROTO_TO_STATE[code] == expected_state

    def test_all_keys_are_single_uppercase_letters(self):
        for code in PROTO_TO_STATE:
            assert len(code) == 1
            assert code.isupper()

    def test_all_values_are_securitas_states(self):
        for state in PROTO_TO_STATE.values():
            assert isinstance(state, SecuritasState)


# ── STATE_LABELS ─────────────────────────────────────────────────────────────


class TestStateLabels:
    """Tests for STATE_LABELS mapping."""

    def test_has_label_for_every_securitas_state(self):
        """Every SecuritasState member should have a human-readable label."""
        assert set(STATE_LABELS.keys()) == set(SecuritasState)

    def test_all_labels_are_non_empty_strings(self):
        for label in STATE_LABELS.values():
            assert isinstance(label, str)
            assert len(label) > 0

    @pytest.mark.parametrize(
        ("state", "expected_label"),
        [
            (SecuritasState.NOT_USED, "Not used"),
            (SecuritasState.TOTAL, "Total"),
            (SecuritasState.PERI_ONLY, "Perimeter only"),
            (SecuritasState.TOTAL_PERI, "Total + Perimeter"),
        ],
    )
    def test_specific_labels(self, state, expected_label):
        assert STATE_LABELS[state] == expected_label


# ── STD_OPTIONS / PERI_OPTIONS ───────────────────────────────────────────────


class TestStdOptions:
    """Tests for STD_OPTIONS list."""

    def test_contains_expected_states(self):
        assert set(STD_OPTIONS) == {
            SecuritasState.NOT_USED,
            SecuritasState.PARTIAL_DAY,
            SecuritasState.PARTIAL_NIGHT,
            SecuritasState.TOTAL,
        }

    def test_is_subset_of_peri_options(self):
        assert set(STD_OPTIONS).issubset(set(PERI_OPTIONS))

    def test_does_not_contain_peri_specific_states(self):
        peri_only_states = {
            SecuritasState.PERI_ONLY,
            SecuritasState.PARTIAL_DAY_PERI,
            SecuritasState.PARTIAL_NIGHT_PERI,
            SecuritasState.TOTAL_PERI,
        }
        assert set(STD_OPTIONS).isdisjoint(peri_only_states)

    def test_does_not_contain_disarmed_states(self):
        assert SecuritasState.DISARMED not in STD_OPTIONS
        assert SecuritasState.DISARMED_PERI not in STD_OPTIONS


class TestPeriOptions:
    """Tests for PERI_OPTIONS list."""

    def test_contains_expected_states(self):
        assert set(PERI_OPTIONS) == {
            SecuritasState.NOT_USED,
            SecuritasState.PARTIAL_DAY,
            SecuritasState.PARTIAL_NIGHT,
            SecuritasState.TOTAL,
            SecuritasState.PERI_ONLY,
            SecuritasState.PARTIAL_DAY_PERI,
            SecuritasState.PARTIAL_NIGHT_PERI,
            SecuritasState.TOTAL_PERI,
        }

    def test_contains_all_std_options(self):
        for opt in STD_OPTIONS:
            assert opt in PERI_OPTIONS

    def test_contains_peri_specific_states(self):
        assert SecuritasState.PERI_ONLY in PERI_OPTIONS
        assert SecuritasState.PARTIAL_DAY_PERI in PERI_OPTIONS
        assert SecuritasState.PARTIAL_NIGHT_PERI in PERI_OPTIONS
        assert SecuritasState.TOTAL_PERI in PERI_OPTIONS

    def test_does_not_contain_disarmed_states(self):
        assert SecuritasState.DISARMED not in PERI_OPTIONS
        assert SecuritasState.DISARMED_PERI not in PERI_OPTIONS


# ── STD_DEFAULTS / PERI_DEFAULTS ────────────────────────────────────────────


EXPECTED_DEFAULT_KEYS = {
    "map_home",
    "map_away",
    "map_night",
    "map_custom",
    "map_vacation",
}


class TestStdDefaults:
    """Tests for STD_DEFAULTS mapping."""

    def test_has_correct_keys(self):
        assert set(STD_DEFAULTS.keys()) == EXPECTED_DEFAULT_KEYS

    def test_values_are_valid_securitas_state_values(self):
        valid_values = {s.value for s in SecuritasState}
        for value in STD_DEFAULTS.values():
            assert value in valid_values

    def test_specific_defaults(self):
        assert STD_DEFAULTS["map_home"] == "partial_day"
        assert STD_DEFAULTS["map_away"] == "total"
        assert STD_DEFAULTS["map_night"] == "partial_night"
        assert STD_DEFAULTS["map_custom"] == "not_used"
        assert STD_DEFAULTS["map_vacation"] == "not_used"


class TestPeriDefaults:
    """Tests for PERI_DEFAULTS mapping."""

    def test_has_correct_keys(self):
        assert set(PERI_DEFAULTS.keys()) == EXPECTED_DEFAULT_KEYS

    def test_values_are_valid_securitas_state_values(self):
        valid_values = {s.value for s in SecuritasState}
        for value in PERI_DEFAULTS.values():
            assert value in valid_values

    def test_specific_defaults(self):
        assert PERI_DEFAULTS["map_home"] == "partial_day"
        assert PERI_DEFAULTS["map_away"] == "total_peri"
        assert PERI_DEFAULTS["map_night"] == "partial_night"
        assert PERI_DEFAULTS["map_custom"] == "peri_only"
        assert PERI_DEFAULTS["map_vacation"] == "not_used"

    def test_peri_defaults_differ_from_std_for_peri_states(self):
        """PERI_DEFAULTS should use peri-enhanced states for away and custom."""
        assert PERI_DEFAULTS["map_away"] != STD_DEFAULTS["map_away"]
        assert PERI_DEFAULTS["map_custom"] != STD_DEFAULTS["map_custom"]

    def test_home_mapping_is_same_as_std(self):
        """map_home is the same in both STD and PERI defaults."""
        assert PERI_DEFAULTS["map_home"] == STD_DEFAULTS["map_home"]

    def test_night_mapping_is_same_as_std(self):
        """map_night uses partial_night in both STD and PERI defaults."""
        assert PERI_DEFAULTS["map_night"] == STD_DEFAULTS["map_night"]
