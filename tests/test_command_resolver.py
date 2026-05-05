"""Tests for command_resolver module."""

import pytest

from custom_components.securitas.securitas_direct_new_api.command_resolver import (
    AlarmState,
    CommandResolver,
    InteriorMode,
    PerimeterMode,
    PROTO_TO_ALARM_STATE,
    ALARM_STATE_TO_PROTO,
)


class TestAlarmState:
    """Test the AlarmState model and proto code mappings."""

    def test_all_proto_codes_mapped(self):
        """Every known proto code maps to an AlarmState."""
        expected_protos = {"D", "P", "Q", "T", "E", "B", "C", "A", "X", "R", "S", "O"}
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
        from pydantic import ValidationError

        state = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        with pytest.raises(ValidationError):
            state.interior = InteriorMode.TOTAL  # type: ignore[misc]

    def test_alarm_state_equality(self):
        a = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        b = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        assert a == b

    def test_alarm_state_hashable(self):
        """AlarmState can be used as dict key."""
        state = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        d = {state: "test"}
        assert (
            d[AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)]
            == "test"
        )


class TestCommandResolverDisarm:
    """Test disarm transition resolution."""

    def test_no_op_when_already_disarmed(self):
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert steps == []

    def test_disarm_interior_only(self):
        resolver = CommandResolver(has_peri=False)
        current = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["DARM1"]

    def test_disarm_perimeter_only(self):
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.ON)
        target = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["DARMPERI", "DARM1"]

    def test_disarm_both_axes(self):
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        target = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["DARM1DARMPERI", "DARM1"]

    def test_disarm_both_no_peri_config(self):
        """Without peri config, disarm is always just DARM1."""
        resolver = CommandResolver(has_peri=False)
        current = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        target = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["DARM1"]

    def test_disarm_skips_unsupported_command(self):
        resolver = CommandResolver(has_peri=True)
        resolver.mark_unsupported("DARM1DARMPERI")
        current = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        target = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["DARM1"]

    def test_disarm_peri_skips_unsupported_darmperi(self):
        resolver = CommandResolver(has_peri=True)
        resolver.mark_unsupported("DARMPERI")
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.ON)
        target = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["DARM1"]


class TestCommandResolverArm:
    """Test arm transition resolution."""

    def test_arm_total_no_peri(self):
        resolver = CommandResolver(has_peri=False)
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["ARM1"]

    def test_arm_day_no_peri(self):
        resolver = CommandResolver(has_peri=False)
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.DAY, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["ARMDAY1"]

    def test_arm_night_no_peri(self):
        resolver = CommandResolver(has_peri=False)
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.NIGHT, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["ARMNIGHT1"]

    def test_arm_peri_only(self):
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.ON)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["PERI1"]

    def test_arm_total_plus_peri(self):
        """Combined arm: tries ARMINTEXT1 first (WAF-safe), then ARM1PERI1."""
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["ARMINTEXT1", "ARM1PERI1", "ARM1+PERI1"]

    def test_arm_day_plus_peri(self):
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.DAY, perimeter=PerimeterMode.ON)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["ARMDAY1PERI1", "ARMDAY1+PERI1"]

    def test_arm_night_plus_peri(self):
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.NIGHT, perimeter=PerimeterMode.ON)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["ARMNIGHT1PERI1", "ARMNIGHT1+PERI1"]

    def test_arm_peri_when_interior_already_armed(self):
        """Only perimeter changes — just send PERI1."""
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["PERI1"]

    def test_arm_skips_unsupported_compound(self):
        resolver = CommandResolver(has_peri=True)
        resolver.mark_unsupported("ARMINTEXT1")
        resolver.mark_unsupported("ARM1PERI1")
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["ARM1+PERI1"]


class TestCommandResolverModeChange:
    """Test mode change transitions (rearm: disarm + arm)."""

    def test_day_to_night_no_peri(self):
        """Mode change requires disarm then arm."""
        resolver = CommandResolver(has_peri=False)
        current = AlarmState(interior=InteriorMode.DAY, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.NIGHT, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert len(steps) == 2
        assert steps[0].commands == ["DARM1"]  # disarm first
        assert steps[1].commands == ["ARMNIGHT1"]  # then arm night

    def test_total_peri_to_day_peri(self):
        """Mode change with perimeter: disarm all, then arm day+peri."""
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        target = AlarmState(interior=InteriorMode.DAY, perimeter=PerimeterMode.ON)
        steps = resolver.resolve(current, target)
        assert len(steps) == 2
        assert steps[0].commands == ["DARM1DARMPERI", "DARM1"]  # disarm
        assert steps[1].commands == ["ARMDAY1PERI1", "ARMDAY1+PERI1"]  # arm

    def test_total_to_total_peri(self):
        """Interior same, just adding perimeter — no disarm needed."""
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF)
        target = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["PERI1"]

    def test_total_peri_to_disarmed(self):
        """Full disarm from total+peri."""
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        target = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["DARM1DARMPERI", "DARM1"]

    def test_peri_to_total_peri(self):
        """From peri-only to total+peri: just arm interior."""
        resolver = CommandResolver(has_peri=True)
        current = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.ON)
        target = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        steps = resolver.resolve(current, target)
        assert len(steps) == 1
        assert steps[0].commands == ["ARM1"]


class TestSecuritasStateAnnexMappings:
    """Test SecuritasState enum annex variants and their SECURITAS_STATE_TO_ALARM_STATE mappings."""

    def test_annex_only(self):
        from custom_components.securitas.securitas_direct_new_api.command_resolver import (
            SECURITAS_STATE_TO_ALARM_STATE,
        )
        from custom_components.securitas.securitas_direct_new_api.const import SecuritasState
        from custom_components.securitas.securitas_direct_new_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        s = SECURITAS_STATE_TO_ALARM_STATE[SecuritasState.ANNEX_ONLY]
        assert s.interior == InteriorMode.OFF
        assert s.perimeter == PerimeterMode.OFF
        assert s.annex == AnnexMode.ON

    def test_total_peri_annex(self):
        from custom_components.securitas.securitas_direct_new_api.command_resolver import (
            SECURITAS_STATE_TO_ALARM_STATE,
        )
        from custom_components.securitas.securitas_direct_new_api.const import SecuritasState
        from custom_components.securitas.securitas_direct_new_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        s = SECURITAS_STATE_TO_ALARM_STATE[SecuritasState.TOTAL_PERI_ANNEX]
        assert s.interior == InteriorMode.TOTAL
        assert s.perimeter == PerimeterMode.ON
        assert s.annex == AnnexMode.ON

    def test_all_eight_annex_variants_mapped(self):
        from custom_components.securitas.securitas_direct_new_api.command_resolver import (
            SECURITAS_STATE_TO_ALARM_STATE,
        )
        from custom_components.securitas.securitas_direct_new_api.const import SecuritasState

        for name in (
            "ANNEX_ONLY",
            "PARTIAL_DAY_ANNEX",
            "PARTIAL_NIGHT_ANNEX",
            "TOTAL_ANNEX",
            "PERI_ANNEX",
            "PARTIAL_DAY_PERI_ANNEX",
            "PARTIAL_NIGHT_PERI_ANNEX",
            "TOTAL_PERI_ANNEX",
        ):
            assert SecuritasState[name] in SECURITAS_STATE_TO_ALARM_STATE, name
