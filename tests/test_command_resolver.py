"""Tests for command_resolver module."""

import pytest

from custom_components.securitas.securitas_direct_new_api.command_resolver import (
    AlarmState,
    InteriorMode,
    PerimeterMode,
    PROTO_TO_ALARM_STATE,
    ALARM_STATE_TO_PROTO,
)


class TestAlarmState:
    """Test the AlarmState model and proto code mappings."""

    def test_all_proto_codes_mapped(self):
        """Every known proto code maps to an AlarmState."""
        expected_protos = {"D", "P", "Q", "T", "E", "B", "C", "A"}
        assert set(PROTO_TO_ALARM_STATE.keys()) == expected_protos

    def test_bidirectional_mapping(self):
        """ALARM_STATE_TO_PROTO is the inverse of PROTO_TO_ALARM_STATE."""
        for proto, state in PROTO_TO_ALARM_STATE.items():
            assert ALARM_STATE_TO_PROTO[state] == proto

    def test_disarmed_state(self):
        state = PROTO_TO_ALARM_STATE["D"]
        assert state.interior == InteriorMode.OFF
        assert state.perimeter == PerimeterMode.OFF

    def test_total_peri_state(self):
        state = PROTO_TO_ALARM_STATE["A"]
        assert state.interior == InteriorMode.TOTAL
        assert state.perimeter == PerimeterMode.ON

    def test_day_peri_state(self):
        state = PROTO_TO_ALARM_STATE["B"]
        assert state.interior == InteriorMode.DAY
        assert state.perimeter == PerimeterMode.ON

    def test_peri_only_state(self):
        state = PROTO_TO_ALARM_STATE["E"]
        assert state.interior == InteriorMode.OFF
        assert state.perimeter == PerimeterMode.ON

    def test_alarm_state_is_frozen(self):
        state = AlarmState(InteriorMode.OFF, PerimeterMode.OFF)
        with pytest.raises(AttributeError):
            state.interior = InteriorMode.TOTAL  # type: ignore[misc]

    def test_alarm_state_equality(self):
        a = AlarmState(InteriorMode.TOTAL, PerimeterMode.ON)
        b = AlarmState(InteriorMode.TOTAL, PerimeterMode.ON)
        assert a == b

    def test_alarm_state_hashable(self):
        """AlarmState can be used as dict key."""
        state = AlarmState(InteriorMode.TOTAL, PerimeterMode.ON)
        d = {state: "test"}
        assert d[AlarmState(InteriorMode.TOTAL, PerimeterMode.ON)] == "test"
