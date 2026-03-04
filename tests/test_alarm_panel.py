"""Tests for alarm_control_panel entity logic."""

from datetime import datetime, timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.alarm_control_panel import AlarmControlPanelEntityFeature
from homeassistant.components.alarm_control_panel.const import (
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.exceptions import ServiceValidationError

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    ArmStatus,
    CheckAlarmStatus,
    DisarmStatus,
    Installation,
)
from custom_components.securitas.securitas_direct_new_api.const import (
    PERI_DEFAULTS,
    STATE_TO_COMMAND,
    STD_DEFAULTS,
    SecuritasState,
)
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    ArmingExceptionError,
    SecuritasDirectError,
)
from custom_components.securitas.alarm_control_panel import (
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
            "map_vacation": defaults["map_vacation"],
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
        patch.object(SecuritasAlarm, "async_schedule_update_ha_state", MagicMock()),
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

    def test_unknown_code_sets_custom_bypass(self):
        """Unknown protomResponse code sets ARMED_CUSTOM_BYPASS."""
        alarm = make_alarm()

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

    def test_partial_night_peri_unmapped_in_peri_defaults(self):
        """protomResponse 'C' (partial_night_peri) is unmapped in PERI defaults.

        In PERI defaults map_night = partial_night (proto 'Q').
        Proto 'C' (partial_night_peri) is not assigned to any HA button
        by default, so it falls through to ARMED_CUSTOM_BYPASS.
        Users can explicitly map it to a button via the options flow.
        """
        alarm = make_alarm(has_peri=True)
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="C",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS

    def test_partial_night_maps_to_armed_night_in_peri_defaults(self):
        """protomResponse 'Q' (partial_night) maps to ARMED_NIGHT in PERI defaults.

        With PERI defaults, map_night = partial_night (proto 'Q').
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
        assert alarm._state == AlarmControlPanelState.ARMED_NIGHT


# ===========================================================================
# check_code
# ===========================================================================


class TestCheckCode:
    """Tests for _check_code()."""

    def test_empty_code_config_allows_any(self):
        """Empty code config means any code passes."""
        alarm = make_alarm(code="")
        assert alarm._check_code("1234") is True
        assert alarm._check_code(None) is True

    def test_none_code_config_allows_any(self):
        """None code config (no key) means any code passes."""
        alarm = make_alarm()
        assert alarm._check_code("9999") is True

    def test_matching_code_returns_true(self):
        """Matching code returns True."""
        alarm = make_alarm(code="1234")
        assert alarm._check_code("1234") is True

    def test_non_matching_code_raises_service_validation_error(self):
        """Non-matching code raises ServiceValidationError."""
        alarm = make_alarm(code="1234")
        with pytest.raises(ServiceValidationError):
            alarm._check_code("0000")

    def test_numeric_code_string_compared(self):
        """Numeric code string in config is compared correctly."""
        alarm = make_alarm(code="1234")
        assert alarm._check_code("1234") is True
        with pytest.raises(ServiceValidationError):
            alarm._check_code("5678")


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

    def test_std_defaults_no_vacation(self):
        """STD defaults: vacation is NOT enabled (map_vacation defaults to not_used)."""
        alarm = make_alarm(has_peri=False)
        features = alarm.supported_features
        assert not (features & AlarmControlPanelEntityFeature.ARM_VACATION)

    def test_vacation_feature_when_mapped(self):
        """Vacation feature is enabled when map_vacation is mapped to a Securitas mode."""
        config = {
            "PERI_alarm": False,
            "map_home": STD_DEFAULTS["map_home"],
            "map_away": STD_DEFAULTS["map_away"],
            "map_night": STD_DEFAULTS["map_night"],
            "map_custom": STD_DEFAULTS["map_custom"],
            "map_vacation": SecuritasState.TOTAL.value,
            "scan_interval": 120,
        }
        alarm = make_alarm(config=config)
        features = alarm.supported_features
        assert features & AlarmControlPanelEntityFeature.ARM_VACATION

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

    async def test_wrong_code_raises_service_validation_error(self):
        """Wrong code raises ServiceValidationError without calling disarm_alarm."""
        alarm = make_alarm(code="1234")
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm.client.session.disarm_alarm = AsyncMock()

        with pytest.raises(ServiceValidationError):
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
        assert args[0][0] == "Securitas: Error disarming"

    async def test_disarm_with_peri_armed_uses_combined_command(self):
        """When peri is configured and armed, tries DARM1DARMPERI."""
        alarm = make_alarm(has_peri=True)
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "A"  # total_peri = peri armed

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
            alarm.installation, "DARM1DARMPERI"
        )

    async def test_disarm_with_peri_configured_always_tries_combined(self):
        """When peri is configured, always tries DARM1DARMPERI regardless of proto code."""
        alarm = make_alarm(has_peri=True)
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"  # total = no peri currently

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
            alarm.installation, "DARM1DARMPERI"
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
        # set_arm_state checks _last_status (set by __force_state) for prior state
        alarm._state = AlarmControlPanelState.ARMED_HOME
        alarm._last_status = AlarmControlPanelState.ARMED_HOME

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

    async def test_disarm_error_during_rearm_continues_to_arm(self):
        """Error from disarm_alarm during re-arm logs warning and continues to arm."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_HOME
        alarm._last_status = AlarmControlPanelState.ARMED_HOME

        alarm.client.session.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("connection lost")
        )
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

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        alarm.client.session.arm_alarm.assert_called_once()
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

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

    def test_code_format_none_when_no_code(self):
        """code_format is None when no code is configured."""
        alarm = make_alarm()
        assert alarm.code_format is None

    def test_code_format_number_when_numeric_code(self):
        """code_format is NUMBER when a numeric code is configured."""
        alarm = make_alarm(code="1234")
        assert alarm.code_format == CodeFormat.NUMBER

    def test_code_format_text_when_alpha_code(self):
        """code_format is TEXT when a non-numeric code is configured."""
        alarm = make_alarm(code="abcd")
        assert alarm.code_format == CodeFormat.TEXT

    def test_code_arm_required_false_when_no_code(self):
        """code_arm_required is False when no code is configured."""
        alarm = make_alarm()
        assert alarm.code_arm_required is False

    def test_code_arm_required_from_config(self):
        """code_arm_required reflects CONF_CODE_ARM_REQUIRED config when code is set."""
        alarm = make_alarm(code="1234")
        # Default is False when not in config
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
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_HOME]
            == STATE_TO_COMMAND[SecuritasState.PARTIAL_DAY]
        )
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_AWAY]
            == STATE_TO_COMMAND[SecuritasState.TOTAL]
        )
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_NIGHT]
            == STATE_TO_COMMAND[SecuritasState.PARTIAL_NIGHT]
        )
        assert AlarmControlPanelState.ARMED_CUSTOM_BYPASS not in alarm._command_map

    def test_peri_command_map(self):
        """PERI defaults build the expected command map including custom bypass."""
        alarm = make_alarm(has_peri=True)
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_HOME]
            == STATE_TO_COMMAND[SecuritasState.PARTIAL_DAY]
        )
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_AWAY]
            == STATE_TO_COMMAND[SecuritasState.TOTAL_PERI]
        )
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_NIGHT]
            == STATE_TO_COMMAND[SecuritasState.PARTIAL_NIGHT]
        )
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_CUSTOM_BYPASS]
            == STATE_TO_COMMAND[SecuritasState.PERI_ONLY]
        )

    def test_std_status_map(self):
        """STD defaults build status_map mapping proto codes to HA states."""
        alarm = make_alarm(has_peri=False)
        assert alarm._status_map["P"] == AlarmControlPanelState.ARMED_HOME
        assert alarm._status_map["T"] == AlarmControlPanelState.ARMED_AWAY
        assert alarm._status_map["Q"] == AlarmControlPanelState.ARMED_NIGHT

    def test_peri_status_map(self):
        """PERI defaults build status_map with correct proto code mappings."""
        alarm = make_alarm(has_peri=True)
        assert alarm._status_map["P"] == AlarmControlPanelState.ARMED_HOME
        assert alarm._status_map["A"] == AlarmControlPanelState.ARMED_AWAY
        assert alarm._status_map["Q"] == AlarmControlPanelState.ARMED_NIGHT
        assert alarm._status_map["E"] == AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        # "C" (partial_night_peri) is not mapped by default
        assert "C" not in alarm._status_map


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

    async def test_disarm_sets_operation_in_progress_during_api_call(self):
        """async_alarm_disarm sets _operation_in_progress=True while the API call runs."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_AWAY

        observed_flags = []

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

        async def capture_flag(*args, **kwargs):
            observed_flags.append(alarm._operation_in_progress)
            return await original_disarm(*args, **kwargs)

        alarm.client.session.disarm_alarm = capture_flag

        assert alarm._operation_in_progress is False
        await alarm.async_alarm_disarm()

        assert True in observed_flags, (
            "_operation_in_progress was never True during API call"
        )
        assert alarm._operation_in_progress is False

    async def test_arm_sets_operation_in_progress_during_api_call(self):
        """set_arm_state sets _operation_in_progress=True while the API call runs."""
        alarm = make_alarm()

        observed_flags = []

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

        async def capture_flag(*args, **kwargs):
            observed_flags.append(alarm._operation_in_progress)
            return await original_arm(*args, **kwargs)

        alarm.client.session.arm_alarm = capture_flag

        assert alarm._operation_in_progress is False
        await alarm.async_alarm_arm_away()

        assert True in observed_flags, (
            "_operation_in_progress was never True during API call"
        )
        assert alarm._operation_in_progress is False

    async def test_operation_in_progress_cleared_after_disarm_error(self):
        """_operation_in_progress is cleared even when disarm raises SecuritasDirectError."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm.client.session.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("API error")
        )

        await alarm.async_alarm_disarm()

        assert alarm._operation_in_progress is False

    async def test_operation_in_progress_cleared_after_arm_error(self):
        """_operation_in_progress is cleared even when arm raises SecuritasDirectError."""
        alarm = make_alarm()
        alarm.client.session.arm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("API error")
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        assert alarm._operation_in_progress is False


# ===========================================================================
# get_arm_state
# ===========================================================================


@pytest.mark.asyncio
class TestGetArmState:
    """Tests for get_arm_state()."""

    async def test_calls_check_alarm_then_check_alarm_status(self):
        """get_arm_state calls check_alarm then check_alarm_status."""
        alarm = make_alarm()
        alarm.client.session.check_alarm = AsyncMock(return_value="ref-abc")
        expected_status = CheckAlarmStatus(
            operation_status="OK",
            message="Panel armed",
            status="",
            InstallationNumer="123456",
            protomResponse="T",
            protomResponseData="",
        )
        alarm.client.session.check_alarm_status = AsyncMock(
            return_value=expected_status
        )

        with patch("custom_components.securitas.alarm_control_panel.asyncio.sleep"):
            await alarm.get_arm_state()

        alarm.client.session.check_alarm.assert_called_once_with(alarm.installation)
        alarm.client.session.check_alarm_status.assert_called_once_with(
            alarm.installation, "ref-abc"
        )

    async def test_returns_alarm_status(self):
        """get_arm_state returns the CheckAlarmStatus from the API."""
        alarm = make_alarm()
        alarm.client.session.check_alarm = AsyncMock(return_value="ref-xyz")
        expected_status = CheckAlarmStatus(
            operation_status="OK",
            message="Disarmed",
            status="",
            InstallationNumer="123456",
            protomResponse="D",
            protomResponseData="some-data",
        )
        alarm.client.session.check_alarm_status = AsyncMock(
            return_value=expected_status
        )

        with patch("custom_components.securitas.alarm_control_panel.asyncio.sleep"):
            result = await alarm.get_arm_state()

        assert result is expected_status
        assert result.protomResponse == "D"
        assert result.message == "Disarmed"


# ===========================================================================
# async_will_remove_from_hass
# ===========================================================================


@pytest.mark.asyncio
class TestAsyncWillRemoveFromHass:
    """Tests for async_will_remove_from_hass()."""

    async def test_calls_unsub_when_exists(self):
        """Calls the unsub callable when it exists."""
        alarm = make_alarm()
        unsub_mock = MagicMock()
        alarm._update_unsub = unsub_mock

        await alarm.async_will_remove_from_hass()

        unsub_mock.assert_called_once()

    async def test_handles_none_unsub_gracefully(self):
        """Handles None _update_unsub gracefully (no crash)."""
        alarm = make_alarm()
        alarm._update_unsub = None

        # Should not raise
        await alarm.async_will_remove_from_hass()

    async def test_unsubscribes_mobile_action_listener(self):
        """Calls _mobile_action_unsub() when it is set."""
        alarm = make_alarm()
        mobile_unsub_mock = MagicMock()
        alarm._mobile_action_unsub = mobile_unsub_mock

        await alarm.async_will_remove_from_hass()

        mobile_unsub_mock.assert_called_once()

    async def test_handles_none_mobile_action_unsub_gracefully(self):
        """Handles None _mobile_action_unsub gracefully (no crash)."""
        alarm = make_alarm()
        alarm._mobile_action_unsub = None

        # Should not raise
        await alarm.async_will_remove_from_hass()


# ===========================================================================
# async_update_status
# ===========================================================================


@pytest.mark.asyncio
class TestAsyncUpdateStatus:
    """Tests for async_update_status()."""

    async def test_success_calls_update_overview_and_writes_state(self):
        """Success: calls update_overview, update_status_alarm, writes HA state."""
        alarm = make_alarm()
        status = CheckAlarmStatus(
            operation_status="OK",
            message="Armed total",
            status="",
            InstallationNumer="123456",
            protomResponse="T",
            protomResponseData="",
        )
        alarm.client.update_overview = AsyncMock(return_value=status)

        await alarm.async_update_status()

        alarm.client.update_overview.assert_called_once_with(alarm.installation)
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY
        alarm.async_write_ha_state.assert_called_once()

    async def test_success_with_now_parameter(self):
        """async_update_status accepts an optional now parameter (used by timer)."""
        alarm = make_alarm()
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="D",
            protomResponseData="",
        )
        alarm.client.update_overview = AsyncMock(return_value=status)

        await alarm.async_update_status(now="2024-01-01T00:00:00")

        alarm.client.update_overview.assert_called_once_with(alarm.installation)
        assert alarm._state == AlarmControlPanelState.DISARMED
        alarm.async_write_ha_state.assert_called_once()

    async def test_error_logged_no_ha_state_write(self):
        """Error: SecuritasDirectError logged, doesn't write HA state."""
        alarm = make_alarm()
        alarm.client.update_overview = AsyncMock(
            side_effect=SecuritasDirectError("Network error")
        )

        await alarm.async_update_status()

        alarm.client.update_overview.assert_called_once()
        # async_write_ha_state should NOT be called on error
        alarm.async_write_ha_state.assert_not_called()
        # State should remain at initial DISARMED
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_skips_poll_when_operation_in_progress(self):
        """Status poll is skipped when _operation_in_progress is True."""
        alarm = make_alarm()
        alarm.client.update_overview = AsyncMock()
        alarm._operation_in_progress = True

        await alarm.async_update_status()

        alarm.client.update_overview.assert_not_called()
        alarm.async_write_ha_state.assert_not_called()

    async def test_polls_when_operation_not_in_progress(self):
        """Status poll proceeds normally when _operation_in_progress is False."""
        alarm = make_alarm()
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="D",
            protomResponseData="",
        )
        alarm.client.update_overview = AsyncMock(return_value=status)
        alarm._operation_in_progress = False

        await alarm.async_update_status()

        alarm.client.update_overview.assert_called_once()


# ===========================================================================
# _check_code_for_arm_if_required
# ===========================================================================


class TestCheckCodeForArmIfRequired:
    """Tests for _check_code_for_arm_if_required()."""

    def test_no_code_configured_returns_true(self):
        """No code configured: returns True regardless of input."""
        alarm = make_alarm()  # no code
        assert alarm._check_code_for_arm_if_required(None) is True
        assert alarm._check_code_for_arm_if_required("1234") is True

    def test_code_configured_but_arm_required_false(self):
        """Code configured but code_arm_required=False: returns True."""
        alarm = make_alarm(code="1234")
        # code_arm_required defaults to False
        assert alarm._attr_code_arm_required is False
        assert alarm._check_code_for_arm_if_required(None) is True
        assert alarm._check_code_for_arm_if_required("wrong") is True

    def test_code_configured_arm_required_correct_code(self):
        """Code configured AND code_arm_required=True with correct code: returns True."""
        config = {
            "PERI_alarm": False,
            "map_home": "partial_day",
            "map_away": "total",
            "map_night": "partial_night",
            "map_custom": "not_used",
            "scan_interval": 120,
            "code": "5678",
            "code_arm_required": True,
        }
        alarm = make_alarm(config=config)
        assert alarm._check_code_for_arm_if_required("5678") is True

    def test_code_configured_arm_required_wrong_code(self):
        """Code configured AND code_arm_required=True with wrong code: raises ServiceValidationError."""
        config = {
            "PERI_alarm": False,
            "map_home": "partial_day",
            "map_away": "total",
            "map_night": "partial_night",
            "map_custom": "not_used",
            "scan_interval": 120,
            "code": "5678",
            "code_arm_required": True,
        }
        alarm = make_alarm(config=config)
        with pytest.raises(ServiceValidationError):
            alarm._check_code_for_arm_if_required("0000")


# ===========================================================================
# async_alarm_arm_home / arm_night / arm_custom_bypass
# ===========================================================================


@pytest.mark.asyncio
class TestArmMethods:
    """Tests for async_alarm_arm_home, async_alarm_arm_night, async_alarm_arm_custom_bypass."""

    async def test_arm_home_passes_armed_home(self):
        """async_alarm_arm_home calls set_arm_state with ARMED_HOME."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED

        alarm.client.session.arm_alarm = AsyncMock(
            return_value=ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="P",
                protomResponseData="",
            )
        )

        await alarm.async_alarm_arm_home()

        alarm.client.session.arm_alarm.assert_called_once()
        # Verify the command corresponds to ARMED_HOME mapping
        call_args = alarm.client.session.arm_alarm.call_args
        assert call_args[0][1] == alarm._command_map[AlarmControlPanelState.ARMED_HOME]
        assert alarm._state == AlarmControlPanelState.ARMED_HOME

    async def test_arm_night_passes_armed_night(self):
        """async_alarm_arm_night calls set_arm_state with ARMED_NIGHT."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED

        alarm.client.session.arm_alarm = AsyncMock(
            return_value=ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="Q",
                protomResponseData="",
            )
        )

        await alarm.async_alarm_arm_night()

        alarm.client.session.arm_alarm.assert_called_once()
        call_args = alarm.client.session.arm_alarm.call_args
        assert call_args[0][1] == alarm._command_map[AlarmControlPanelState.ARMED_NIGHT]
        assert alarm._state == AlarmControlPanelState.ARMED_NIGHT

    async def test_arm_custom_bypass_passes_armed_custom_bypass(self):
        """async_alarm_arm_custom_bypass calls set_arm_state with ARMED_CUSTOM_BYPASS."""
        alarm = make_alarm(has_peri=True)  # PERI config maps custom bypass
        alarm._state = AlarmControlPanelState.DISARMED

        alarm.client.session.arm_alarm = AsyncMock(
            return_value=ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="E",
                protomResponseData="",
            )
        )

        await alarm.async_alarm_arm_custom_bypass()

        alarm.client.session.arm_alarm.assert_called_once()
        call_args = alarm.client.session.arm_alarm.call_args
        assert (
            call_args[0][1]
            == alarm._command_map[AlarmControlPanelState.ARMED_CUSTOM_BYPASS]
        )
        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS

    async def test_arm_vacation_passes_armed_vacation(self):
        """async_alarm_arm_vacation calls set_arm_state with ARMED_VACATION."""
        config = {
            "PERI_alarm": False,
            "map_home": STD_DEFAULTS["map_home"],
            "map_away": SecuritasState.NOT_USED.value,
            "map_night": STD_DEFAULTS["map_night"],
            "map_custom": STD_DEFAULTS["map_custom"],
            "map_vacation": SecuritasState.TOTAL.value,
            "scan_interval": 120,
        }
        alarm = make_alarm(config=config)
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

        await alarm.async_alarm_arm_vacation()

        alarm.client.session.arm_alarm.assert_called_once()
        call_args = alarm.client.session.arm_alarm.call_args
        assert (
            call_args[0][1] == alarm._command_map[AlarmControlPanelState.ARMED_VACATION]
        )
        assert alarm._state == AlarmControlPanelState.ARMED_VACATION

    async def test_each_arm_method_transitions_through_arming(self):
        """All arm methods set ARMING state via __force_state before the API call."""
        alarm = make_alarm(has_peri=True)
        alarm._state = AlarmControlPanelState.DISARMED

        observed_states = []

        original_arm = AsyncMock(
            return_value=ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="P",
                protomResponseData="",
            )
        )

        async def capture_state(*args, **kwargs):
            observed_states.append(alarm._state)
            return await original_arm(*args, **kwargs)

        alarm.client.session.arm_alarm = capture_state

        await alarm.async_alarm_arm_home()

        assert AlarmControlPanelState.ARMING in observed_states


# ===========================================================================
# Force-arm context
# ===========================================================================


class TestForceArmContext:
    """Tests for the force-arm exception handling flow."""

    def _make_arming_exception(
        self,
        ref_id: str = "ref-exc-123",
        suid: str = "123456VI4ucRGS5Q==",
        exceptions: list[dict] | None = None,
    ) -> ArmingExceptionError:
        if exceptions is None:
            exceptions = [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}]
        return ArmingExceptionError(ref_id, suid, exceptions)

    async def test_arming_exception_stores_force_context(self):
        """ArmingExceptionError during arm stores force context and reverts state."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_status = AlarmControlPanelState.DISARMED

        exc = self._make_arming_exception()
        alarm.client.session.arm_alarm = AsyncMock(side_effect=exc)

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # State should revert
        assert alarm._state == AlarmControlPanelState.DISARMED
        # Force context should be stored
        assert alarm._force_context is not None
        assert alarm._force_context["reference_id"] == "ref-exc-123"
        assert alarm._force_context["suid"] == "123456VI4ucRGS5Q=="
        assert alarm._force_context["mode"] == AlarmControlPanelState.ARMED_HOME
        # Attributes should expose exception info
        assert alarm._attr_extra_state_attributes["force_arm_available"] is True
        assert "Kitchen Door" in alarm._attr_extra_state_attributes["arm_exceptions"]

    async def test_widget_re_arm_does_not_force(self):
        """Re-arming via the widget does NOT auto-force — force context is ignored."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._force_context = {
            "reference_id": "ref-exc-123",
            "suid": "123456VI4ucRGS5Q==",
            "mode": AlarmControlPanelState.ARMED_HOME,
            "exceptions": [{"status": "0", "deviceType": "MG", "alias": "Door"}],
            "created_at": datetime.now(),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True
        alarm._attr_extra_state_attributes["arm_exceptions"] = ["Door"]

        alarm.client.session.arm_alarm = AsyncMock(
            return_value=ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="P",
                protomResponseData="",
            )
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Force params should NOT have been passed (widget doesn't force)
        call_kwargs = alarm.client.session.arm_alarm.call_args[1]
        assert "force_arming_remote_id" not in call_kwargs
        assert "suid" not in call_kwargs

    async def test_force_context_survives_immediate_status_refresh(self):
        """async_update_status does NOT clear recently-set force context.

        HA triggers an immediate status refresh after every service call.
        The force context must survive until the user has a chance to re-arm.
        """
        alarm = make_alarm()
        alarm._force_context = {
            "reference_id": "ref-123",
            "suid": "suid-123",
            "mode": AlarmControlPanelState.ARMED_HOME,
            "exceptions": [],
            "created_at": datetime.now(),  # Just set — recent
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True
        alarm._attr_extra_state_attributes["arm_exceptions"] = ["Door"]

        alarm.client.update_overview = AsyncMock(
            return_value=CheckAlarmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="D",
                protomResponseData="",
            )
        )

        await alarm.async_update_status()

        # Force context should STILL be present (age < scan interval)
        assert alarm._force_context is not None
        assert alarm._attr_extra_state_attributes.get("force_arm_available") is True

    async def test_force_context_cleared_on_expired_status_refresh(self):
        """async_update_status clears force context after scan interval expires."""
        alarm = make_alarm()
        alarm._force_context = {
            "reference_id": "ref-123",
            "suid": "suid-123",
            "mode": AlarmControlPanelState.ARMED_HOME,
            "exceptions": [],
            "created_at": datetime.now() - timedelta(seconds=300),  # Old
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True
        alarm._attr_extra_state_attributes["arm_exceptions"] = ["Door"]

        alarm.client.update_overview = AsyncMock(
            return_value=CheckAlarmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="D",
                protomResponseData="",
            )
        )

        await alarm.async_update_status()

        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        assert "arm_exceptions" not in alarm._attr_extra_state_attributes

    async def test_force_context_cleared_on_successful_arm(self):
        """Successful arm without force context does not leave stale context."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._force_context = None

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

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        assert alarm._force_context is None
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_arming_exception_sends_persistent_notification(self):
        """ArmingExceptionError triggers persistent notification."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_status = AlarmControlPanelState.DISARMED

        exc = self._make_arming_exception()
        alarm.client.session.arm_alarm = AsyncMock(side_effect=exc)

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Verify persistent notification was created
        alarm.hass.async_create_task.assert_called()

    async def test_arming_exception_notifies_configured_group(self):
        """ArmingExceptionError sends to configured notify group."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_status = AlarmControlPanelState.DISARMED

        exc = self._make_arming_exception()
        alarm.client.session.arm_alarm = AsyncMock(side_effect=exc)

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Should have two async_create_task calls: persistent_notification + notify
        assert alarm.hass.async_create_task.call_count == 2

    async def test_arming_exception_no_notify_group_only_persistent(self):
        """Without notify_group configured, only persistent notification fires."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_status = AlarmControlPanelState.DISARMED

        exc = self._make_arming_exception()
        alarm.client.session.arm_alarm = AsyncMock(side_effect=exc)

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Only persistent notification
        assert alarm.hass.async_create_task.call_count == 1

    async def test_async_force_arm_uses_stored_context(self):
        """async_force_arm consumes stored context and passes force params."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._force_context = {
            "reference_id": "ref-exc-456",
            "suid": "suid-456",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"status": "0", "deviceType": "MG", "alias": "Window"}],
            "created_at": datetime.now(),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True
        alarm._attr_extra_state_attributes["arm_exceptions"] = ["Window"]

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

        await alarm.async_force_arm()

        # Should have called arm_alarm with force params
        call_kwargs = alarm.client.session.arm_alarm.call_args[1]
        assert call_kwargs["force_arming_remote_id"] == "ref-exc-456"
        assert call_kwargs["suid"] == "suid-456"
        # Force arm always bypasses sensors — state must be ARMED_CUSTOM_BYPASS
        # regardless of the proto code the Securitas API returns (which is the
        # same as a normal arm and would otherwise map to the original mode).
        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        assert alarm._was_force_armed is True
        # Force context should be cleared after consumption
        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        assert "arm_exceptions" not in alarm._attr_extra_state_attributes

    async def test_async_force_arm_no_context_does_nothing(self):
        """async_force_arm with no stored context does nothing."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._force_context = None

        alarm.client.session.arm_alarm = AsyncMock()

        await alarm.async_force_arm()

        alarm.client.session.arm_alarm.assert_not_called()
        assert alarm._state == AlarmControlPanelState.DISARMED

    def test_mobile_action_force_arm_dispatches_task(self):
        """SECURITAS_FORCE_ARM_<num> mobile action dispatches async_force_arm."""
        alarm = make_alarm()
        alarm._force_context = {
            "reference_id": "ref-mobile",
            "suid": "suid-mobile",
            "mode": AlarmControlPanelState.ARMED_HOME,
            "exceptions": [{"alias": "Door"}],
            "created_at": datetime.now(),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True

        event = MagicMock()
        event.data = {"action": f"SECURITAS_FORCE_ARM_{alarm.installation.number}"}

        alarm._handle_mobile_action(event)

        alarm.hass.async_create_task.assert_called_once()

    def test_mobile_action_cancel_dispatches_task(self):
        """SECURITAS_CANCEL_FORCE_ARM_<num> mobile action dispatches async_force_arm_cancel."""
        alarm = make_alarm()
        alarm._force_context = {
            "reference_id": "ref-mobile",
            "suid": "suid-mobile",
            "mode": AlarmControlPanelState.ARMED_HOME,
            "exceptions": [{"alias": "Door"}],
            "created_at": datetime.now(),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True

        event = MagicMock()
        event.data = {
            "action": f"SECURITAS_CANCEL_FORCE_ARM_{alarm.installation.number}"
        }

        alarm._handle_mobile_action(event)

        # _handle_mobile_action creates a task — verify the task was dispatched
        alarm.hass.async_create_task.assert_called_once()

    def test_mobile_action_unknown_does_nothing(self):
        """Unrecognised mobile action does not affect alarm state."""
        alarm = make_alarm()
        alarm._force_context = None

        event = MagicMock()
        event.data = {"action": "SOME_OTHER_APP_ACTION"}

        alarm._handle_mobile_action(event)

        alarm.hass.async_create_task.assert_not_called()
        assert alarm._force_context is None

    def test_mobile_action_wrong_installation_does_nothing(self):
        """Mobile action for a different installation number is ignored."""
        alarm = make_alarm()
        alarm._force_context = {
            "reference_id": "ref-other",
            "suid": "suid-other",
            "mode": AlarmControlPanelState.ARMED_HOME,
            "exceptions": [],
            "created_at": datetime.now(),
        }

        event = MagicMock()
        event.data = {"action": "SECURITAS_FORCE_ARM_999999"}  # wrong installation

        alarm._handle_mobile_action(event)

        alarm.hass.async_create_task.assert_not_called()
        assert alarm._force_context is not None  # untouched


# ===========================================================================
# force_arm_cancel service
# ===========================================================================


@pytest.mark.asyncio
class TestForceArmCancel:
    """Tests for the securitas.force_arm_cancel entity service."""

    async def test_cancel_clears_context_and_dismisses_notification(self):
        """force_arm_cancel clears context, dismisses notification, writes state."""
        alarm = make_alarm()
        alarm._force_context = {
            "reference_id": "ref-cancel",
            "suid": "suid-cancel",
            "mode": AlarmControlPanelState.ARMED_HOME,
            "exceptions": [{"alias": "Window"}],
            "created_at": datetime.now(),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True
        alarm._attr_extra_state_attributes["arm_exceptions"] = ["Window"]

        await alarm.async_force_arm_cancel()

        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        assert "arm_exceptions" not in alarm._attr_extra_state_attributes
        alarm.async_write_ha_state.assert_called()

    async def test_cancel_no_context_does_nothing(self):
        """force_arm_cancel with no stored context logs warning and returns."""
        alarm = make_alarm()
        alarm._force_context = None
        alarm._state = AlarmControlPanelState.DISARMED

        await alarm.async_force_arm_cancel()

        assert alarm._force_context is None
        assert alarm._state == AlarmControlPanelState.DISARMED


# ===========================================================================
# Multi-step arm commands (ARMNIGHT1PERI1 → ARMNIGHT1 + PERI1)
# ===========================================================================


def _night_peri_config():
    """Config with map_night = partial_night_peri (triggers multi-step arm)."""
    return {
        "PERI_alarm": True,
        "map_home": PERI_DEFAULTS["map_home"],
        "map_away": PERI_DEFAULTS["map_away"],
        "map_night": SecuritasState.PARTIAL_NIGHT_PERI.value,
        "map_custom": PERI_DEFAULTS["map_custom"],
        "scan_interval": 120,
    }


@pytest.mark.asyncio
class TestCompoundArmCommands:
    """Tests for compound arm command auto-detection (try single, fall back to multi-step)."""

    async def test_compound_tries_single_first_then_multi_step(self):
        """First attempt sends compound command; on failure, splits to multi-step."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.DISARMED

        calls = []

        async def track_arm(installation, command, **kwargs):
            calls.append(command)
            if command == "ARMNIGHT1PERI1":
                raise SecuritasDirectError("does not exist")
            proto = "Q" if command == "ARMNIGHT1" else "C"
            return ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse=proto,
                protomResponseData="",
            )

        alarm.client.session.arm_alarm = track_arm

        await alarm.async_alarm_arm_night()

        # First tried compound, then fell back to two steps
        assert calls == ["ARMNIGHT1PERI1", "ARMNIGHT1", "PERI1"]
        assert alarm._use_multi_step is True
        assert alarm._state == AlarmControlPanelState.ARMED_NIGHT

    async def test_compound_succeeds_as_single_command(self):
        """Panel that supports compound commands sends only one call."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.DISARMED

        alarm.client.session.arm_alarm = AsyncMock(
            return_value=ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="C",
                protomResponseData="",
            )
        )

        await alarm.async_alarm_arm_night()

        alarm.client.session.arm_alarm.assert_called_once_with(
            alarm.installation, "ARMNIGHT1PERI1"
        )
        assert alarm._use_multi_step is False
        assert alarm._state == AlarmControlPanelState.ARMED_NIGHT

    async def test_multi_step_remembered_skips_single_attempt(self):
        """Once _use_multi_step is set, compound commands go straight to steps."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._use_multi_step = True

        calls = []

        async def track_arm(installation, command, **kwargs):
            calls.append((command, kwargs))
            proto = "Q" if command == "ARMNIGHT1" else "C"
            return ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse=proto,
                protomResponseData="",
            )

        alarm.client.session.arm_alarm = track_arm

        await alarm.async_alarm_arm_night()

        # Skipped the compound attempt, went straight to steps
        assert len(calls) == 2
        assert calls[0][0] == "ARMNIGHT1"
        assert calls[1][0] == "PERI1"

    async def test_force_params_passed_to_all_steps(self):
        """Force arming params are passed to every step.

        Both interior and perimeter sensors can trigger ArmingExceptionError,
        so force params must reach whichever step originally failed.
        """
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._use_multi_step = True

        calls = []

        async def track_arm(installation, command, **kwargs):
            calls.append((command, kwargs))
            return ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="C",
                protomResponseData="",
            )

        alarm.client.session.arm_alarm = track_arm

        await alarm.set_arm_state(
            AlarmControlPanelState.ARMED_NIGHT,
            force_arming_remote_id="ref-123",
            suid="suid-456",
        )

        expected_params = {
            "force_arming_remote_id": "ref-123",
            "suid": "suid-456",
        }
        assert len(calls) == 2
        assert calls[0][1] == expected_params
        assert calls[1][1] == expected_params

    async def test_multi_step_second_step_fails_reflects_partial_state(self):
        """If step 1 succeeds but step 2 fails, state reflects partial arming."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_status = AlarmControlPanelState.DISARMED
        alarm._use_multi_step = True
        alarm._notify_error = MagicMock()

        call_count = 0

        async def arm_side_effect(installation, command, **kwargs):
            nonlocal call_count
            call_count += 1
            if command == "ARMNIGHT1":
                return ArmStatus(
                    operation_status="OK",
                    message="",
                    status="",
                    InstallationNumer="123456",
                    protomResponse="Q",
                    protomResponseData="",
                )
            raise SecuritasDirectError("PERI1 failed")

        alarm.client.session.arm_alarm = arm_side_effect

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        assert call_count == 2
        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        alarm.async_write_ha_state.assert_called()
        alarm._notify_error.assert_called_once()

    async def test_both_single_and_multi_step_fail_notifies(self):
        """When compound fails and multi-step also fails, error is reported."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_status = AlarmControlPanelState.DISARMED
        alarm._notify_error = MagicMock()

        alarm.client.session.arm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("API error")
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        # Tried compound, then multi-step first step also failed
        assert alarm.client.session.arm_alarm.call_count == 2
        assert alarm._use_multi_step is True
        alarm._notify_error.assert_called_once()
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_non_compound_command_sent_directly(self):
        """Non-compound commands (e.g. ARMNIGHT1) are sent as-is."""
        alarm = make_alarm(has_peri=True)
        alarm._state = AlarmControlPanelState.DISARMED

        alarm.client.session.arm_alarm = AsyncMock(
            return_value=ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="Q",
                protomResponseData="",
            )
        )

        await alarm.async_alarm_arm_night()

        alarm.client.session.arm_alarm.assert_called_once()
        assert alarm.client.session.arm_alarm.call_args[0][1] == "ARMNIGHT1"

    async def test_409_does_not_trigger_multi_step_arm_fallback(self):
        """409 (server busy) should re-raise, not switch to multi-step."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_status = AlarmControlPanelState.DISARMED
        alarm._notify_error = MagicMock()

        alarm.client.session.arm_alarm = AsyncMock(
            side_effect=SecuritasDirectError(
                "alarm-manager.alarm_process_error", http_status=409
            )
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        # Should only try ARMNIGHT1PERI1 once — NOT fall back to multi-step
        alarm.client.session.arm_alarm.assert_called_once_with(
            alarm.installation, "ARMNIGHT1PERI1"
        )
        assert alarm._use_multi_step is False

    async def test_unsupported_enum_triggers_multi_step_and_succeeds(self):
        """GraphQL enum error triggers multi-step fallback which succeeds."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.DISARMED

        calls = []

        async def arm_side_effect(installation, command, **kwargs):
            calls.append(command)
            if command == "ARMNIGHT1PERI1":
                raise SecuritasDirectError(
                    'Value "ARMNIGHT1PERI1" does not exist in "ArmCodeRequest" enum.'
                )
            proto = "Q" if command == "ARMNIGHT1" else "C"
            return ArmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse=proto,
                protomResponseData="",
            )

        alarm.client.session.arm_alarm = arm_side_effect

        await alarm.async_alarm_arm_night()

        assert calls == ["ARMNIGHT1PERI1", "ARMNIGHT1", "PERI1"]
        assert alarm._state == AlarmControlPanelState.ARMED_NIGHT
        assert alarm._use_multi_step is True


# ===========================================================================
# Dynamic disarm command (based on current state and auto-detection)
# ===========================================================================


@pytest.mark.asyncio
class TestDynamicDisarm:
    """Tests for dynamic disarm command selection."""

    async def test_peri_armed_tries_combined_first(self):
        """With peri armed, tries DARM1DARMPERI first."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "C"  # partial_night_peri = peri armed
        alarm._state = AlarmControlPanelState.ARMED_NIGHT

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
            alarm.installation, "DARM1DARMPERI"
        )
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_peri_armed_falls_back_to_darm1(self):
        """When DARM1DARMPERI fails, falls back to DARM1 without setting _use_multi_step."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"  # total_peri = peri armed
        alarm._state = AlarmControlPanelState.ARMED_AWAY

        calls = []

        async def disarm_side_effect(installation, command):
            calls.append(command)
            if command == "DARM1DARMPERI":
                raise SecuritasDirectError("404 not found")
            return DisarmStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protomResponse="D",
                protomResponseData="",
            )

        alarm.client.session.disarm_alarm = disarm_side_effect

        await alarm.async_alarm_disarm()

        assert calls == ["DARM1DARMPERI", "DARM1"]
        # Disarm does NOT set _use_multi_step — only arm failures should
        assert alarm._use_multi_step is False
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_peri_not_armed_still_tries_combined(self):
        """With peri configured but not currently armed, still tries DARM1DARMPERI.

        This ensures disarm during an in-progress arm-with-perimeter works
        correctly even when _last_proto_code hasn't been updated yet.
        """
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "Q"  # partial_night = no peri
        alarm._state = AlarmControlPanelState.ARMED_NIGHT

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
            alarm.installation, "DARM1DARMPERI"
        )

    async def test_no_peri_config_uses_darm1(self):
        """Without peri config, always sends DARM1."""
        alarm = make_alarm(has_peri=False)
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._notify_error = MagicMock()

        alarm.client.session.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("API down")
        )

        await alarm.async_alarm_disarm()

        alarm.client.session.disarm_alarm.assert_called_once_with(
            alarm.installation, "DARM1"
        )

    async def test_multi_step_known_skips_combined(self):
        """With _use_multi_step set, peri armed goes straight to DARM1."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "E"  # peri_only
        alarm._state = AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        alarm._use_multi_step = True

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
            alarm.installation, "DARM1"
        )

    async def test_both_disarm_attempts_fail(self):
        """When both DARM1DARMPERI and DARM1 fail, error is reported."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "B"  # partial_day_peri
        alarm._state = AlarmControlPanelState.ARMED_HOME
        alarm._last_status = AlarmControlPanelState.ARMED_HOME
        alarm._notify_error = MagicMock()

        alarm.client.session.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("permanent failure")
        )

        await alarm.async_alarm_disarm()

        assert alarm.client.session.disarm_alarm.call_count == 2
        alarm._notify_error.assert_called_once()
        assert alarm._state == AlarmControlPanelState.ARMED_HOME

    async def test_409_does_not_trigger_darm1_fallback(self):
        """409 (server busy) should re-raise, not fall back to DARM1."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"  # total_peri = peri armed
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_status = AlarmControlPanelState.ARMED_AWAY
        alarm._notify_error = MagicMock()

        alarm.client.session.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError(
                "alarm-manager.alarm_process_error", http_status=409
            )
        )

        await alarm.async_alarm_disarm()

        # Should only try DARM1DARMPERI once — NOT fall back to DARM1
        alarm.client.session.disarm_alarm.assert_called_once_with(
            alarm.installation, "DARM1DARMPERI"
        )
        assert alarm._use_multi_step is False
        # Error notification should show clean message, not full args dump
        alarm._notify_error.assert_called_once()
        _, msg = alarm._notify_error.call_args[0]
        assert "alarm-manager.alarm_process_error" in msg
        assert "headers" not in msg.lower()

    async def test_disarm_error_notification_is_short(self):
        """Error notification should show just the message, not the full error tuple."""
        alarm = make_alarm(has_peri=False)
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_status = AlarmControlPanelState.ARMED_AWAY
        alarm._notify_error = MagicMock()

        alarm.client.session.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError(
                "API error message",
                {"response": "data"},
                {"auth": "secret-token"},
                {"query": "mutation"},
            )
        )

        await alarm.async_alarm_disarm()

        alarm._notify_error.assert_called_once()
        _, msg = alarm._notify_error.call_args[0]
        assert msg == "API error message"
        assert "secret-token" not in msg

    async def test_rearm_disarm_with_peri_armed(self):
        """Pre-disarm during re-arm uses dynamic disarm with fallback."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "B"  # partial_day_peri
        alarm._state = AlarmControlPanelState.ARMED_HOME
        alarm._last_status = AlarmControlPanelState.ARMED_HOME

        disarm_calls = []

        async def track_disarm(installation, command):
            disarm_calls.append(command)
            if command == "DARM1DARMPERI":
                raise SecuritasDirectError("404 not found")
            return DisarmStatus()

        alarm.client.session.disarm_alarm = track_disarm
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

        assert disarm_calls == ["DARM1DARMPERI", "DARM1"]
        # Disarm does NOT set _use_multi_step — only arm failures should
        assert alarm._use_multi_step is False
        # ARM1PERI1 is not in COMPOUND_COMMAND_STEPS (accepted by all panels),
        # so it is sent as a single command regardless of _use_multi_step.
        assert alarm.client.session.arm_alarm.call_count == 1
        assert alarm.client.session.arm_alarm.call_args[0][1] == "ARM1PERI1"


# ===========================================================================
# _last_proto_code tracking
# ===========================================================================


class TestLastProtoCode:
    """Tests that _last_proto_code is tracked by update_status_alarm."""

    def test_proto_code_stored(self):
        """update_status_alarm stores the proto code."""
        alarm = make_alarm()
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="C",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._last_proto_code == "C"

    def test_disarmed_proto_code_stored(self):
        """'D' (disarmed) is also stored."""
        alarm = make_alarm()
        alarm._last_proto_code = "A"
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="D",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._last_proto_code == "D"

    def test_empty_proto_response_not_stored(self):
        """Empty protomResponse does not update _last_proto_code."""
        alarm = make_alarm()
        alarm._last_proto_code = "T"
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._last_proto_code == "T"

    def test_non_proto_string_not_stored(self):
        """Non-proto strings (e.g. from xSStatus) don't overwrite proto code.

        When check_alarm_panel is disabled, protomResponse carries the
        xSStatus.status string (e.g. "ARMED_TOTAL") instead of a single-char
        proto code.  This must not pollute _last_proto_code.
        """
        alarm = make_alarm()
        alarm._last_proto_code = "A"
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="ARMED_TOTAL",
            InstallationNumer="123456",
            protomResponse="ARMED_TOTAL",
            protomResponseData="",
        )
        alarm.update_status_alarm(status)
        assert alarm._last_proto_code == "A"


# ===========================================================================
# _notify_error per-installation notification_id
# ===========================================================================


class TestNotifyError:
    """Tests for _notify_error helper."""

    def test_notification_id_includes_installation_number(self):
        """notification_id includes installation number for multi-installation setups."""
        alarm = make_alarm()
        alarm._notify_error("Securitas: Arming failed", "test body")

        alarm.hass.async_create_task.assert_called_once()
        call_args = alarm.hass.services.async_call.call_args
        service_data = call_args[1]["service_data"]
        assert "123456" in service_data["notification_id"]
        assert (
            service_data["notification_id"]
            == "securitas.securitas_arming_failed_123456"
        )


# ===========================================================================
# Notification content tests
# ===========================================================================


class TestNotificationContent:
    """Tests for arming exception notification content."""

    def _make_exc(self, exceptions=None):
        if exceptions is None:
            exceptions = [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}]
        return ArmingExceptionError("ref-123", "suid-123", exceptions)

    def test_persistent_notification_content(self):
        """Persistent notification has correct title, message, and notification_id."""
        alarm = make_alarm()
        exc = self._make_exc()

        alarm._notify_arm_exceptions(exc)

        # Find the persistent_notification.create call
        calls = alarm.hass.services.async_call.call_args_list
        pn_call = next(c for c in calls if c[1]["domain"] == "persistent_notification")
        sd = pn_call[1]["service_data"]
        assert sd["title"] == "Securitas: Arm blocked — open sensor(s)"
        assert "Kitchen Door" in sd["message"]
        assert sd["notification_id"] == "securitas.arming_exception_123456"

    def test_mobile_notification_has_tag(self):
        """Mobile notification includes the per-installation tag."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        exc = self._make_exc()

        alarm._notify_arm_exceptions(exc)

        calls = alarm.hass.services.async_call.call_args_list
        mobile_call = next(c for c in calls if c[1]["domain"] == "notify")
        data = mobile_call[1]["service_data"]["data"]
        assert data["tag"] == "securitas.arming_exception_123456"

    def test_mobile_notification_action_buttons(self):
        """Mobile notification has Force Arm and Cancel action buttons."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        exc = self._make_exc()

        alarm._notify_arm_exceptions(exc)

        calls = alarm.hass.services.async_call.call_args_list
        mobile_call = next(c for c in calls if c[1]["domain"] == "notify")
        actions = mobile_call[1]["service_data"]["data"]["actions"]
        assert len(actions) == 2
        assert actions[0]["action"] == "SECURITAS_FORCE_ARM_123456"
        assert actions[0]["title"] == "Force Arm"
        assert actions[1]["action"] == "SECURITAS_CANCEL_FORCE_ARM_123456"
        assert actions[1]["title"] == "Cancel"

    def test_mobile_notification_short_message(self):
        """Mobile message is shorter than persistent message and contains sensor alias."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        exc = self._make_exc()

        alarm._notify_arm_exceptions(exc)

        calls = alarm.hass.services.async_call.call_args_list
        pn_call = next(c for c in calls if c[1]["domain"] == "persistent_notification")
        mobile_call = next(c for c in calls if c[1]["domain"] == "notify")
        persistent_msg = pn_call[1]["service_data"]["message"]
        mobile_msg = mobile_call[1]["service_data"]["message"]
        assert "Kitchen Door" in mobile_msg
        assert len(mobile_msg) < len(persistent_msg)

    def test_notification_multiple_sensors(self):
        """Multiple sensors appear in both persistent and mobile notifications."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        exc = self._make_exc(
            exceptions=[{"alias": "Kitchen Door"}, {"alias": "Bedroom Window"}]
        )

        alarm._notify_arm_exceptions(exc)

        calls = alarm.hass.services.async_call.call_args_list
        pn_call = next(c for c in calls if c[1]["domain"] == "persistent_notification")
        mobile_call = next(c for c in calls if c[1]["domain"] == "notify")
        persistent_msg = pn_call[1]["service_data"]["message"]
        mobile_msg = mobile_call[1]["service_data"]["message"]
        assert "Kitchen Door" in persistent_msg
        assert "Bedroom Window" in persistent_msg
        assert "Kitchen Door" in mobile_msg
        assert "Bedroom Window" in mobile_msg

    def test_notification_sensor_alias_fallback(self):
        """Sensor without alias key shows 'unknown' in notification."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        exc = self._make_exc(exceptions=[{"status": "0", "deviceType": "MG"}])

        alarm._notify_arm_exceptions(exc)

        calls = alarm.hass.services.async_call.call_args_list
        pn_call = next(c for c in calls if c[1]["domain"] == "persistent_notification")
        mobile_call = next(c for c in calls if c[1]["domain"] == "notify")
        assert "unknown" in pn_call[1]["service_data"]["message"]
        assert "unknown" in mobile_call[1]["service_data"]["message"]

    def test_no_mobile_notification_without_notify_group(self):
        """Without notify_group, only persistent notification fires with correct content."""
        alarm = make_alarm()
        exc = self._make_exc()

        alarm._notify_arm_exceptions(exc)

        # Only 1 async_create_task call (persistent only)
        assert alarm.hass.async_create_task.call_count == 1
        # Verify persistent notification content is still correct
        calls = alarm.hass.services.async_call.call_args_list
        assert len(calls) == 1
        sd = calls[0][1]["service_data"]
        assert sd["title"] == "Securitas: Arm blocked — open sensor(s)"
        assert "Kitchen Door" in sd["message"]
        assert sd["notification_id"] == "securitas.arming_exception_123456"


# ===========================================================================
# Dismiss notification tests
# ===========================================================================


class TestDismissNotification:
    """Tests for _dismiss_arming_exception_notification."""

    def test_dismiss_persistent_notification(self):
        """Dismissing sends persistent_notification.dismiss with correct notification_id."""
        alarm = make_alarm()

        alarm._dismiss_arming_exception_notification()

        calls = alarm.hass.services.async_call.call_args_list
        pn_call = next(c for c in calls if c[1]["domain"] == "persistent_notification")
        assert pn_call[1]["service"] == "dismiss"
        assert pn_call[1]["service_data"] == {
            "notification_id": "securitas.arming_exception_123456"
        }

    def test_dismiss_mobile_notification_with_notify_group(self):
        """With notify_group, dismiss also sends clear_notification to mobile."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"

        alarm._dismiss_arming_exception_notification()

        calls = alarm.hass.services.async_call.call_args_list
        mobile_call = next(c for c in calls if c[1]["domain"] == "notify")
        assert mobile_call[1]["service"] == "mobile_app_phone"
        assert mobile_call[1]["service_data"] == {
            "message": "clear_notification",
            "data": {"tag": "securitas.arming_exception_123456"},
        }

    def test_dismiss_no_mobile_without_notify_group(self):
        """Without notify_group, only persistent dismiss fires."""
        alarm = make_alarm()

        alarm._dismiss_arming_exception_notification()

        # Only 1 async_create_task call (persistent dismiss only)
        assert alarm.hass.async_create_task.call_count == 1

    @pytest.mark.asyncio
    async def test_force_arm_cancel_dismisses_both(self):
        """async_force_arm_cancel dismisses both persistent and mobile notifications."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._force_context = {
            "reference_id": "ref-123",
            "suid": "suid-123",
            "mode": AlarmControlPanelState.ARMED_HOME,
            "exceptions": [{"alias": "Door"}],
            "created_at": datetime.now(),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True

        await alarm.async_force_arm_cancel()

        calls = alarm.hass.services.async_call.call_args_list
        # persistent_notification.dismiss
        pn_call = next(c for c in calls if c[1]["domain"] == "persistent_notification")
        assert pn_call[1]["service"] == "dismiss"
        # notify clear_notification
        mobile_call = next(c for c in calls if c[1]["domain"] == "notify")
        assert mobile_call[1]["service_data"]["message"] == "clear_notification"
        assert (
            mobile_call[1]["service_data"]["data"]["tag"]
            == "securitas.arming_exception_123456"
        )
        # Context should be cleared
        assert alarm._force_context is None


# ===========================================================================
# async_added_to_hass tests
# ===========================================================================


@pytest.mark.asyncio
class TestAsyncAddedToHass:
    """Tests for async_added_to_hass event listener registration."""

    async def test_registers_mobile_action_listener(self):
        """async_added_to_hass registers listener for mobile_app_notification_action."""
        alarm = make_alarm()

        await alarm.async_added_to_hass()

        alarm.hass.bus.async_listen.assert_called_once_with(
            "mobile_app_notification_action",
            alarm._handle_mobile_action,
        )

    async def test_mobile_action_unsub_stored(self):
        """async_added_to_hass stores the unsubscribe callable from bus.async_listen."""
        alarm = make_alarm()
        sentinel = MagicMock()
        alarm.hass.bus.async_listen.return_value = sentinel

        await alarm.async_added_to_hass()

        assert alarm._mobile_action_unsub is sentinel


# ===========================================================================
# Force-arm workflow integration tests
# ===========================================================================


@pytest.mark.asyncio
class TestForceArmWorkflow:
    """End-to-end integration tests for the force-arm workflow."""

    async def test_full_force_arm_workflow(self):
        """Full workflow: arm fails -> notifications -> force arm succeeds."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._last_status = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-force-123",
            "suid-force-123",
            [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}],
        )
        success_result = ArmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="P",
            protomResponseData="",
        )
        # First call raises ArmingExceptionError, second succeeds
        alarm.client.session.arm_alarm = AsyncMock(side_effect=[exc, success_result])

        # Step 1: initial arm attempt fails
        alarm._state = AlarmControlPanelState.ARMING
        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Force context should be stored
        assert alarm._force_context is not None
        assert alarm._force_context["reference_id"] == "ref-force-123"
        assert alarm._force_context["suid"] == "suid-force-123"
        assert alarm._force_context["mode"] == AlarmControlPanelState.ARMED_HOME

        # Notifications should have been sent (persistent + mobile)
        assert alarm.hass.async_create_task.call_count == 2
        calls = alarm.hass.services.async_call.call_args_list
        pn_create = next(
            c
            for c in calls
            if c[1]["domain"] == "persistent_notification"
            and c[1]["service"] == "create"
        )
        assert "Kitchen Door" in pn_create[1]["service_data"]["message"]

        # Reset call tracking for step 2
        alarm.hass.async_create_task.reset_mock()
        alarm.hass.services.async_call.reset_mock()

        # Step 2: force arm
        await alarm.async_force_arm()

        # arm_alarm should be called with force params
        force_call_kwargs = alarm.client.session.arm_alarm.call_args[1]
        assert force_call_kwargs["force_arming_remote_id"] == "ref-force-123"
        assert force_call_kwargs["suid"] == "suid-force-123"

        # Context should be cleared
        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        assert "arm_exceptions" not in alarm._attr_extra_state_attributes

        # State should reflect bypass arm — force_arm always bypasses sensors
        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        assert alarm._was_force_armed is True

        # Dismiss notifications should have been called
        dismiss_calls = alarm.hass.services.async_call.call_args_list
        pn_dismiss = next(
            c
            for c in dismiss_calls
            if c[1]["domain"] == "persistent_notification"
            and c[1]["service"] == "dismiss"
        )
        assert (
            pn_dismiss[1]["service_data"]["notification_id"]
            == "securitas.arming_exception_123456"
        )

    async def test_full_cancel_workflow(self):
        """Full workflow: arm fails -> user cancels -> context cleared."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._last_status = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-cancel-123",
            "suid-cancel-123",
            [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}],
        )
        alarm.client.session.arm_alarm = AsyncMock(side_effect=exc)

        # Step 1: initial arm fails
        alarm._state = AlarmControlPanelState.ARMING
        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        assert alarm._force_context is not None

        # Reset tracking
        alarm.hass.async_create_task.reset_mock()
        alarm.hass.services.async_call.reset_mock()

        # Step 2: user cancels
        await alarm.async_force_arm_cancel()

        # Context should be cleared
        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes

        # Dismiss notifications should have been called for both
        dismiss_calls = alarm.hass.services.async_call.call_args_list
        pn_dismiss = next(
            c
            for c in dismiss_calls
            if c[1]["domain"] == "persistent_notification"
            and c[1]["service"] == "dismiss"
        )
        assert pn_dismiss is not None
        mobile_clear = next(c for c in dismiss_calls if c[1]["domain"] == "notify")
        assert mobile_clear[1]["service_data"]["message"] == "clear_notification"

        # State should be disarmed
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_force_arm_after_status_refresh(self):
        """Force context survives an immediate status refresh and force arm succeeds."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._last_status = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-refresh-123",
            "suid-refresh-123",
            [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}],
        )
        success_result = ArmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="P",
            protomResponseData="",
        )

        # Step 1: initial arm fails
        alarm.client.session.arm_alarm = AsyncMock(side_effect=exc)
        alarm._state = AlarmControlPanelState.ARMING
        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        assert alarm._force_context is not None
        created_at = alarm._force_context["created_at"]

        # Step 2: status refresh returns disarmed (HA auto-refreshes after service calls)
        alarm.client.update_overview = AsyncMock(
            return_value=CheckAlarmStatus(
                operation_status="OK",
                message="",
                status="",
                InstallationNumer="123456",
                protomResponse="D",
                protomResponseData="",
            )
        )
        await alarm.async_update_status()

        # Context should survive (age < scan interval of 120s)
        assert alarm._force_context is not None
        assert alarm._force_context["created_at"] == created_at
        assert alarm._attr_extra_state_attributes.get("force_arm_available") is True

        # Step 3: force arm succeeds
        alarm.client.session.arm_alarm = AsyncMock(return_value=success_result)
        await alarm.async_force_arm()

        # arm_alarm should have been called with force params
        call_kwargs = alarm.client.session.arm_alarm.call_args[1]
        assert call_kwargs["force_arming_remote_id"] == "ref-refresh-123"
        assert call_kwargs["suid"] == "suid-refresh-123"

        # Context cleared, state reflects bypass arm
        assert alarm._force_context is None
        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        assert alarm._was_force_armed is True


# ===========================================================================
# hass-is-None guard tests (issue #323)
# ===========================================================================


class TestHassNoneGuardsAlarm:
    """Verify alarm entity bails out when hass is None (after removal)."""

    async def test_update_status_skips_when_hass_is_none(self):
        alarm = make_alarm()
        alarm.hass = None
        alarm.client.update_overview = AsyncMock()

        await alarm.async_update_status()

        alarm.client.update_overview.assert_not_awaited()

    def test_force_state_skips_schedule_when_hass_is_none(self):
        alarm = make_alarm()
        alarm.async_schedule_update_ha_state = MagicMock()
        alarm.hass = None

        alarm._SecuritasAlarm__force_state(AlarmControlPanelState.ARMING)

        assert alarm._state == AlarmControlPanelState.ARMING
        alarm.async_schedule_update_ha_state.assert_not_called()
