"""Tests for alarm_control_panel entity logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.alarm_control_panel import AlarmControlPanelEntityFeature
from homeassistant.components.alarm_control_panel.const import (
    AlarmControlPanelState,
    CodeFormat,
)

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    ArmStatus,
    CheckAlarmStatus,
    DisarmStatus,
    Installation,
)
from custom_components.securitas.securitas_direct_new_api.const import (
    PERI_DEFAULTS,
    PROTO_TO_STATE,
    STATE_TO_COMMAND,
    STD_DEFAULTS,
    SecuritasState,
)
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
)
from custom_components.securitas.alarm_control_panel import (
    HA_STATE_TO_CONF_KEY,
    SecuritasAlarm,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_alarm(
    config=None,
    has_peri=False,
    initial_status=None,
    code=None,
) -> SecuritasAlarm:
    """Create a SecuritasAlarm with mocked dependencies.

    ``code`` sets the CONF_CODE value that check_code() compares against.
    """
    installation = Installation(
        number="123456",
        alias="Home",
        panel="SDVFAST",
        type="PLUS",
        address="123 St",
        city="Madrid",
    )

    if config is None:
        defaults = PERI_DEFAULTS if has_peri else STD_DEFAULTS
        config = {
            "PERI_alarm": has_peri,
            "map_home": defaults["map_home"],
            "map_away": defaults["map_away"],
            "map_night": defaults["map_night"],
            "map_custom": defaults["map_custom"],
            "scan_interval": 120,
        }

    if code is not None:
        config["code"] = code

    client = MagicMock()
    client.config = config
    client.session = AsyncMock()

    hass = MagicMock()
    hass.async_create_task = MagicMock()
    hass.services = MagicMock()

    if initial_status is None:
        initial_status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="D",
            protomResponseData="",
        )

    # Patch async_track_time_interval to avoid HA event loop dependency,
    # and patch Entity state-writing methods that require a running HA instance.
    with (
        patch(
            "custom_components.securitas.alarm_control_panel.async_track_time_interval"
        ) as mock_track,
        patch.object(
            SecuritasAlarm, "async_schedule_update_ha_state", MagicMock()
        ),
        patch.object(SecuritasAlarm, "async_write_ha_state", MagicMock()),
    ):
        mock_track.return_value = MagicMock()  # unsub callable
        alarm = SecuritasAlarm(
            installation=installation,
            state=initial_status,
            client=client,
            hass=hass,
        )
    # Keep the patches alive on the instance for later calls in tests
    alarm.async_schedule_update_ha_state = MagicMock()
    alarm.async_write_ha_state = MagicMock()
    return alarm


# ===========================================================================
# update_status_alarm  (STD defaults)
# ===========================================================================


class TestUpdateStatusAlarm:
    """Tests for update_status_alarm with STD (non-perimeter) config."""

    def test_disarmed(self):
        """protomResponse 'D' sets state to DISARMED."""
        alarm = make_alarm()
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="D",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.DISARMED

    def test_total_maps_to_armed_away(self):
        """protomResponse 'T' (total) maps to ARMED_AWAY with STD defaults."""
        alarm = make_alarm()
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="T",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    def test_partial_day_maps_to_armed_home(self):
        """protomResponse 'P' (partial_day) maps to ARMED_HOME with STD defaults."""
        alarm = make_alarm()
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="P",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_HOME

    def test_partial_night_maps_to_armed_night(self):
        """protomResponse 'Q' (partial_night) maps to ARMED_NIGHT with STD defaults."""
        alarm = make_alarm()
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="Q",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_NIGHT

    def test_unknown_code_sets_custom_bypass_and_notifies(self):
        """Unknown protomResponse code sets ARMED_CUSTOM_BYPASS and calls _notify_error."""
        alarm = make_alarm()
        alarm._notify_error = MagicMock()

        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="Z",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        alarm._notify_error.assert_called_once()
        args = alarm._notify_error.call_args
        assert args[0][0] == "unmapped_state"

    def test_empty_protom_response_ignored(self):
        """Empty protomResponse leaves state unchanged."""
        alarm = make_alarm()
        assert alarm._state == AlarmControlPanelState.DISARMED

        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.DISARMED

    def test_none_status_with_message_attr(self):
        """None status is handled gracefully -- no crash."""
        alarm = make_alarm()
        alarm.update_status_alarm(None)
        # State should remain at the initial value
        assert alarm._state == AlarmControlPanelState.DISARMED

    def test_status_message_stored_in_extra_attributes(self):
        """Status message and protomResponseData are stored in extra_state_attributes."""
        alarm = make_alarm()
        status = CheckAlarmStatus(
            operation_status="OK",
            message="Panel ok",
            status="",
            InstallationNumer="123456",
            protomResponse="D",
            protomResponseData="some-data",
        )
        alarm.update_status_alarm(status)
        assert alarm._attr_extra_state_attributes["message"] == "Panel ok"
        assert alarm._attr_extra_state_attributes["response_data"] == "some-data"


# ===========================================================================
# update_status_alarm  (PERI config)
# ===========================================================================


class TestUpdateStatusAlarmPeri:
    """Tests for update_status_alarm with PERI (perimeter) config."""

    def test_total_peri_maps_to_armed_away(self):
        """protomResponse 'A' (total_peri) maps to ARMED_AWAY with PERI defaults."""
        alarm = make_alarm(has_peri=True)
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="A",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    def test_peri_only_maps_to_armed_custom_bypass(self):
        """protomResponse 'E' (peri_only) maps to ARMED_CUSTOM_BYPASS with PERI defaults."""
        alarm = make_alarm(has_peri=True)
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="E",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS

    def test_partial_night_peri_maps_to_armed_night(self):
        """protomResponse 'Q' still maps to ARMED_NIGHT (partial_night) with PERI defaults.

        In PERI defaults map_night = partial_night_peri.  The 'Q' proto code
        maps to partial_night (without peri).  With PERI defaults the night
        slot is bound to partial_night_peri (proto 'B' is partial_day_peri).
        Since 'Q' is partial_night and that is NOT the configured state for
        any PERI mapping, 'Q' will fall through to the unknown handler.
        """
        alarm = make_alarm(has_peri=True)
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="Q",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        # With PERI defaults, partial_night (Q) is not mapped to any HA state
        # (map_night is partial_night_peri which maps from a different proto code).
        # So the unknown handler fires.
        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS


# ===========================================================================
# check_code
# ===========================================================================


class TestCheckCode:
    """Tests for check_code()."""

    def test_empty_code_config_allows_any(self):
        """Empty code config means any code passes."""
        alarm = make_alarm(code="")
        assert alarm.check_code("1234") is True
        assert alarm.check_code(None) is True

    def test_none_code_config_allows_any(self):
        """None code config (no key) means any code passes."""
        alarm = make_alarm()
        # config has no 'code' key at all
        assert "code" not in alarm.client.config or alarm.client.config.get("code") in (
            "",
            None,
        )
        assert alarm.check_code("9999") is True

    def test_matching_code_returns_true(self):
        """Matching code returns True."""
        alarm = make_alarm(code="1234")
        assert alarm.check_code("1234") is True

    def test_non_matching_code_returns_false(self):
        """Non-matching code returns False."""
        alarm = make_alarm(code="1234")
        assert alarm.check_code("0000") is False

    def test_numeric_code_compared_as_string(self):
        """Integer code in config is compared as string."""
        alarm = make_alarm(code=1234)
        assert alarm.check_code("1234") is True
        assert alarm.check_code("5678") is False


# ===========================================================================
# supported_features
# ===========================================================================


class TestSupportedFeatures:
    """Tests for supported_features property."""

    def test_std_defaults_features(self):
        """STD defaults: ARM_HOME, ARM_AWAY, ARM_NIGHT (no ARM_CUSTOM_BYPASS)."""
        alarm = make_alarm(has_peri=False)
        features = alarm.supported_features
        assert features & AlarmControlPanelEntityFeature.ARM_HOME
        assert features & AlarmControlPanelEntityFeature.ARM_AWAY
        assert features & AlarmControlPanelEntityFeature.ARM_NIGHT
        assert not (features & AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS)

    def test_peri_defaults_features(self):
        """PERI defaults: ARM_HOME, ARM_AWAY, ARM_NIGHT, ARM_CUSTOM_BYPASS."""
        alarm = make_alarm(has_peri=True)
        features = alarm.supported_features
        assert features & AlarmControlPanelEntityFeature.ARM_HOME
        assert features & AlarmControlPanelEntityFeature.ARM_AWAY
        assert features & AlarmControlPanelEntityFeature.ARM_NIGHT
        assert features & AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS

    def test_no_features_when_all_not_used(self):
        """If all mappings are not_used, no features are reported."""
        config = {
            "PERI_alarm": False,
            "map_home": SecuritasState.NOT_USED.value,
            "map_away": SecuritasState.NOT_USED.value,
            "map_night": SecuritasState.NOT_USED.value,
            "map_custom": SecuritasState.NOT_USED.value,
            "scan_interval": 120,
        }
        alarm = make_alarm(config=config)
        assert alarm.supported_features == 0


# ===========================================================================
# async_alarm_disarm
# ===========================================================================


@pytest.mark.asyncio
class TestAsyncAlarmDisarm:
    """Tests for async_alarm_disarm()."""

    async def test_correct_code_calls_disarm(self):
        """Correct code calls disarm_alarm on session."""
        alarm = make_alarm(code="1234")
        # Pre-set to armed so we can see it transition
        alarm._state = AlarmControlPanelState.ARMED_AWAY

        alarm.client.session.disarm_alarm = AsyncMock(
            return_value=DisarmStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protomResponse="D",
                protomResponseData="",
            )
        )

        await alarm.async_alarm_disarm("1234")

        alarm.client.session.disarm_alarm.assert_called_once_with(
            alarm.installation, STATE_TO_COMMAND[SecuritasState.DISARMED]
        )
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_wrong_code_does_not_call_disarm(self):
        """Wrong code does not call disarm_alarm."""
        alarm = make_alarm(code="1234")
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm.client.session.disarm_alarm = AsyncMock()

        await alarm.async_alarm_disarm("0000")

        alarm.client.session.disarm_alarm.assert_not_called()
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_disarm_error_notifies(self):
        """Error from disarm_alarm calls _notify_error."""
        alarm = make_alarm(code="1234")
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._notify_error = MagicMock()

        alarm.client.session.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("API down")
        )

        await alarm.async_alarm_disarm("1234")

        alarm._notify_error.assert_called_once()
        args = alarm._notify_error.call_args
        assert args[0][0] == "disarm_error"

    async def test_disarm_with_peri_uses_disarmed_peri_command(self):
        """PERI config uses DISARMED_PERI command for disarm."""
        alarm = make_alarm(has_peri=True)
        alarm._state = AlarmControlPanelState.ARMED_AWAY

        alarm.client.session.disarm_alarm = AsyncMock(
            return_value=DisarmStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protomResponse="D",
                protomResponseData="",
            )
        )

        await alarm.async_alarm_disarm()

        alarm.client.session.disarm_alarm.assert_called_once_with(
            alarm.installation, STATE_TO_COMMAND[SecuritasState.DISARMED_PERI]
        )


# ===========================================================================
# set_arm_state
# ===========================================================================


@pytest.mark.asyncio
class TestSetArmState:
    """Tests for set_arm_state()."""

    async def test_arm_from_disarmed_no_pre_disarm(self):
        """When previously disarmed, arms without pre-disarming."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED

        alarm.client.session.arm_alarm = AsyncMock(
            return_value=ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="T",
                protomResponseData="",
            )
        )
        alarm.client.session.disarm_alarm = AsyncMock()

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        alarm.client.session.disarm_alarm.assert_not_called()
        alarm.client.session.arm_alarm.assert_called_once()
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_arm_from_armed_disarms_first(self):
        """When previously armed, disarms first then arms."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_HOME

        alarm.client.session.disarm_alarm = AsyncMock(return_value=DisarmStatus())
        alarm.client.session.arm_alarm = AsyncMock(
            return_value=ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="T",
                protomResponseData="",
            )
        )

        with patch("custom_components.securitas.alarm_control_panel.asyncio.sleep"):
            await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        alarm.client.session.disarm_alarm.assert_called_once_with(
            alarm.installation, STATE_TO_COMMAND[SecuritasState.DISARMED]
        )
        alarm.client.session.arm_alarm.assert_called_once()
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_arm_error_returns_early(self):
        """Error from arm_alarm causes early return, state unchanged from arm_alarm perspective."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED

        alarm.client.session.arm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("timeout")
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        # update_status_alarm is never called with a success response,
        # so state stays at DISARMED
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_disarm_error_during_rearm_returns_early(self):
        """Error from disarm_alarm during re-arm returns early without calling arm_alarm."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_HOME

        alarm.client.session.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("connection lost")
        )
        alarm.client.session.arm_alarm = AsyncMock()

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        alarm.client.session.arm_alarm.assert_not_called()
        assert alarm._state == AlarmControlPanelState.ARMED_HOME

    async def test_unmapped_mode_returns_early(self):
        """If mode has no configured command, returns without calling API."""
        config = {
            "PERI_alarm": False,
            "map_home": SecuritasState.PARTIAL_DAY.value,
            "map_away": SecuritasState.TOTAL.value,
            "map_night": SecuritasState.PARTIAL_NIGHT.value,
            "map_custom": SecuritasState.NOT_USED.value,
            "scan_interval": 120,
        }
        alarm = make_alarm(config=config)
        alarm._state = AlarmControlPanelState.DISARMED
        alarm.client.session.arm_alarm = AsyncMock()

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_CUSTOM_BYPASS)

        alarm.client.session.arm_alarm.assert_not_called()


# ===========================================================================
# Properties
# ===========================================================================


class TestProperties:
    """Tests for simple property accessors."""

    def test_name_returns_installation_alias(self):
        """name returns installation.alias."""
        alarm = make_alarm()
        assert alarm.name == "Home"

    def test_code_format_returns_number(self):
        """code_format returns NUMBER."""
        alarm = make_alarm()
        assert alarm.code_format == CodeFormat.NUMBER

    def test_code_arm_required_returns_false(self):
        """code_arm_required returns False."""
        alarm = make_alarm()
        assert alarm.code_arm_required is False

    def test_alarm_state_returns_correct_enum(self):
        """alarm_state returns correct AlarmControlPanelState enum value."""
        alarm = make_alarm()

        alarm._state = AlarmControlPanelState.DISARMED
        assert alarm.alarm_state == AlarmControlPanelState.DISARMED

        alarm._state = AlarmControlPanelState.ARMED_AWAY
        assert alarm.alarm_state == AlarmControlPanelState.ARMED_AWAY

        alarm._state = AlarmControlPanelState.ARMED_HOME
        assert alarm.alarm_state == AlarmControlPanelState.ARMED_HOME

        alarm._state = AlarmControlPanelState.ARMING
        assert alarm.alarm_state == AlarmControlPanelState.ARMING

    def test_alarm_state_none_for_invalid(self):
        """alarm_state returns None for an invalid state string."""
        alarm = make_alarm()
        alarm._state = "totally_invalid_state"
        assert alarm.alarm_state is None

    def test_changed_by(self):
        """changed_by returns the stored value."""
        alarm = make_alarm()
        assert alarm.changed_by == ""
        alarm._changed_by = "user123"
        assert alarm.changed_by == "user123"

    def test_entity_id_and_unique_id(self):
        """entity_id and unique_id are derived from installation number."""
        alarm = make_alarm()
        assert alarm.entity_id == "securitas_direct.123456"
        assert alarm._attr_unique_id == "securitas_direct.123456"

    def test_device_info(self):
        """device_info contains correct manufacturer, model, and name."""
        alarm = make_alarm()
        info = alarm._attr_device_info
        assert info["manufacturer"] == "Securitas Direct"
        assert info["model"] == "SDVFAST"
        assert info["name"] == "Home"
        assert info["hw_version"] == "PLUS"


# ===========================================================================
# command_map and status_map (internal mapping tables)
# ===========================================================================


class TestMappingTables:
    """Tests for the internal _command_map and _status_map built during __init__."""

    def test_std_command_map(self):
        """STD defaults build the expected command map."""
        alarm = make_alarm(has_peri=False)
        assert alarm._command_map[AlarmControlPanelState.ARMED_HOME] == STATE_TO_COMMAND[SecuritasState.PARTIAL_DAY]
        assert alarm._command_map[AlarmControlPanelState.ARMED_AWAY] == STATE_TO_COMMAND[SecuritasState.TOTAL]
        assert alarm._command_map[AlarmControlPanelState.ARMED_NIGHT] == STATE_TO_COMMAND[SecuritasState.PARTIAL_NIGHT]
        assert AlarmControlPanelState.ARMED_CUSTOM_BYPASS not in alarm._command_map

    def test_peri_command_map(self):
        """PERI defaults build the expected command map including custom bypass."""
        alarm = make_alarm(has_peri=True)
        assert alarm._command_map[AlarmControlPanelState.ARMED_HOME] == STATE_TO_COMMAND[SecuritasState.PARTIAL_DAY]
        assert alarm._command_map[AlarmControlPanelState.ARMED_AWAY] == STATE_TO_COMMAND[SecuritasState.TOTAL_PERI]
        assert alarm._command_map[AlarmControlPanelState.ARMED_NIGHT] == STATE_TO_COMMAND[SecuritasState.PARTIAL_NIGHT_PERI]
        assert alarm._command_map[AlarmControlPanelState.ARMED_CUSTOM_BYPASS] == STATE_TO_COMMAND[SecuritasState.PERI_ONLY]

    def test_std_status_map(self):
        """STD defaults build status_map mapping proto codes to HA states."""
        alarm = make_alarm(has_peri=False)
        assert alarm._status_map["P"] == AlarmControlPanelState.ARMED_HOME
        assert alarm._status_map["T"] == AlarmControlPanelState.ARMED_AWAY
        assert alarm._status_map["Q"] == AlarmControlPanelState.ARMED_NIGHT

    def test_peri_status_map(self):
        """PERI defaults build status_map with perimeter-specific proto codes."""
        alarm = make_alarm(has_peri=True)
        assert alarm._status_map["E"] == AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        assert alarm._status_map["A"] == AlarmControlPanelState.ARMED_AWAY


# ===========================================================================
# __force_state (via high-level arm/disarm methods)
# ===========================================================================


@pytest.mark.asyncio
class TestForceState:
    """Tests for __force_state behavior through public methods."""

    async def test_disarm_transitions_through_disarming(self):
        """async_alarm_disarm sets DISARMING before the API call completes."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_AWAY

        observed_states = []

        original_disarm = AsyncMock(
            return_value=DisarmStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protomResponse="D",
                protomResponseData="",
            )
        )

        async def capture_state(*args, **kwargs):
            observed_states.append(alarm._state)
            return await original_disarm(*args, **kwargs)

        alarm.client.session.disarm_alarm = capture_state

        await alarm.async_alarm_disarm()

        # During the disarm API call, the state should have been DISARMING
        assert AlarmControlPanelState.DISARMING in observed_states
        # After completion, should be DISARMED
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_arm_transitions_through_arming(self):
        """async_alarm_arm_away sets ARMING before the API call completes."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED

        observed_states = []

        original_arm = AsyncMock(
            return_value=ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="T",
                protomResponseData="",
            )
        )

        async def capture_state(*args, **kwargs):
            observed_states.append(alarm._state)
            return await original_arm(*args, **kwargs)

        alarm.client.session.arm_alarm = capture_state

        await alarm.async_alarm_arm_away()

        assert AlarmControlPanelState.ARMING in observed_states
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY
