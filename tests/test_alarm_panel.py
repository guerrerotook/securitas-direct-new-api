"""Tests for alarm_control_panel entity logic."""

from datetime import datetime, timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.alarm_control_panel import AlarmControlPanelEntityFeature  # type: ignore[attr-defined]
from homeassistant.components.alarm_control_panel.const import (
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.securitas.securitas_direct_new_api.models import (
    Installation,
    OperationStatus,
    SStatus,
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
from custom_components.securitas.coordinators import (
    AlarmCoordinator,
    AlarmStatusData,
)
from custom_components.securitas.securitas_direct_new_api.command_resolver import (
    AlarmState,
    InteriorMode,
    PerimeterMode,
)
from custom_components.securitas.const import (
    CONF_FORCE_ARM_NOTIFICATIONS,
    DEFAULT_FORCE_ARM_NOTIFICATIONS,
)


class TestForceArmNotificationsConfig:
    """Tests for the force_arm_notifications config toggle."""

    def test_constants_exist(self):
        """Config constants for force_arm_notifications are defined."""
        assert CONF_FORCE_ARM_NOTIFICATIONS == "force_arm_notifications"
        assert DEFAULT_FORCE_ARM_NOTIFICATIONS is True

    def test_make_alarm_default_notifications_enabled(self):
        """By default, force_arm_notifications is True in config."""
        alarm = make_alarm()
        assert alarm.client.config.get("force_arm_notifications", True) is True

    def test_make_alarm_notifications_disabled(self):
        """force_arm_notifications=False is passed through config."""
        alarm = make_alarm(
            config={
                "map_home": STD_DEFAULTS["map_home"],
                "map_away": STD_DEFAULTS["map_away"],
                "map_night": STD_DEFAULTS["map_night"],
                "map_custom": STD_DEFAULTS["map_custom"],
                "map_vacation": STD_DEFAULTS["map_vacation"],
                "scan_interval": 120,
                "force_arm_notifications": False,
            }
        )
        assert alarm.client.config.get("force_arm_notifications") is False

    async def test_arming_exception_fires_event(self):
        """ArmingExceptionError fires securitas_arming_exception event."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-123",
            "suid-123",
            [
                {
                    "status": "0",
                    "deviceType": "MG",
                    "alias": "Kitchen Door",
                    "zone_id": "3",
                }
            ],
        )
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        alarm.hass.bus.async_fire.assert_called_once()
        call_args = alarm.hass.bus.async_fire.call_args
        assert call_args[0][0] == "securitas_arming_exception"
        event_data = call_args[0][1]
        assert event_data["entity_id"] == alarm.entity_id
        assert event_data["mode"] == AlarmControlPanelState.ARMED_HOME
        assert event_data["zones"] == ["Kitchen Door"]
        assert event_data["details"]["installation"] == "123456"
        assert event_data["details"]["exceptions"] == exc.exceptions

    async def test_handler_creates_notifications_when_enabled(self):
        """Built-in handler creates persistent + mobile notifications when enabled."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = True
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-123",
            "suid-123",
            [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}],
        )
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        # Register the built-in handler (simulates async_added_to_hass)
        alarm._register_arming_exception_handler()

        # Capture the callback that was registered with async_listen
        listen_calls = alarm.hass.bus.async_listen.call_args_list
        arming_exc_call = [
            c for c in listen_calls if c[0][0] == "securitas_arming_exception"
        ]
        assert len(arming_exc_call) == 1
        handler_cb = arming_exc_call[0][0][1]

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Event fired
        alarm.hass.bus.async_fire.assert_called_once()

        # Manually invoke the captured handler with the event data
        # (since MagicMock bus doesn't actually dispatch)
        fire_args = alarm.hass.bus.async_fire.call_args
        mock_event = MagicMock()
        mock_event.data = fire_args[0][1]
        handler_cb(mock_event)

        # Single async_create_task that wraps both persistent + mobile work
        assert alarm.hass.async_create_task.call_count == 1
        for call in alarm.hass.async_create_task.call_args_list:
            arg = call[0][0]
            if hasattr(arg, "close"):
                arg.close()

    async def test_handler_skips_notifications_when_disabled(self):
        """No notifications when force_arm_notifications is False."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = False
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-123",
            "suid-123",
            [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}],
        )
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Event still fires
        alarm.hass.bus.async_fire.assert_called_once()
        # No notifications
        alarm.hass.async_create_task.assert_not_called()
        # But force context is still stored
        assert alarm._force_context is not None
        assert alarm._attr_extra_state_attributes["force_arm_available"] is True

    def test_force_context_expiry_silent_when_disabled(self):
        """When notifications disabled, force context expiry does not notify."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = False
        alarm._force_context = {
            "reference_id": "ref-123",
            "suid": "suid-123",
            "mode": AlarmControlPanelState.ARMED_HOME,
            "exceptions": [],
            "created_at": datetime.now() - timedelta(seconds=300),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True
        alarm._attr_extra_state_attributes["arm_exceptions"] = ["Door"]

        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="D"), protom_response="D"
        )

        alarm._handle_coordinator_update()

        # Force context cleared
        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        # No notification calls
        alarm.hass.async_create_task.assert_not_called()

    async def test_force_arm_no_dismiss_when_disabled(self):
        """When notifications disabled, force_arm skips notification dismissal."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = False
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._force_context = {
            "reference_id": "ref-456",
            "suid": "suid-456",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"alias": "Window"}],
            "created_at": datetime.now(),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_data="",
            )
        )

        # Reset call tracking before the force_arm call
        alarm.hass.async_create_task.reset_mock()

        await alarm.async_force_arm()

        # No notification dismissal calls
        alarm.hass.async_create_task.assert_not_called()


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
    client.arm_alarm = AsyncMock()
    client.disarm_alarm = AsyncMock()

    hass = MagicMock()
    hass.async_create_task = MagicMock()
    hass.services = MagicMock()

    coordinator = MagicMock(spec=AlarmCoordinator)
    coordinator.data = None
    coordinator.async_request_refresh = AsyncMock()
    coordinator.has_peri = has_peri
    coordinator.has_annex = False

    if initial_status is None:
        initial_status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="D",
            protom_response_data="",
        )

    # Patch Entity state-writing methods that require a running HA instance.
    with (
        patch.object(SecuritasAlarm, "async_schedule_update_ha_state", MagicMock()),
        patch.object(SecuritasAlarm, "async_write_ha_state", MagicMock()),
    ):
        alarm = SecuritasAlarm(
            installation=installation,
            client=client,
            hass=hass,
            coordinator=coordinator,
        )
    # Apply the initial status to set default state (e.g. DISARMED)
    alarm.update_status_alarm(initial_status)
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
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="D",
            protom_response_data="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.DISARMED

    def test_total_maps_to_armed_away(self):
        """protomResponse 'T' (total) maps to ARMED_AWAY with STD defaults."""
        alarm = make_alarm()
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="T",
            protom_response_data="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    def test_partial_day_maps_to_armed_home(self):
        """protomResponse 'P' (partial_day) maps to ARMED_HOME with STD defaults."""
        alarm = make_alarm()
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="P",
            protom_response_data="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_HOME

    def test_partial_night_maps_to_armed_night(self):
        """protomResponse 'Q' (partial_night) maps to ARMED_NIGHT with STD defaults."""
        alarm = make_alarm()
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="Q",
            protom_response_data="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_NIGHT

    def test_unknown_code_sets_custom_bypass(self):
        """Unknown protomResponse code sets ARMED_CUSTOM_BYPASS."""
        alarm = make_alarm()

        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="Z",
            protom_response_data="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS

    def test_empty_protom_response_ignored(self):
        """Empty protomResponse leaves state unchanged."""
        alarm = make_alarm()
        assert alarm._state == AlarmControlPanelState.DISARMED

        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="",
            protom_response_data="",
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
        status = OperationStatus(
            operation_status="OK",
            message="Panel ok",
            status="",
            installation_number="123456",
            protom_response="D",
            protom_response_data="some-data",
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
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="A",
            protom_response_data="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    def test_peri_only_maps_to_armed_custom_bypass(self):
        """protomResponse 'E' (peri_only) maps to ARMED_CUSTOM_BYPASS with PERI defaults."""
        alarm = make_alarm(has_peri=True)
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="E",
            protom_response_data="",
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
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="C",
            protom_response_data="",
        )
        alarm.update_status_alarm(status)
        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS

    def test_partial_night_maps_to_armed_night_in_peri_defaults(self):
        """protomResponse 'Q' (partial_night) maps to ARMED_NIGHT in PERI defaults.

        With PERI defaults, map_night = partial_night (proto 'Q').
        """
        alarm = make_alarm(has_peri=True)
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="Q",
            protom_response_data="",
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
        alarm._last_proto_code = "T"  # resolver needs armed proto to issue disarm

        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_disarm("1234")

        alarm.client.disarm_alarm.assert_called_once_with(
            alarm.installation, STATE_TO_COMMAND[SecuritasState.DISARMED]
        )
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_wrong_code_raises_service_validation_error(self):
        """Wrong code raises ServiceValidationError without calling disarm_alarm."""
        alarm = make_alarm(code="1234")
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm.client.disarm_alarm = AsyncMock()

        with pytest.raises(ServiceValidationError):
            await alarm.async_alarm_disarm("0000")

        alarm.client.disarm_alarm.assert_not_called()
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_disarm_error_notifies(self):
        """Error from disarm_alarm sends a translated disarm_failed notification."""
        alarm = make_alarm(code="1234")
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"  # resolver needs armed proto to issue disarm

        alarm.client.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("API down")
        )

        with patch(
            "custom_components.securitas.alarm_control_panel._notify"
        ) as mock_notify:
            await alarm.async_alarm_disarm("1234")

        mock_notify.assert_called_once_with(
            alarm.hass,
            f"disarm_failed_{alarm.installation.number}",
            "disarm_failed",
            {"error": "API down"},
        )

    async def test_disarm_with_peri_armed_uses_combined_command(self):
        """When peri is configured and armed, tries DARM1DARMPERI."""
        alarm = make_alarm(has_peri=True)
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "A"  # total_peri = peri armed

        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_disarm()

        alarm.client.disarm_alarm.assert_called_once_with(
            alarm.installation, "DARM1DARMPERI"
        )

    async def test_disarm_with_peri_configured_but_not_armed_uses_darm1(self):
        """When peri is configured but not currently armed, resolver uses DARM1.

        The resolver is state-aware: proto "T" means interior=TOTAL, peri=OFF,
        so only interior disarm (DARM1) is needed.
        """
        alarm = make_alarm(has_peri=True)
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"  # total = no peri currently

        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_disarm()

        alarm.client.disarm_alarm.assert_called_once_with(alarm.installation, "DARM1")


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

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_data="",
            )
        )
        alarm.client.disarm_alarm = AsyncMock()

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        alarm.client.disarm_alarm.assert_not_called()
        alarm.client.arm_alarm.assert_called_once()
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_arm_from_armed_disarms_first(self):
        """When previously armed (mode change), resolver disarms first then arms."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_HOME
        alarm._last_state = AlarmControlPanelState.ARMED_HOME
        alarm._last_proto_code = "P"  # partial_day = currently armed home

        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(protom_response="D", operation_status="OK")
        )
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_data="",
            )
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        alarm.client.disarm_alarm.assert_called_once_with(alarm.installation, "DARM1")
        alarm.client.arm_alarm.assert_called_once()
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_arm_error_returns_early(self):
        """Error from arm_alarm causes early return, state unchanged from arm_alarm perspective."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._last_state = AlarmControlPanelState.DISARMED

        alarm.client.arm_alarm = AsyncMock(side_effect=SecuritasDirectError("timeout"))

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        # update_status_alarm is never called with a success response,
        # so state stays at DISARMED
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_disarm_error_during_rearm_continues_to_arm(self):
        """Error from disarm_alarm during re-arm logs warning and continues to arm."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_HOME
        alarm._last_state = AlarmControlPanelState.ARMED_HOME

        alarm.client.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("connection lost")
        )
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_data="",
            )
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        alarm.client.arm_alarm.assert_called_once()
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_unmapped_mode_raises_error(self):
        """If mode has no configured SecuritasState, notifies via arm_failed translation key."""
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
        alarm.client.arm_alarm = AsyncMock()

        with patch(
            "custom_components.securitas.alarm_control_panel._notify"
        ) as mock_notify:
            await alarm.set_arm_state(AlarmControlPanelState.ARMED_CUSTOM_BYPASS)

        alarm.client.arm_alarm.assert_not_called()
        mock_notify.assert_called_once()
        assert mock_notify.call_args[0][2] == "arm_failed"


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

    def test_unique_id(self):
        """unique_id is derived from installation number."""
        alarm = make_alarm()
        assert alarm._attr_unique_id == "v4_securitas_direct.123456"

    def test_device_info(self):
        """device_info contains correct manufacturer, model, and name."""
        alarm = make_alarm()
        info = alarm._attr_device_info
        assert info["manufacturer"] == "Securitas Direct"  # type: ignore[typeddict-item]
        assert info["model"] == "SDVFAST"  # type: ignore[typeddict-item]
        assert info["name"] == "Home"  # type: ignore[typeddict-item]
        assert info["hw_version"] == "PLUS"  # type: ignore[typeddict-item]


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
        alarm._last_proto_code = "T"  # resolver needs armed proto

        observed_states = []

        original_disarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_data="",
            )
        )

        async def capture_state(*args, **kwargs):
            observed_states.append(alarm._state)
            return await original_disarm(*args, **kwargs)

        alarm.client.disarm_alarm = capture_state

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
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_data="",
            )
        )

        async def capture_state(*args, **kwargs):
            observed_states.append(alarm._state)
            return await original_arm(*args, **kwargs)

        alarm.client.arm_alarm = capture_state

        await alarm.async_alarm_arm_away()

        assert AlarmControlPanelState.ARMING in observed_states
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_disarm_sets_operation_in_progress_during_api_call(self):
        """async_alarm_disarm sets _operation_in_progress=True while the API call runs."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"  # resolver needs armed proto

        observed_flags = []

        original_disarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_data="",
            )
        )

        async def capture_flag(*args, **kwargs):
            observed_flags.append(alarm._operation_in_progress)
            return await original_disarm(*args, **kwargs)

        alarm.client.disarm_alarm = capture_flag

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
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_data="",
            )
        )

        async def capture_flag(*args, **kwargs):
            observed_flags.append(alarm._operation_in_progress)
            return await original_arm(*args, **kwargs)

        alarm.client.arm_alarm = capture_flag

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
        alarm._last_proto_code = "T"  # resolver needs armed proto
        alarm.client.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("API error")
        )

        await alarm.async_alarm_disarm()

        assert alarm._operation_in_progress is False

    async def test_operation_in_progress_cleared_after_arm_error(self):
        """_operation_in_progress is cleared even when arm raises SecuritasDirectError."""
        alarm = make_alarm()
        alarm.client.arm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("API error")
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        assert alarm._operation_in_progress is False

    async def test_disarm_403_sets_waf_blocked_skips_generic_notification(self):
        """403 on disarm sets waf_blocked, shows rate_limited but NOT disarm_failed."""
        alarm = make_alarm(code="1234")
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"

        alarm.client.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("HTTP 403", http_status=403)
        )

        with patch(
            "custom_components.securitas.alarm_control_panel._notify"
        ) as mock_notify:
            await alarm.async_alarm_disarm("1234")

        assert alarm._attr_extra_state_attributes.get("waf_blocked") is True
        # _notify is called once for "rate_limited" from _execute_step,
        # but NOT for the generic "disarm_failed" message
        translation_keys = [c.args[2] for c in mock_notify.call_args_list]
        assert "disarm_failed" not in translation_keys
        assert "rate_limited" in translation_keys
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_arm_403_sets_waf_blocked_skips_generic_notification(self):
        """403 on arm sets waf_blocked, shows rate_limited but NOT arm_failed."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._last_state = AlarmControlPanelState.DISARMED

        alarm.client.arm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("HTTP 403", http_status=403)
        )

        with patch(
            "custom_components.securitas.alarm_control_panel._notify"
        ) as mock_notify:
            await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        assert alarm._attr_extra_state_attributes.get("waf_blocked") is True
        # _notify is called once for "rate_limited" from _execute_step,
        # but NOT for the generic "arm_failed" message
        translation_keys = [c.args[2] for c in mock_notify.call_args_list]
        assert "arm_failed" not in translation_keys
        assert "rate_limited" in translation_keys
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_successful_disarm_clears_waf_blocked(self):
        """Successful disarm clears waf_blocked."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"
        alarm._attr_extra_state_attributes["waf_blocked"] = True

        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_disarm()

        assert "waf_blocked" not in alarm._attr_extra_state_attributes

    async def test_successful_arm_clears_waf_blocked(self):
        """Successful arm clears waf_blocked."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._attr_extra_state_attributes["waf_blocked"] = True

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_data="",
            )
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        assert "waf_blocked" not in alarm._attr_extra_state_attributes

    def test_clearing_waf_blocked_dismisses_rate_limited_notification(self):
        """When WAF clears, dismissing must target the same ID used to create the rate-limited notification."""
        alarm = make_alarm()
        alarm._attr_extra_state_attributes["waf_blocked"] = True

        alarm._set_waf_blocked(False)

        alarm.hass.async_create_task.assert_called_once()  # type: ignore[attr-defined]
        call = alarm.hass.services.async_call.call_args  # type: ignore[attr-defined]
        assert call[1]["domain"] == "persistent_notification"
        assert call[1]["service"] == "dismiss"
        assert call[1]["service_data"]["notification_id"] == (
            f"securitas.rate_limited_{alarm.installation.number}"
        )


# ===========================================================================
# async_will_remove_from_hass
# ===========================================================================


@pytest.mark.asyncio
class TestAsyncWillRemoveFromHass:
    """Tests for async_will_remove_from_hass()."""

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

    async def test_unsubscribes_arming_event_listener(self):
        """Calls _arming_event_unsub() when it is set."""
        alarm = make_alarm()
        arming_unsub_mock = MagicMock()
        alarm._arming_event_unsub = arming_unsub_mock

        await alarm.async_will_remove_from_hass()

        arming_unsub_mock.assert_called_once()

    async def test_handles_none_arming_event_unsub_gracefully(self):
        """Handles None _arming_event_unsub gracefully (no crash)."""
        alarm = make_alarm()
        alarm._arming_event_unsub = None
        alarm._mobile_action_unsub = None

        # Should not raise
        await alarm.async_will_remove_from_hass()

    async def test_calls_super_to_clean_up_coordinator_listener(self):
        """Calls super().async_will_remove_from_hass() so CoordinatorEntity unsubscribes its listener."""
        alarm = make_alarm()

        with patch.object(
            CoordinatorEntity,
            "async_will_remove_from_hass",
            AsyncMock(),
        ) as super_remove:
            await alarm.async_will_remove_from_hass()

        super_remove.assert_called_once()


# ===========================================================================
# _handle_coordinator_update / _update_from_coordinator
# ===========================================================================


class TestHandleCoordinatorUpdate:
    """Tests for coordinator-driven updates."""

    def test_coordinator_update_with_total_status(self):
        """Coordinator data with status 'T' sets ARMED_AWAY."""
        alarm = make_alarm()
        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="T"), protom_response="T"
        )

        alarm._handle_coordinator_update()

        assert alarm._state == AlarmControlPanelState.ARMED_AWAY
        alarm.async_write_ha_state.assert_called_once()  # type: ignore[attr-defined]

    def test_coordinator_update_with_disarmed_status(self):
        """Coordinator data with status 'D' sets DISARMED."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="D"), protom_response="D"
        )

        alarm._handle_coordinator_update()

        assert alarm._state == AlarmControlPanelState.DISARMED
        alarm.async_write_ha_state.assert_called_once()  # type: ignore[attr-defined]

    def test_coordinator_update_skipped_during_operation(self):
        """Coordinator update is skipped when _operation_in_progress is True."""
        alarm = make_alarm()
        alarm._operation_in_progress = True
        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="T"), protom_response="T"
        )

        alarm._handle_coordinator_update()

        # State should remain at initial DISARMED — update was skipped
        assert alarm._state == AlarmControlPanelState.DISARMED
        alarm.async_write_ha_state.assert_not_called()  # type: ignore[attr-defined]

    def test_coordinator_update_with_none_data(self):
        """Coordinator data=None still writes HA state (no crash)."""
        alarm = make_alarm()
        alarm.coordinator.data = None

        alarm._handle_coordinator_update()

        alarm.async_write_ha_state.assert_called_once()  # type: ignore[attr-defined]

    def test_coordinator_update_with_empty_status(self):
        """Coordinator data with empty status string leaves state unchanged."""
        alarm = make_alarm()
        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status=""), protom_response=""
        )

        alarm._handle_coordinator_update()

        assert alarm._state == AlarmControlPanelState.DISARMED
        alarm.async_write_ha_state.assert_called_once()  # type: ignore[attr-defined]

    def test_coordinator_update_with_none_status(self):
        """Coordinator data with None status string leaves state unchanged."""
        alarm = make_alarm()
        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status=None), protom_response=""
        )

        alarm._handle_coordinator_update()

        assert alarm._state == AlarmControlPanelState.DISARMED

    def test_coordinator_update_unknown_code_sets_custom_bypass(self):
        """Unknown proto code from coordinator sets ARMED_CUSTOM_BYPASS."""
        alarm = make_alarm()
        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="Z"), protom_response="Z"
        )

        alarm._handle_coordinator_update()

        assert alarm._state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS

    def test_coordinator_update_updates_last_proto_code(self):
        """Known proto code from coordinator updates _last_proto_code."""
        alarm = make_alarm()
        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="T"), protom_response="T"
        )

        alarm._handle_coordinator_update()

        assert alarm._last_proto_code == "T"

    def test_scan_interval_zero_keeps_force_context_retention(self):
        """scan_interval=0 still uses DEFAULT_SCAN_INTERVAL for force_context retention."""
        from custom_components.securitas import DEFAULT_SCAN_INTERVAL

        alarm = make_alarm(
            config={
                "scan_interval": 0,
                "PERI_alarm": False,
                "map_home": "not_used",
                "map_away": "total",
                "map_night": "not_used",
                "map_custom": "not_used",
                "map_vacation": "not_used",
            }
        )
        assert alarm._update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)


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

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="P",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_arm_home()

        alarm.client.arm_alarm.assert_called_once()
        # Verify the command corresponds to ARMED_HOME mapping
        call_args = alarm.client.arm_alarm.call_args
        assert call_args[0][1] == alarm._command_map[AlarmControlPanelState.ARMED_HOME]
        assert alarm._state == AlarmControlPanelState.ARMED_HOME

    async def test_arm_night_passes_armed_night(self):
        """async_alarm_arm_night calls set_arm_state with ARMED_NIGHT."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="Q",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_arm_night()

        alarm.client.arm_alarm.assert_called_once()
        call_args = alarm.client.arm_alarm.call_args
        assert call_args[0][1] == alarm._command_map[AlarmControlPanelState.ARMED_NIGHT]
        assert alarm._state == AlarmControlPanelState.ARMED_NIGHT

    async def test_arm_custom_bypass_passes_armed_custom_bypass(self):
        """async_alarm_arm_custom_bypass calls set_arm_state with ARMED_CUSTOM_BYPASS."""
        alarm = make_alarm(has_peri=True)  # PERI config maps custom bypass
        alarm._state = AlarmControlPanelState.DISARMED

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="E",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_arm_custom_bypass()

        alarm.client.arm_alarm.assert_called_once()
        call_args = alarm.client.arm_alarm.call_args
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

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_arm_vacation()

        alarm.client.arm_alarm.assert_called_once()
        call_args = alarm.client.arm_alarm.call_args
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
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="P",
                protom_response_data="",
            )
        )

        async def capture_state(*args, **kwargs):
            observed_states.append(alarm._state)
            return await original_arm(*args, **kwargs)

        alarm.client.arm_alarm = capture_state

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
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = self._make_arming_exception()
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

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

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="P",
                protom_response_data="",
            )
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Force params should NOT have been passed (widget doesn't force)
        call_kwargs = alarm.client.arm_alarm.call_args[1]
        assert "force_arming_remote_id" not in call_kwargs
        assert "suid" not in call_kwargs

    async def test_force_context_survives_immediate_coordinator_update(self):
        """Coordinator update does NOT clear recently-set force context.

        HA triggers an immediate coordinator refresh after every service call.
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

        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="D"), protom_response="D"
        )

        alarm._handle_coordinator_update()

        # Force context should STILL be present (age < scan interval)
        assert alarm._force_context is not None
        assert alarm._attr_extra_state_attributes.get("force_arm_available") is True

    async def test_notify_force_arm_expired_uses_translation_key(self):
        """_notify_force_arm_expired calls _notify with the force_arm_expired translation key."""
        alarm = make_alarm()
        with patch(
            "custom_components.securitas.alarm_control_panel._notify"
        ) as mock_notify:
            alarm._notify_force_arm_expired()

        mock_notify.assert_called_once_with(
            alarm.hass,
            f"arming_exception_{alarm.installation.number}",
            "force_arm_expired",
        )

    async def test_force_context_cleared_on_expired_coordinator_update(self):
        """Coordinator update clears force context after scan interval expires."""
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

        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="D"), protom_response="D"
        )

        alarm._handle_coordinator_update()

        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        assert "arm_exceptions" not in alarm._attr_extra_state_attributes

    async def test_force_context_cleared_on_successful_arm(self):
        """Successful arm without force context does not leave stale context."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._force_context = None

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_data="",
            )
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        assert alarm._force_context is None
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_arming_exception_sends_persistent_notification(self):
        """ArmingExceptionError triggers async notification helper via event handler."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = True
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = self._make_arming_exception()
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        # Register handler and capture callback
        alarm._register_arming_exception_handler()
        handler_cb = alarm.hass.bus.async_listen.call_args[0][1]

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Manually dispatch the event to the captured handler
        mock_event = MagicMock()
        mock_event.data = alarm.hass.bus.async_fire.call_args[0][1]
        handler_cb(mock_event)

        # Verify the async helper was scheduled
        alarm.hass.async_create_task.assert_called()  # type: ignore[attr-defined]
        # Close the unawaited coroutine to silence RuntimeWarning
        for call in alarm.hass.async_create_task.call_args_list:  # type: ignore[attr-defined]
            arg = call[0][0]
            if hasattr(arg, "close"):
                arg.close()

    async def test_arming_exception_notifies_configured_group(self):
        """ArmingExceptionError schedules async helper which dispatches both notifications."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = True
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = self._make_arming_exception()
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        # Register handler and capture callback
        alarm._register_arming_exception_handler()
        handler_cb = alarm.hass.bus.async_listen.call_args[0][1]

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Manually dispatch the event to the captured handler
        mock_event = MagicMock()
        mock_event.data = alarm.hass.bus.async_fire.call_args[0][1]
        handler_cb(mock_event)

        # Single async_create_task that wraps the persistent + mobile work
        alarm.hass.async_create_task.assert_called_once()  # type: ignore[attr-defined]
        for call in alarm.hass.async_create_task.call_args_list:  # type: ignore[attr-defined]
            arg = call[0][0]
            if hasattr(arg, "close"):
                arg.close()

    async def test_arming_exception_no_notify_group_only_persistent(self):
        """Without notify_group configured, only persistent notification fires via handler."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = True
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = self._make_arming_exception()
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        # Register handler and capture callback
        alarm._register_arming_exception_handler()
        handler_cb = alarm.hass.bus.async_listen.call_args[0][1]

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Manually dispatch the event to the captured handler
        mock_event = MagicMock()
        mock_event.data = alarm.hass.bus.async_fire.call_args[0][1]
        handler_cb(mock_event)

        # Single async_create_task that wraps the (persistent-only) work
        alarm.hass.async_create_task.assert_called_once()  # type: ignore[attr-defined]
        for call in alarm.hass.async_create_task.call_args_list:  # type: ignore[attr-defined]
            arg = call[0][0]
            if hasattr(arg, "close"):
                arg.close()

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

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_data="",
            )
        )

        await alarm.async_force_arm()

        # Should have called arm_alarm with force params
        call_kwargs = alarm.client.arm_alarm.call_args[1]
        assert call_kwargs["force_arming_remote_id"] == "ref-exc-456"
        assert call_kwargs["suid"] == "suid-456"
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY
        # Force context should be cleared after consumption
        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        assert "arm_exceptions" not in alarm._attr_extra_state_attributes

    async def test_async_force_arm_no_context_does_nothing(self):
        """async_force_arm with no stored context does nothing."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._force_context = None

        alarm.client.arm_alarm = AsyncMock()

        await alarm.async_force_arm()

        alarm.client.arm_alarm.assert_not_called()
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

        alarm.hass.async_create_task.assert_called_once()  # type: ignore[attr-defined]

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
        alarm.hass.async_create_task.assert_called_once()  # type: ignore[attr-defined]

    def test_mobile_action_unknown_does_nothing(self):
        """Unrecognised mobile action does not affect alarm state."""
        alarm = make_alarm()
        alarm._force_context = None

        event = MagicMock()
        event.data = {"action": "SOME_OTHER_APP_ACTION"}

        alarm._handle_mobile_action(event)

        alarm.hass.async_create_task.assert_not_called()  # type: ignore[attr-defined]
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

        alarm.hass.async_create_task.assert_not_called()  # type: ignore[attr-defined]
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
        alarm.async_write_ha_state.assert_called()  # type: ignore[attr-defined]

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
    """Tests for compound arm commands via the resolver + executor."""

    async def test_compound_tries_single_first_then_multi_step(self):
        """First attempt sends compound command; on failure, splits to multi-step."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.DISARMED

        calls = []

        async def track_arm(installation, command, **kwargs):
            calls.append(command)
            if command == "ARMNIGHT1PERI1":
                raise SecuritasDirectError("does not exist", http_status=400)
            proto = "Q" if command == "ARMNIGHT1" else "C"
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response=proto,
                protom_response_data="",
            )

        alarm.client.arm_alarm = track_arm

        await alarm.async_alarm_arm_night()

        # First tried compound, then fell back to two steps via "+" split
        assert calls == ["ARMNIGHT1PERI1", "ARMNIGHT1", "PERI1"]
        assert "ARMNIGHT1PERI1" in alarm._resolver.unsupported
        assert alarm._state == AlarmControlPanelState.ARMED_NIGHT

    async def test_compound_succeeds_as_single_command(self):
        """Panel that supports compound commands sends only one call."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.DISARMED

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="C",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_arm_night()

        alarm.client.arm_alarm.assert_called_once_with(
            alarm.installation, "ARMNIGHT1PERI1"
        )
        assert len(alarm._resolver.unsupported) == 0
        assert alarm._state == AlarmControlPanelState.ARMED_NIGHT

    async def test_unsupported_remembered_skips_compound(self):
        """Once compound is marked unsupported, goes straight to multi-step."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._resolver.mark_unsupported("ARMNIGHT1PERI1")

        calls = []

        async def track_arm(installation, command, **kwargs):
            calls.append((command, kwargs))
            proto = "Q" if command == "ARMNIGHT1" else "C"
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response=proto,
                protom_response_data="",
            )

        alarm.client.arm_alarm = track_arm

        await alarm.async_alarm_arm_night()

        # Skipped the compound attempt, went straight to multi-step
        assert len(calls) == 2
        assert calls[0][0] == "ARMNIGHT1"
        assert calls[1][0] == "PERI1"

    async def test_force_params_passed_to_all_steps(self):
        """Force arming params are passed to every step of a multi-step command.

        Both interior and perimeter sensors can trigger ArmingExceptionError,
        so force params must reach whichever step originally failed.
        """
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._resolver.mark_unsupported("ARMNIGHT1PERI1")

        calls = []

        async def track_arm(installation, command, **kwargs):
            calls.append((command, kwargs))
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="C",
                protom_response_data="",
            )

        alarm.client.arm_alarm = track_arm

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
        """If step 1 of a multi-step command succeeds but step 2 fails, state reflects partial arming."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED
        alarm._resolver.mark_unsupported("ARMNIGHT1PERI1")

        call_count = 0

        async def arm_side_effect(installation, command, **kwargs):
            nonlocal call_count
            call_count += 1
            if command == "ARMNIGHT1":
                return OperationStatus(
                    operation_status="OK",
                    message="",
                    status="",
                    installation_number="123456",
                    protom_response="Q",
                    protom_response_data="",
                )
            raise SecuritasDirectError("PERI1 failed")

        alarm.client.arm_alarm = arm_side_effect

        with patch(
            "custom_components.securitas.alarm_control_panel._notify"
        ) as mock_notify:
            await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        assert call_count == 2
        # Partial state: ARMNIGHT1 succeeded with proto "Q" (partial_night)
        # which maps to ARMED_CUSTOM_BYPASS if unmapped in _night_peri_config,
        # or ARMED_NIGHT if Q is in the status map
        alarm.async_write_ha_state.assert_called()  # type: ignore[attr-defined]
        mock_notify.assert_called_once()
        assert mock_notify.call_args[0][2] == "arm_failed"

    async def test_all_commands_already_unsupported_raises_no_supported_command(self):
        """When every command in a step is already marked unsupported, raise translated HomeAssistantError."""
        from custom_components.securitas.securitas_direct_new_api.command_resolver import (
            CommandStep,
        )

        alarm = make_alarm(config=_night_peri_config())
        alarm._resolver.mark_unsupported("ARMNIGHT1PERI1")
        alarm._resolver.mark_unsupported("ARMNIGHT1+PERI1")

        step = CommandStep(commands=["ARMNIGHT1PERI1", "ARMNIGHT1+PERI1"])

        with pytest.raises(HomeAssistantError) as excinfo:
            await alarm._execute_step(step)

        assert excinfo.value.translation_domain == "securitas"
        assert excinfo.value.translation_key == "no_supported_command"

    async def test_all_alternatives_fail_raises_unsupported_alarm_mode(self):
        """When all 400-failing alternatives are exhausted, raise translated HomeAssistantError."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        alarm.client.arm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("API error", http_status=400)
        )

        with pytest.raises(HomeAssistantError) as excinfo:
            await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        assert excinfo.value.translation_domain == "securitas"
        assert excinfo.value.translation_key == "unsupported_alarm_mode"
        # Tried compound ARMNIGHT1PERI1 then ARMNIGHT1 (first sub-cmd of ARMNIGHT1+PERI1)
        assert alarm.client.arm_alarm.call_count == 2
        assert "ARMNIGHT1PERI1" in alarm._resolver.unsupported
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_non_compound_command_sent_directly(self):
        """Non-compound commands (e.g. ARMNIGHT1) are sent as-is."""
        alarm = make_alarm(has_peri=True)
        alarm._state = AlarmControlPanelState.DISARMED

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="Q",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_arm_night()

        alarm.client.arm_alarm.assert_called_once()
        assert alarm.client.arm_alarm.call_args[0][1] == "ARMNIGHT1"

    async def test_409_does_not_trigger_fallback(self):
        """409 (server busy) should re-raise, not try alternatives."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        alarm.client.arm_alarm = AsyncMock(
            side_effect=SecuritasDirectError(
                "alarm-manager.alarm_process_error", http_status=409
            )
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        # Should only try ARMNIGHT1PERI1 once — NOT fall back to multi-step
        alarm.client.arm_alarm.assert_called_once_with(
            alarm.installation, "ARMNIGHT1PERI1"
        )
        assert "ARMNIGHT1PERI1" not in alarm._resolver.unsupported

    async def test_unsupported_enum_triggers_multi_step_and_succeeds(self):
        """GraphQL enum error triggers multi-step fallback which succeeds."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.DISARMED

        calls = []

        async def arm_side_effect(installation, command, **kwargs):
            calls.append(command)
            if command == "ARMNIGHT1PERI1":
                raise SecuritasDirectError(
                    'Value "ARMNIGHT1PERI1" does not exist in "ArmCodeRequest" enum.',
                    http_status=400,
                )
            proto = "Q" if command == "ARMNIGHT1" else "C"
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response=proto,
                protom_response_data="",
            )

        alarm.client.arm_alarm = arm_side_effect

        await alarm.async_alarm_arm_night()

        assert calls == ["ARMNIGHT1PERI1", "ARMNIGHT1", "PERI1"]
        assert alarm._state == AlarmControlPanelState.ARMED_NIGHT
        assert "ARMNIGHT1PERI1" in alarm._resolver.unsupported

    async def test_arm1peri1_fallback(self):
        """Total+peri falls back through alternatives on panel rejection.

        Resolver for total+peri from disarmed produces:
        [ARMINTEXT1, ARM1PERI1, ARM1+PERI1]
        """
        alarm = make_alarm(has_peri=True)  # map_away = total_peri
        alarm._state = AlarmControlPanelState.DISARMED

        calls = []

        async def track_arm(installation, command, **kwargs):
            calls.append(command)
            if command in ("ARMINTEXT1", "ARM1PERI1"):
                raise SecuritasDirectError("does not exist", http_status=400)
            proto = "T" if command == "ARM1" else "A"
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response=proto,
                protom_response_data="",
            )

        alarm.client.arm_alarm = track_arm

        await alarm.async_alarm_arm_away()

        assert calls == ["ARMINTEXT1", "ARM1PERI1", "ARM1", "PERI1"]
        assert "ARMINTEXT1" in alarm._resolver.unsupported
        assert "ARM1PERI1" in alarm._resolver.unsupported
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_armday1peri1_fallback(self):
        """ARMDAY1PERI1 falls back to ARMDAY1 + PERI1 on panel rejection."""
        config = {
            "PERI_alarm": True,
            "map_home": SecuritasState.PARTIAL_DAY_PERI.value,
            "map_away": PERI_DEFAULTS["map_away"],
            "map_night": PERI_DEFAULTS["map_night"],
            "map_custom": PERI_DEFAULTS["map_custom"],
            "scan_interval": 120,
        }
        alarm = make_alarm(config=config)
        alarm._state = AlarmControlPanelState.DISARMED

        calls = []

        async def track_arm(installation, command, **kwargs):
            calls.append(command)
            if command == "ARMDAY1PERI1":
                raise SecuritasDirectError("does not exist", http_status=400)
            proto = "P" if command == "ARMDAY1" else "B"
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response=proto,
                protom_response_data="",
            )

        alarm.client.arm_alarm = track_arm

        await alarm.async_alarm_arm_home()

        assert calls == ["ARMDAY1PERI1", "ARMDAY1", "PERI1"]
        assert "ARMDAY1PERI1" in alarm._resolver.unsupported
        assert alarm._state == AlarmControlPanelState.ARMED_HOME


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

        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_disarm()

        alarm.client.disarm_alarm.assert_called_once_with(
            alarm.installation, "DARM1DARMPERI"
        )
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_peri_armed_falls_back_to_darm1(self):
        """When DARM1DARMPERI fails, falls back to DARM1."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"  # total_peri = peri armed
        alarm._state = AlarmControlPanelState.ARMED_AWAY

        calls = []

        async def disarm_side_effect(installation, command):
            calls.append(command)
            if command == "DARM1DARMPERI":
                raise SecuritasDirectError("404 not found", http_status=400)
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_data="",
            )

        alarm.client.disarm_alarm = disarm_side_effect

        await alarm.async_alarm_disarm()

        assert calls == ["DARM1DARMPERI", "DARM1"]
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_peri_not_armed_uses_darm1(self):
        """With peri configured but not currently armed, resolver uses DARM1.

        The resolver is state-aware: proto "Q" means interior=NIGHT, peri=OFF,
        so only interior disarm (DARM1) is needed.
        """
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "Q"  # partial_night = no peri
        alarm._state = AlarmControlPanelState.ARMED_NIGHT

        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_disarm()

        alarm.client.disarm_alarm.assert_called_once_with(alarm.installation, "DARM1")

    async def test_no_peri_config_uses_darm1(self):
        """Without peri config, always sends DARM1."""
        alarm = make_alarm(has_peri=False)
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"  # resolver needs armed proto

        alarm.client.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("API down")
        )

        await alarm.async_alarm_disarm()

        alarm.client.disarm_alarm.assert_called_once_with(alarm.installation, "DARM1")

    async def test_unsupported_combined_skips_to_darm1(self):
        """With combined disarm marked unsupported, peri armed goes to DARM1."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "E"  # peri_only
        alarm._state = AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        alarm._resolver.mark_unsupported("DARMPERI")

        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_data="",
            )
        )

        await alarm.async_alarm_disarm()

        alarm.client.disarm_alarm.assert_called_once_with(alarm.installation, "DARM1")

    async def test_both_disarm_attempts_fail(self):
        """When both DARM1DARMPERI and DARM1 fail with 400, raise translated HomeAssistantError."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "B"  # partial_day_peri
        alarm._state = AlarmControlPanelState.ARMED_HOME
        alarm._last_state = AlarmControlPanelState.ARMED_HOME

        alarm.client.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("permanent failure", http_status=400)
        )

        with pytest.raises(HomeAssistantError) as excinfo:
            await alarm.async_alarm_disarm()

        assert excinfo.value.translation_domain == "securitas"
        assert excinfo.value.translation_key == "unsupported_alarm_mode"
        assert alarm.client.disarm_alarm.call_count == 2
        assert alarm._state == AlarmControlPanelState.ARMED_HOME

    async def test_409_does_not_trigger_darm1_fallback(self):
        """409 (server busy) should re-raise, not fall back to DARM1."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"  # total_peri = peri armed
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_state = AlarmControlPanelState.ARMED_AWAY

        alarm.client.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError(
                "alarm-manager.alarm_process_error", http_status=409
            )
        )

        with patch(
            "custom_components.securitas.alarm_control_panel._notify"
        ) as mock_notify:
            await alarm.async_alarm_disarm()

        # Should only try DARM1DARMPERI once — NOT fall back to DARM1
        alarm.client.disarm_alarm.assert_called_once_with(
            alarm.installation, "DARM1DARMPERI"
        )
        # Error placeholder carries clean API message, no full args dump
        mock_notify.assert_called_once()
        placeholders = mock_notify.call_args[0][3]
        assert placeholders["error"] == "alarm-manager.alarm_process_error"
        assert "headers" not in placeholders["error"].lower()

    async def test_disarm_error_notification_is_short(self):
        """Error placeholder should be just the API message, not the full error tuple."""
        alarm = make_alarm(has_peri=False)
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"  # resolver needs armed proto

        _err = SecuritasDirectError("API error message", http_status=500)
        _err.response_body = {"response": "data", "auth": "secret-token"}
        alarm.client.disarm_alarm = AsyncMock(side_effect=_err)

        with patch(
            "custom_components.securitas.alarm_control_panel._notify"
        ) as mock_notify:
            await alarm.async_alarm_disarm()

        mock_notify.assert_called_once()
        placeholders = mock_notify.call_args[0][3]
        assert placeholders["error"] == "API error message"
        assert "secret-token" not in placeholders["error"]

    async def test_rearm_disarm_with_peri_armed(self):
        """Mode change from peri-armed state disarms with fallback, then arms."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "B"  # partial_day_peri = AlarmState(DAY, ON)
        alarm._state = AlarmControlPanelState.ARMED_HOME
        alarm._last_state = AlarmControlPanelState.ARMED_HOME

        disarm_calls = []

        async def track_disarm(installation, command):
            disarm_calls.append(command)
            if command == "DARM1DARMPERI":
                raise SecuritasDirectError("404 not found", http_status=400)
            return OperationStatus(protom_response="D", operation_status="OK")

        alarm.client.disarm_alarm = track_disarm
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="A",
                protom_response_data="",
            )
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        # Disarm fallback: DARM1DARMPERI failed, then DARM1 succeeded
        assert disarm_calls == ["DARM1DARMPERI", "DARM1"]
        assert "DARM1DARMPERI" in alarm._resolver.unsupported
        # Then arm total+peri — tries ARMINTEXT1 first
        assert alarm.client.arm_alarm.call_count == 1
        assert alarm.client.arm_alarm.call_args[0][1] == "ARMINTEXT1"


# ===========================================================================
# _execute_transition (resolver + executor integration)
# ===========================================================================


@pytest.mark.asyncio
class TestExecuteTransition:
    """Tests for _execute_transition (resolver + executor integration)."""

    async def test_disarm_from_total_no_peri(self):
        """Disarm from total (no peri) sends DARM1."""
        alarm = make_alarm(has_peri=False)
        alarm._last_proto_code = "T"
        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(protom_response="D", operation_status="OK")
        )
        await alarm._execute_transition(
            AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        )
        alarm.client.disarm_alarm.assert_called_once_with(alarm.installation, "DARM1")

    async def test_disarm_compound_fallback_to_darm1(self):
        """Disarm from total_peri falls back from DARM1DARMPERI to DARM1."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"
        alarm.client.disarm_alarm = AsyncMock(
            side_effect=[
                SecuritasDirectError("unsupported", http_status=400),
                OperationStatus(protom_response="D", operation_status="OK"),
            ]
        )
        await alarm._execute_transition(
            AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        )
        calls = alarm.client.disarm_alarm.call_args_list
        assert calls[0].args == (alarm.installation, "DARM1DARMPERI")
        assert calls[1].args == (alarm.installation, "DARM1")

    async def test_disarm_compound_fallback_remembers(self):
        """When DARM1DARMPERI fails, it is added to unsupported set."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"
        alarm.client.disarm_alarm = AsyncMock(
            side_effect=[
                SecuritasDirectError("unsupported", http_status=400),
                OperationStatus(protom_response="D", operation_status="OK"),
            ]
        )
        await alarm._execute_transition(
            AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        )
        assert "DARM1DARMPERI" in alarm._resolver.unsupported

    async def test_409_not_treated_as_unsupported(self):
        """409 error re-raises without marking command as unsupported."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"
        alarm.client.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("busy", http_status=409)
        )
        with pytest.raises(SecuritasDirectError, match="busy"):
            await alarm._execute_transition(
                AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
            )
        assert "DARM1DARMPERI" not in alarm._resolver.unsupported

    async def test_403_waf_reraises_without_marking_unsupported(self):
        """403 WAF block re-raises immediately without marking command unsupported."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"
        alarm.client.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError(
                "HTTP 403 from Securitas API", http_status=403
            )
        )
        with pytest.raises(SecuritasDirectError, match="403"):
            await alarm._execute_transition(
                AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
            )
        # Only tried first command, didn't fall back
        alarm.client.disarm_alarm.assert_called_once_with(
            alarm.installation, "DARM1DARMPERI"
        )
        assert "DARM1DARMPERI" not in alarm._resolver.unsupported

    async def test_technical_error_reraises_without_trying_alternatives(self):
        """TECHNICAL_ERROR (no http_status) re-raises immediately, no fallback."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"
        alarm.client.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("Disarm command failed: TECHNICAL_ERROR"),
        )
        with pytest.raises(SecuritasDirectError, match="TECHNICAL_ERROR"):
            await alarm._execute_transition(
                AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
            )
        # Only tried first command, didn't fall back to DARM1
        alarm.client.disarm_alarm.assert_called_once_with(
            alarm.installation, "DARM1DARMPERI"
        )
        # Not marked as unsupported — error was transient
        assert "DARM1DARMPERI" not in alarm._resolver.unsupported

    async def test_all_commands_fail_raises(self):
        """When all 400-failing command alternatives are exhausted, raise translated HomeAssistantError."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"
        alarm.client.disarm_alarm = AsyncMock(
            side_effect=SecuritasDirectError("fail", http_status=400)
        )
        with pytest.raises(HomeAssistantError) as excinfo:
            await alarm._execute_transition(
                AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
            )
        assert excinfo.value.translation_key == "unsupported_alarm_mode"

    async def test_mode_change_disarms_then_arms(self):
        """Mode change (day -> night) disarms first, then arms new mode."""
        alarm = make_alarm(has_peri=False)
        alarm._last_proto_code = "P"
        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(protom_response="D", operation_status="OK")
        )
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(protom_response="Q", operation_status="OK")
        )
        await alarm._execute_transition(
            AlarmState(interior=InteriorMode.NIGHT, perimeter=PerimeterMode.OFF)
        )
        alarm.client.disarm_alarm.assert_called_once_with(alarm.installation, "DARM1")
        alarm.client.arm_alarm.assert_called_once_with(alarm.installation, "ARMNIGHT1")

    async def test_arm_total_peri_multi_step(self):
        """Arm total+peri falls back to multi-step when compounds unsupported."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "D"
        alarm._resolver.mark_unsupported("ARMINTEXT1")
        alarm._resolver.mark_unsupported("ARM1PERI1")
        alarm.client.arm_alarm = AsyncMock(
            side_effect=[
                OperationStatus(protom_response="T", operation_status="OK"),
                OperationStatus(protom_response="A", operation_status="OK"),
            ]
        )
        await alarm._execute_transition(
            AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        )
        calls = alarm.client.arm_alarm.call_args_list
        assert calls[0].args == (alarm.installation, "ARM1")
        assert calls[1].args == (alarm.installation, "PERI1")

    async def test_stale_state_retries_with_corrected_proto(self):
        """When result doesn't match target, retry with corrected state.

        Scenario: _last_proto_code says disarmed ("D") but panel is
        actually in perimeter-only ("E").  User requests arm total+peri.
        First attempt sends ARM1 (wrong — only arms interior → "T").
        Retry sees real state "T", sends PERI1 → reaches target "A".
        """
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "D"  # stale — panel is actually in "E"
        # First call: ARM1 (from "D") → result is "T" (not the target "A")
        # Second call: PERI1 (from "T") → result is "A" (target reached)
        alarm.client.arm_alarm = AsyncMock(
            side_effect=[
                OperationStatus(protom_response="T", operation_status="OK"),
                OperationStatus(protom_response="A", operation_status="OK"),
            ]
        )
        result = await alarm._execute_transition(
            AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        )
        assert result.protom_response == "A"
        assert alarm._last_proto_code == "T"  # updated before retry
        calls = alarm.client.arm_alarm.call_args_list
        # First attempt resolved D→A: tries compound first
        assert calls[0].args[1] in ("ARMINTEXT1", "ARM1PERI1", "ARM1")
        # Second attempt resolved T→A: needs only PERI1
        assert calls[1].args == (alarm.installation, "PERI1")

    async def test_stale_state_retry_limited_to_one(self):
        """State mismatch retry happens at most once."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "D"
        # Both attempts return wrong state — should not loop forever
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(protom_response="T", operation_status="OK")
        )
        result = await alarm._execute_transition(
            AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        )
        # Accepted the second attempt's result even though it's wrong
        assert result.protom_response == "T"
        # Called twice (attempt 0 + attempt 1), not more
        assert alarm.client.arm_alarm.call_count == 2

    async def test_no_retry_when_state_matches_target(self):
        """No retry when the result matches the target state."""
        alarm = make_alarm(has_peri=False)
        alarm._last_proto_code = "D"
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(protom_response="T", operation_status="OK")
        )
        result = await alarm._execute_transition(
            AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF)
        )
        assert result.protom_response == "T"
        alarm.client.arm_alarm.assert_called_once()


# ===========================================================================
# _last_proto_code tracking
# ===========================================================================


class TestLastProtoCode:
    """Tests that _last_proto_code is tracked by update_status_alarm."""

    def test_proto_code_stored(self):
        """update_status_alarm stores the proto code."""
        alarm = make_alarm()
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="C",
            protom_response_data="",
        )
        alarm.update_status_alarm(status)
        assert alarm._last_proto_code == "C"

    def test_disarmed_proto_code_stored(self):
        """'D' (disarmed) is also stored."""
        alarm = make_alarm()
        alarm._last_proto_code = "A"
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="D",
            protom_response_data="",
        )
        alarm.update_status_alarm(status)
        assert alarm._last_proto_code == "D"

    def test_empty_proto_response_not_stored(self):
        """Empty protomResponse does not update _last_proto_code."""
        alarm = make_alarm()
        alarm._last_proto_code = "T"
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="",
            protom_response_data="",
        )
        alarm.update_status_alarm(status)
        assert alarm._last_proto_code == "T"

    def test_non_proto_string_not_stored(self):
        """Non-proto strings (e.g. from xSStatus) don't overwrite proto code.

        Periodic polling uses xSStatus, so protomResponse carries the
        status string (e.g. "ARMED_TOTAL") instead of a single-char
        proto code.  This must not pollute _last_proto_code.
        """
        alarm = make_alarm()
        alarm._last_proto_code = "A"
        status = OperationStatus(
            operation_status="OK",
            message="",
            status="ARMED_TOTAL",
            installation_number="123456",
            protom_response="ARMED_TOTAL",
            protom_response_data="",
        )
        alarm.update_status_alarm(status)
        assert alarm._last_proto_code == "A"


# ===========================================================================
# Notification content tests
# ===========================================================================


_FAKE_NOTIFICATION_ENTRY = {
    "title": "TITLE",
    "message": "Arming blocked because:\n{sensor_list}\nTap Force Arm to override.",
    "mobile_message": "Blocked: {sensor_list}",
    "force_arm_action": "Forçar",
    "cancel_action": "Cancel·lar",
}


@pytest.mark.asyncio
class TestNotificationContent:
    """Tests for arming exception notification content (event-driven path)."""

    def _make_event(self, zones=None):
        """Create a mock event with zones data as fired by _fire_arming_exception_event."""
        if zones is None:
            zones = ["Kitchen Door"]
        event = MagicMock()
        event.data = {"zones": zones}
        return event

    def _alarm_with_async_call(self):
        alarm = make_alarm()
        alarm.hass.config.language = "en"
        alarm.hass.services.async_call = AsyncMock()
        return alarm

    async def test_persistent_notification_translated_content(self):
        """Persistent notification uses translated title and interpolates sensor_list."""
        alarm = self._alarm_with_async_call()
        event = self._make_event()

        with patch(
            "custom_components.securitas.alarm_control_panel.get_notification_strings",
            return_value=_FAKE_NOTIFICATION_ENTRY,
        ):
            await alarm._async_notify_arm_exceptions(event)

        calls = alarm.hass.services.async_call.call_args_list
        pn_call = next(c for c in calls if c[1]["domain"] == "persistent_notification")
        sd = pn_call[1]["service_data"]
        assert sd["title"] == "TITLE"
        assert "- Kitchen Door" in sd["message"]
        assert sd["notification_id"] == "securitas.arming_exception_123456"

    async def test_persistent_notification_unknown_sensor_fallback(self):
        """When zones list is empty, sensor_list placeholder uses unknown-sensor fallback."""
        alarm = self._alarm_with_async_call()
        event = self._make_event(zones=[])

        with patch(
            "custom_components.securitas.alarm_control_panel.get_notification_strings",
            return_value=_FAKE_NOTIFICATION_ENTRY,
        ):
            await alarm._async_notify_arm_exceptions(event)

        pn_call = next(
            c
            for c in alarm.hass.services.async_call.call_args_list
            if c[1]["domain"] == "persistent_notification"
        )
        assert "(unknown sensor)" in pn_call[1]["service_data"]["message"]

    async def test_mobile_notification_has_tag(self):
        """Mobile notification includes the per-installation tag."""
        alarm = self._alarm_with_async_call()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        event = self._make_event()

        with patch(
            "custom_components.securitas.alarm_control_panel.get_notification_strings",
            return_value=_FAKE_NOTIFICATION_ENTRY,
        ):
            await alarm._async_notify_arm_exceptions(event)

        mobile_call = next(
            c
            for c in alarm.hass.services.async_call.call_args_list
            if c[1]["domain"] == "notify"
        )
        data = mobile_call[1]["service_data"]["data"]
        assert data["tag"] == "securitas.arming_exception_123456"

    async def test_mobile_notification_action_buttons_translated(self):
        """Mobile action button titles come from translations."""
        alarm = self._alarm_with_async_call()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        event = self._make_event()

        with patch(
            "custom_components.securitas.alarm_control_panel.get_notification_strings",
            return_value=_FAKE_NOTIFICATION_ENTRY,
        ):
            await alarm._async_notify_arm_exceptions(event)

        mobile_call = next(
            c
            for c in alarm.hass.services.async_call.call_args_list
            if c[1]["domain"] == "notify"
        )
        actions = mobile_call[1]["service_data"]["data"]["actions"]
        assert len(actions) == 2
        assert actions[0]["action"] == "SECURITAS_FORCE_ARM_123456"
        assert actions[0]["title"] == "Forçar"
        assert actions[1]["action"] == "SECURITAS_CANCEL_FORCE_ARM_123456"
        assert actions[1]["title"] == "Cancel·lar"

    async def test_mobile_notification_short_message(self):
        """Mobile message is shorter than persistent message and contains sensor alias."""
        alarm = self._alarm_with_async_call()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        event = self._make_event()

        with patch(
            "custom_components.securitas.alarm_control_panel.get_notification_strings",
            return_value=_FAKE_NOTIFICATION_ENTRY,
        ):
            await alarm._async_notify_arm_exceptions(event)

        calls = alarm.hass.services.async_call.call_args_list
        pn_call = next(c for c in calls if c[1]["domain"] == "persistent_notification")
        mobile_call = next(c for c in calls if c[1]["domain"] == "notify")
        persistent_msg = pn_call[1]["service_data"]["message"]
        mobile_msg = mobile_call[1]["service_data"]["message"]
        assert "Kitchen Door" in mobile_msg
        assert len(mobile_msg) <= len(persistent_msg)

    async def test_notification_multiple_sensors(self):
        """Multiple sensors appear in both persistent and mobile notifications."""
        alarm = self._alarm_with_async_call()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        event = self._make_event(zones=["Kitchen Door", "Bedroom Window"])

        with patch(
            "custom_components.securitas.alarm_control_panel.get_notification_strings",
            return_value=_FAKE_NOTIFICATION_ENTRY,
        ):
            await alarm._async_notify_arm_exceptions(event)

        calls = alarm.hass.services.async_call.call_args_list
        pn_call = next(c for c in calls if c[1]["domain"] == "persistent_notification")
        mobile_call = next(c for c in calls if c[1]["domain"] == "notify")
        persistent_msg = pn_call[1]["service_data"]["message"]
        mobile_msg = mobile_call[1]["service_data"]["message"]
        assert "Kitchen Door" in persistent_msg
        assert "Bedroom Window" in persistent_msg
        assert "Kitchen Door" in mobile_msg
        assert "Bedroom Window" in mobile_msg

    async def test_notification_sensor_alias_fallback(self):
        """Empty zones list shows 'unknown sensor' fallback in notification."""
        alarm = self._alarm_with_async_call()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        event = self._make_event(zones=[])

        with patch(
            "custom_components.securitas.alarm_control_panel.get_notification_strings",
            return_value=_FAKE_NOTIFICATION_ENTRY,
        ):
            await alarm._async_notify_arm_exceptions(event)

        calls = alarm.hass.services.async_call.call_args_list
        pn_call = next(c for c in calls if c[1]["domain"] == "persistent_notification")
        mobile_call = next(c for c in calls if c[1]["domain"] == "notify")
        assert "unknown" in pn_call[1]["service_data"]["message"]
        assert "open sensor" in mobile_call[1]["service_data"]["message"]

    async def test_no_mobile_notification_without_notify_group(self):
        """Without notify_group, only persistent notification fires."""
        alarm = self._alarm_with_async_call()
        event = self._make_event()

        with patch(
            "custom_components.securitas.alarm_control_panel.get_notification_strings",
            return_value=_FAKE_NOTIFICATION_ENTRY,
        ):
            await alarm._async_notify_arm_exceptions(event)

        calls = alarm.hass.services.async_call.call_args_list
        assert len(calls) == 1
        sd = calls[0][1]["service_data"]
        assert sd["title"] == "TITLE"
        assert "Kitchen Door" in sd["message"]
        assert sd["notification_id"] == "securitas.arming_exception_123456"

    def test_event_handler_schedules_async_helper(self):
        """The sync event handler schedules the async helper via async_create_task."""
        alarm = make_alarm()
        event = self._make_event()

        alarm._notify_arm_exceptions_from_event(event)

        alarm.hass.async_create_task.assert_called_once()
        coro = alarm.hass.async_create_task.call_args[0][0]
        coro.close()


# ===========================================================================
# Dismiss notification tests
# ===========================================================================


class TestDismissNotification:
    """Tests for _dismiss_arming_exception_notification."""

    def test_dismiss_persistent_notification(self):
        """Dismissing sends persistent_notification.dismiss with correct notification_id."""
        alarm = make_alarm()

        alarm._dismiss_arming_exception_notification()

        calls = alarm.hass.services.async_call.call_args_list  # type: ignore[attr-defined]
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

        calls = alarm.hass.services.async_call.call_args_list  # type: ignore[attr-defined]
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
        assert alarm.hass.async_create_task.call_count == 1  # type: ignore[attr-defined]

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

        calls = alarm.hass.services.async_call.call_args_list  # type: ignore[attr-defined]
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

        alarm.hass.bus.async_listen.assert_any_call(  # type: ignore[attr-defined]
            "mobile_app_notification_action",
            alarm._handle_mobile_action,
        )

    async def test_registers_arming_exception_listener(self):
        """async_added_to_hass registers listener for securitas_arming_exception."""
        alarm = make_alarm()

        await alarm.async_added_to_hass()

        listen_calls = alarm.hass.bus.async_listen.call_args_list
        arming_exc_calls = [
            c for c in listen_calls if c[0][0] == "securitas_arming_exception"
        ]
        assert len(arming_exc_calls) == 1

    async def test_no_listeners_when_notifications_disabled(self):
        """async_added_to_hass registers no listeners when notifications disabled."""
        alarm = make_alarm(
            config={
                "map_home": STD_DEFAULTS["map_home"],
                "map_away": STD_DEFAULTS["map_away"],
                "map_night": STD_DEFAULTS["map_night"],
                "map_custom": STD_DEFAULTS["map_custom"],
                "map_vacation": STD_DEFAULTS["map_vacation"],
                "scan_interval": 120,
                "force_arm_notifications": False,
            }
        )

        await alarm.async_added_to_hass()

        alarm.hass.bus.async_listen.assert_not_called()  # type: ignore[attr-defined]

    async def test_mobile_action_unsub_stored(self):
        """async_added_to_hass stores the unsubscribe callable from bus.async_listen."""
        alarm = make_alarm()
        sentinel = MagicMock()
        alarm.hass.bus.async_listen.return_value = sentinel  # type: ignore[attr-defined]

        await alarm.async_added_to_hass()

        assert alarm._mobile_action_unsub is sentinel


# ===========================================================================
# Force-arm workflow integration tests
# ===========================================================================


@pytest.mark.asyncio
class TestForceArmWorkflow:
    """End-to-end integration tests for the force-arm workflow."""

    async def test_full_force_arm_workflow(self):
        """Full workflow: arm fails -> event handler schedules notifications -> force arm succeeds."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = True
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-force-123",
            "suid-force-123",
            [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}],
        )
        success_result = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="P",
            protom_response_data="",
        )
        # First call raises ArmingExceptionError, second succeeds
        alarm.client.arm_alarm = AsyncMock(side_effect=[exc, success_result])

        # Register handler (simulates async_added_to_hass)
        alarm._register_arming_exception_handler()
        handler_cb = alarm.hass.bus.async_listen.call_args[0][1]

        # Step 1: initial arm attempt fails
        alarm._state = AlarmControlPanelState.ARMING
        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Force context should be stored
        assert alarm._force_context is not None
        assert alarm._force_context["reference_id"] == "ref-force-123"
        assert alarm._force_context["suid"] == "suid-force-123"
        assert alarm._force_context["mode"] == AlarmControlPanelState.ARMED_HOME

        # Manually dispatch the event to the captured handler
        mock_event = MagicMock()
        mock_event.data = alarm.hass.bus.async_fire.call_args[0][1]
        handler_cb(mock_event)

        # Single async_create_task that wraps the persistent + mobile work
        alarm.hass.async_create_task.assert_called_once()  # type: ignore[attr-defined]
        for call in alarm.hass.async_create_task.call_args_list:  # type: ignore[attr-defined]
            arg = call[0][0]
            if hasattr(arg, "close"):
                arg.close()

        # Reset call tracking for step 2
        alarm.hass.async_create_task.reset_mock()  # type: ignore[attr-defined]
        alarm.hass.services.async_call.reset_mock()  # type: ignore[attr-defined]

        # Step 2: force arm
        await alarm.async_force_arm()

        # arm_alarm should be called with force params
        force_call_kwargs = alarm.client.arm_alarm.call_args[1]
        assert force_call_kwargs["force_arming_remote_id"] == "ref-force-123"
        assert force_call_kwargs["suid"] == "suid-force-123"

        # Context should be cleared
        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        assert "arm_exceptions" not in alarm._attr_extra_state_attributes

        # State should reflect successful arm
        assert alarm._state == AlarmControlPanelState.ARMED_HOME

        # Dismiss notifications should have been called
        dismiss_calls = alarm.hass.services.async_call.call_args_list  # type: ignore[attr-defined]
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
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-cancel-123",
            "suid-cancel-123",
            [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}],
        )
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        # Step 1: initial arm fails
        alarm._state = AlarmControlPanelState.ARMING
        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        assert alarm._force_context is not None

        # Reset tracking
        alarm.hass.async_create_task.reset_mock()  # type: ignore[attr-defined]
        alarm.hass.services.async_call.reset_mock()  # type: ignore[attr-defined]

        # Step 2: user cancels
        await alarm.async_force_arm_cancel()

        # Context should be cleared
        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes

        # Dismiss notifications should have been called for both
        dismiss_calls = alarm.hass.services.async_call.call_args_list  # type: ignore[attr-defined]
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
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-refresh-123",
            "suid-refresh-123",
            [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}],
        )
        success_result = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="P",
            protom_response_data="",
        )

        # Step 1: initial arm fails
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)
        alarm._state = AlarmControlPanelState.ARMING
        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        assert alarm._force_context is not None
        created_at = alarm._force_context["created_at"]

        # Step 2: coordinator refresh returns disarmed (HA auto-refreshes after service calls)
        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="D"), protom_response="D"
        )
        alarm._handle_coordinator_update()

        # Context should survive (age < scan interval of 120s)
        assert alarm._force_context is not None
        assert alarm._force_context["created_at"] == created_at
        assert alarm._attr_extra_state_attributes.get("force_arm_available") is True

        # Step 3: force arm succeeds
        alarm.client.arm_alarm = AsyncMock(return_value=success_result)
        await alarm.async_force_arm()

        # arm_alarm should have been called with force params
        call_kwargs = alarm.client.arm_alarm.call_args[1]
        assert call_kwargs["force_arming_remote_id"] == "ref-refresh-123"
        assert call_kwargs["suid"] == "suid-refresh-123"

        # Context cleared, state reflects success
        assert alarm._force_context is None
        assert alarm._state == AlarmControlPanelState.ARMED_HOME


# ===========================================================================
# hass-is-None guard tests (issue #323)
# ===========================================================================


class TestHassNoneGuardsAlarm:
    """Verify alarm entity bails out when hass is None (after removal)."""

    def test_force_state_skips_schedule_when_hass_is_none(self):
        alarm = make_alarm()
        alarm.async_schedule_update_ha_state = MagicMock()
        alarm.hass = None  # type: ignore[attr-defined]

        alarm._force_state(AlarmControlPanelState.ARMING)

        assert alarm._state == AlarmControlPanelState.ARMING
        alarm.async_schedule_update_ha_state.assert_not_called()
