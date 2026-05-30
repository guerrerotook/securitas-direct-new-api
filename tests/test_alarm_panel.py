"""Tests for alarm_control_panel entity logic."""

import inspect
from datetime import datetime, timedelta

import attr
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.alarm_control_panel import AlarmControlPanelEntityFeature  # type: ignore[attr-defined]
from homeassistant.components.alarm_control_panel.const import (
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as _er_for_feature_detect
from homeassistant.helpers.entity_registry import DeletedRegistryEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.securitas.verisure_owa_api.models import (
    Installation,
    OperationStatus,
    SStatus,
)
from custom_components.securitas.verisure_owa_api.const import (
    PERI_DEFAULTS,
    STATE_TO_COMMAND,
    STD_DEFAULTS,
    VerisureOwaState,
)
from custom_components.securitas.verisure_owa_api.exceptions import (
    ArmingExceptionError,
    VerisureOwaError,
)
from custom_components.securitas.alarm_control_panel import (
    CombinedVerisureOwaAlarmPanel,
)
from custom_components.securitas.coordinators import (
    AlarmCoordinator,
    AlarmStatusData,
)
from custom_components.securitas.verisure_owa_api.command_resolver import (
    AlarmState,
    InteriorMode,
    PerimeterMode,
)
from custom_components.securitas.const import (
    CONF_FORCE_ARM_NOTIFICATIONS,
    DEFAULT_FORCE_ARM_NOTIFICATIONS,
)
from custom_components.securitas.events import (
    ARMING_EXCEPTION_DISMISSED_EVENT_TYPE,
    FORCE_ARM_EXPIRED_EVENT_TYPE,
)


class TestNewArmingExceptionEventConstants:
    """Tests that the two new event-type constants are defined with the
    canonical verisure_owa_* names."""

    def test_force_arm_expired_event_type(self):
        assert FORCE_ARM_EXPIRED_EVENT_TYPE == "verisure_owa_force_arm_expired"

    def test_arming_exception_dismissed_event_type(self):
        assert (
            ARMING_EXCEPTION_DISMISSED_EVENT_TYPE
            == "verisure_owa_arming_exception_dismissed"
        )


class TestNotificationTranslationsPersistentMessageTrim:
    """The persistent-notification arm_blocked_open_sensors.message must
    not direct users to a mobile notification — anyone reading the
    persistent notification is already in the HA UI."""

    LOCALES = ("en", "es", "fr", "it", "pt", "pt-BR", "ca")

    # Substrings (case-insensitive) that would indicate a leftover
    # "or on your mobile notification" clause per locale. We only check
    # for words that *uniquely* appear in the mobile clause, not in the
    # ambient text — "mobile" / "móvil" / "móvel" / "phone".
    FORBIDDEN_BY_LOCALE = {
        "en": ["mobile notification"],
        "es": ["notificación móvil"],
        "fr": ["notification mobile"],
        "it": ["notifica mobile"],
        "pt": ["notificação móvel"],
        "pt-BR": ["notificação móvel"],
        "ca": ["notificació mòbil"],
    }

    def test_message_does_not_mention_mobile_notification(self):
        from custom_components.securitas.notification_translations import (
            NOTIFICATION_TRANSLATIONS,
        )

        for locale in self.LOCALES:
            entry = NOTIFICATION_TRANSLATIONS[locale]["arm_blocked_open_sensors"]
            msg = entry["message"].lower()
            for forbidden in self.FORBIDDEN_BY_LOCALE[locale]:
                assert forbidden.lower() not in msg, (
                    f"Locale {locale!r} arm_blocked_open_sensors.message "
                    f"still contains forbidden substring {forbidden!r}: {entry['message']!r}"
                )

    def test_message_still_mentions_alarm_card(self):
        """Sanity: the alarm-card guidance must still be present per locale."""
        from custom_components.securitas.notification_translations import (
            NOTIFICATION_TRANSLATIONS,
        )

        # Translation hint per locale that should remain.
        keepers = {
            "en": "alarm card",
            "es": "tarjeta de la alarma",
            "fr": "carte d'alarme",
            "it": "card dell'allarme",
            "pt": "cartão do alarme",
            "pt-BR": "cartão do alarme",
            "ca": "targeta de l'alarma",
        }
        for locale in self.LOCALES:
            entry = NOTIFICATION_TRANSLATIONS[locale]["arm_blocked_open_sensors"]
            assert keepers[locale].lower() in entry["message"].lower(), (
                f"Locale {locale!r} no longer mentions {keepers[locale]!r}"
            )


class TestForceArmExpiredMobileMessageTranslation:
    """force_arm_expired entry must carry a mobile_message string per locale
    for the button-less informational mobile notification on expiry."""

    LOCALES = ("en", "es", "fr", "it", "pt", "pt-BR", "ca")

    def test_mobile_message_present_for_all_locales(self):
        from custom_components.securitas.notification_translations import (
            NOTIFICATION_TRANSLATIONS,
        )

        for locale in self.LOCALES:
            entry = NOTIFICATION_TRANSLATIONS[locale]["force_arm_expired"]
            assert "mobile_message" in entry, (
                f"Locale {locale!r} force_arm_expired entry missing mobile_message"
            )
            mobile = entry["mobile_message"]
            assert isinstance(mobile, str) and mobile.strip(), (
                f"Locale {locale!r} force_arm_expired.mobile_message is empty"
            )


# Feature flags for tests that exercise registry APIs introduced after our
# minimum-supported HA (2025.2). On older HA the underlying bug doesn't
# manifest the same way and the test scaffolding can't be constructed — skip
# those tests rather than fake them, since the real-HA assertions are what
# give them value.
_HAS_OBJECT_ID_BASE_KWARG = (
    "object_id_base"
    in inspect.signature(
        _er_for_feature_detect.EntityRegistry.async_get_or_create
    ).parameters
)
_DELETED_REGISTRY_ENTRY_HAS_ALIASES = "aliases" in {
    field.name for field in attr.fields(DeletedRegistryEntry)
}


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
                "scan_interval": 120,
                "force_arm_notifications": False,
            }
        )
        assert alarm.client.config.get("force_arm_notifications") is False

    async def test_arming_exception_fires_event(self):
        """ArmingExceptionError fires both verisure_owa_arming_exception and
        securitas_arming_exception events with the same payload."""
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

        # Both events fired (new + legacy alias)
        assert alarm.hass.bus.async_fire.call_count == 2
        fired_event_names = [c[0][0] for c in alarm.hass.bus.async_fire.call_args_list]
        assert "verisure_owa_arming_exception" in fired_event_names
        assert "securitas_arming_exception" in fired_event_names
        # Check payload from the first fire call (new event)
        event_data = alarm.hass.bus.async_fire.call_args_list[0][0][1]
        assert event_data["entity_id"] == alarm.entity_id
        assert event_data["mode"] == AlarmControlPanelState.ARMED_HOME
        assert event_data["zones"] == ["Kitchen Door"]
        assert event_data["details"]["installation"] == "123456"
        assert event_data["details"]["exceptions"] == exc.exceptions
        assert "_event_id" in event_data

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

        # Capture the callback registered for the new canonical event
        listen_calls = alarm.hass.bus.async_listen.call_args_list
        new_exc_calls = [
            c for c in listen_calls if c[0][0] == "verisure_owa_arming_exception"
        ]
        assert len(new_exc_calls) == 1
        handler_cb = new_exc_calls[0][0][1]

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Both events fired (new canonical + legacy alias)
        assert alarm.hass.bus.async_fire.call_count == 2

        # Manually invoke the captured handler with the event data from the first fire
        # (since MagicMock bus doesn't actually dispatch)
        fire_args = alarm.hass.bus.async_fire.call_args_list[0]
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

        # Both events still fire (new + legacy alias)
        assert alarm.hass.bus.async_fire.call_count == 2
        # No notifications (handler not registered because notifications disabled)
        alarm.hass.async_create_task.assert_not_called()
        # But force context is still stored
        assert alarm._force_context is not None
        assert alarm._attr_extra_state_attributes["force_arm_available"] is True

    async def test_force_context_expiry_silent_when_disabled(self):
        """When notifications disabled, force context expiry does not notify.

        The expiry timer callback now drives this — the coordinator-update
        path no longer touches force context (see TestForceArmExpiryTimer).
        """
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

        # Invoke the timer callback directly — same semantics as the
        # async_call_later-driven flow that production runs.
        await alarm._async_handle_force_arm_expiry(datetime.now())

        # Force context cleared
        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        # No notification calls (notifications disabled)
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
                protom_response_date="",
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
) -> CombinedVerisureOwaAlarmPanel:
    """Create a CombinedVerisureOwaAlarmPanel with mocked dependencies.

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
        # map_custom and map_vacation default to blank (= "not used") so
        # only include keys that the defaults dict actually carries.
        config = {key: value for key, value in defaults.items()}
        config["scan_interval"] = 120

    if code is not None:
        config["code"] = code

    client = MagicMock()
    client.config = config
    client.session = AsyncMock()
    client.arm_alarm = AsyncMock()
    client.disarm_alarm = AsyncMock()

    hass = MagicMock()

    def _consume_coro(coro, *args, **kwargs):
        if hasattr(coro, "close"):
            coro.close()

    hass.async_create_task = MagicMock(side_effect=_consume_coro)
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
            protom_response_date="",
        )

    # Patch Entity state-writing methods that require a running HA instance.
    with (
        patch.object(
            CombinedVerisureOwaAlarmPanel, "async_schedule_update_ha_state", MagicMock()
        ),
        patch.object(
            CombinedVerisureOwaAlarmPanel, "async_write_ha_state", MagicMock()
        ),
    ):
        alarm = CombinedVerisureOwaAlarmPanel(
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


def setup_alarm_entry_data(alarm, *, sub_panels=()):
    """Populate alarm.hass.data[DOMAIN] mirroring alarm_control_panel.__init__.

    Registers ``alarm`` as the combined panel and any provided ``sub_panels``
    in the axis-panel registry, keyed by their ``_AXIS`` attribute. Used by
    tests that exercise `_siblings_on_installation` and the cross-panel
    dismissal helper, both of which walk these registries.
    """
    from custom_components.securitas import DOMAIN

    alarm.hass.data = {DOMAIN: {}}
    alarm.hass.data[DOMAIN]["entry-id-1"] = {
        "combined_alarm_panels": {alarm.installation.number: alarm},
        "axis_alarm_panels": {
            alarm.installation.number: {p._AXIS: p for p in sub_panels}
        },
    }


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
            protom_response_date="",
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
            protom_response_date="",
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
            protom_response_date="",
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
            protom_response_date="",
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
            protom_response_date="",
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
            protom_response_date="",
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
            protom_response_date="some-data",
        )
        alarm.update_status_alarm(status)
        assert alarm._attr_extra_state_attributes["message"] == "Panel ok"
        assert alarm._attr_extra_state_attributes["response_data"] == "some-data"

    def test_unknown_single_letter_updates_last_proto_code(self):
        """Unknown but well-formed proto code (single uppercase letter) is stored.

        Forward-compat: if Verisure adds new state codes we don't yet model,
        we keep `_last_proto_code` truthful so the next arm/disarm can refuse
        cleanly instead of acting on a stale cached state.
        """
        alarm = make_alarm()
        assert alarm._last_proto_code == "D"  # from initial_status

        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="Z",  # not in PROTO_TO_ALARM_STATE; forward-compat for new codes
            protom_response_date="",
        )
        alarm.update_status_alarm(status)
        assert alarm._last_proto_code == "Z"

    def test_multi_char_protom_response_does_not_update_last_proto_code(self):
        """xSStatus polling values like 'ARMED_TOTAL' must not pollute _last_proto_code."""
        alarm = make_alarm()
        alarm._last_proto_code = "T"  # known prior state

        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="ARMED_TOTAL",
            protom_response_date="",
        )
        alarm.update_status_alarm(status)
        assert alarm._last_proto_code == "T"

    def test_lowercase_protom_response_does_not_update_last_proto_code(self):
        """Lowercase letters are not valid proto codes — drop on the floor."""
        alarm = make_alarm()
        alarm._last_proto_code = "T"

        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="t",
            protom_response_date="",
        )
        alarm.update_status_alarm(status)
        assert alarm._last_proto_code == "T"


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
            protom_response_date="",
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
            protom_response_date="",
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
            protom_response_date="",
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
            protom_response_date="",
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
        """Vacation feature is enabled when map_vacation is mapped to a Verisure mode."""
        config = {
            "PERI_alarm": False,
            "map_home": STD_DEFAULTS["map_home"],
            "map_away": STD_DEFAULTS["map_away"],
            "map_night": STD_DEFAULTS["map_night"],
            "map_vacation": VerisureOwaState.TOTAL.value,
            "scan_interval": 120,
        }
        alarm = make_alarm(config=config)
        features = alarm.supported_features
        assert features & AlarmControlPanelEntityFeature.ARM_VACATION

    def test_no_features_when_all_not_used(self):
        """If all mappings are not_used, no features are reported."""
        config = {
            "PERI_alarm": False,
            "map_home": VerisureOwaState.NOT_USED.value,
            "map_away": VerisureOwaState.NOT_USED.value,
            "map_night": VerisureOwaState.NOT_USED.value,
            "map_custom": VerisureOwaState.NOT_USED.value,
            "scan_interval": 120,
        }
        alarm = make_alarm(config=config)
        assert alarm.supported_features == 0


# ===========================================================================
# async_alarm_disarm
# ===========================================================================


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
                protom_response_date="",
            )
        )

        await alarm.async_alarm_disarm("1234")

        alarm.client.disarm_alarm.assert_called_once_with(
            alarm.installation, STATE_TO_COMMAND[VerisureOwaState.DISARMED]
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

        alarm.client.disarm_alarm = AsyncMock(side_effect=VerisureOwaError("API down"))

        with patch(
            "custom_components.securitas.alarm_control_panel._base._notify"
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
                protom_response_date="",
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
                protom_response_date="",
            )
        )

        await alarm.async_alarm_disarm()

        alarm.client.disarm_alarm.assert_called_once_with(alarm.installation, "DARM1")


# ===========================================================================
# set_arm_state
# ===========================================================================


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
                protom_response_date="",
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
                protom_response_date="",
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

        alarm.client.arm_alarm = AsyncMock(side_effect=VerisureOwaError("timeout"))

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
            side_effect=VerisureOwaError("connection lost")
        )
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_date="",
            )
        )

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        alarm.client.arm_alarm.assert_called_once()
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    async def test_unmapped_mode_raises_error(self):
        """If mode has no configured VerisureOwaState, notifies via arm_failed translation key."""
        config = {
            "PERI_alarm": False,
            "map_home": VerisureOwaState.PARTIAL_DAY.value,
            "map_away": VerisureOwaState.TOTAL.value,
            "map_night": VerisureOwaState.PARTIAL_NIGHT.value,
            "map_custom": VerisureOwaState.NOT_USED.value,
            "scan_interval": 120,
        }
        alarm = make_alarm(config=config)
        alarm._state = AlarmControlPanelState.DISARMED
        alarm.client.arm_alarm = AsyncMock()

        with patch(
            "custom_components.securitas.alarm_control_panel._base._notify"
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

    def test_name_returns_main_prefixed_alias(self):
        """Combined (main) panel name is 'Main - <installation alias>'."""
        alarm = make_alarm()
        assert alarm.name == "Main - Home"

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

    def test_unique_id_uses_v5_schema(self):
        """unique_id follows the v5 schema."""
        alarm = make_alarm()
        assert alarm._attr_unique_id == "v4_securitas_direct.123456"

    def test_device_info(self):
        """device_info contains correct manufacturer, model, and name."""
        alarm = make_alarm()
        info = alarm._attr_device_info
        assert info["manufacturer"] == "Verisure"  # type: ignore[typeddict-item]
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
            == STATE_TO_COMMAND[VerisureOwaState.PARTIAL_DAY]
        )
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_AWAY]
            == STATE_TO_COMMAND[VerisureOwaState.TOTAL]
        )
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_NIGHT]
            == STATE_TO_COMMAND[VerisureOwaState.PARTIAL_NIGHT]
        )
        assert AlarmControlPanelState.ARMED_CUSTOM_BYPASS not in alarm._command_map

    def test_peri_command_map(self):
        """PERI defaults build the expected command map including custom bypass."""
        alarm = make_alarm(has_peri=True)
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_HOME]
            == STATE_TO_COMMAND[VerisureOwaState.PARTIAL_DAY]
        )
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_AWAY]
            == STATE_TO_COMMAND[VerisureOwaState.TOTAL_PERI]
        )
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_NIGHT]
            == STATE_TO_COMMAND[VerisureOwaState.PARTIAL_NIGHT]
        )
        assert (
            alarm._command_map[AlarmControlPanelState.ARMED_CUSTOM_BYPASS]
            == STATE_TO_COMMAND[VerisureOwaState.PERI_ONLY]
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
                protom_response_date="",
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
                protom_response_date="",
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
                protom_response_date="",
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
                protom_response_date="",
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
        """_operation_in_progress is cleared even when disarm raises VerisureOwaError."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"  # resolver needs armed proto
        alarm.client.disarm_alarm = AsyncMock(side_effect=VerisureOwaError("API error"))

        await alarm.async_alarm_disarm()

        assert alarm._operation_in_progress is False

    async def test_operation_in_progress_cleared_after_arm_error(self):
        """_operation_in_progress is cleared even when arm raises VerisureOwaError."""
        alarm = make_alarm()
        alarm.client.arm_alarm = AsyncMock(side_effect=VerisureOwaError("API error"))

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        assert alarm._operation_in_progress is False

    async def test_disarm_403_sets_waf_blocked_skips_generic_notification(self):
        """403 on disarm sets waf_blocked, shows rate_limited but NOT disarm_failed."""
        alarm = make_alarm(code="1234")
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"

        alarm.client.disarm_alarm = AsyncMock(
            side_effect=VerisureOwaError("HTTP 403", http_status=403)
        )

        with patch(
            "custom_components.securitas.alarm_control_panel._base._notify"
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
            side_effect=VerisureOwaError("HTTP 403", http_status=403)
        )

        with patch(
            "custom_components.securitas.alarm_control_panel._base._notify"
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
                protom_response_date="",
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
                protom_response_date="",
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
        """Calls _arming_event_unsub_new() when set on teardown."""
        alarm = make_alarm()
        new_unsub_mock = MagicMock()
        alarm._arming_event_unsub_new = new_unsub_mock

        await alarm.async_will_remove_from_hass()

        new_unsub_mock.assert_called_once()

    async def test_handles_none_arming_event_unsub_gracefully(self):
        """Handles None _arming_event_unsub_new gracefully (no crash)."""
        alarm = make_alarm()
        alarm._arming_event_unsub_new = None
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

    def test_coordinator_update_unknown_letter_updates_last_proto_code(self):
        """Unknown but well-formed proto code from coordinator is stored.

        Forward-compat: when Verisure returns a code we don't yet model,
        store it so a later arm/disarm refuses cleanly with the actual code.
        """
        alarm = make_alarm()
        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="Z"), protom_response="Z"
        )

        alarm._handle_coordinator_update()

        assert alarm._last_proto_code == "Z"

    def test_coordinator_update_multi_char_does_not_update_last_proto_code(self):
        """Multi-char status string from coordinator must not pollute _last_proto_code."""
        alarm = make_alarm()
        alarm._last_proto_code = "T"
        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="ARMED_TOTAL"), protom_response="ARMED_TOTAL"
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
                protom_response_date="",
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
                protom_response_date="",
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
                protom_response_date="",
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
            "map_away": VerisureOwaState.NOT_USED.value,
            "map_night": STD_DEFAULTS["map_night"],
            "map_vacation": VerisureOwaState.TOTAL.value,
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
                protom_response_date="",
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
                protom_response_date="",
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
                protom_response_date="",
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
            "custom_components.securitas.alarm_control_panel._base._notify"
        ) as mock_notify:
            alarm._notify_force_arm_expired()

        mock_notify.assert_called_once_with(
            alarm.hass,
            f"arming_exception_{alarm.installation.number}",
            "force_arm_expired",
        )

    async def test_force_context_cleared_on_expiry_timer(self):
        """Expiry timer callback clears force context + attributes.

        Previously this exercised the coordinator-update-driven TTL check,
        which has been removed (HA's coordinator does not call listeners
        on consecutive failures, so the TTL would be missed during a
        sustained outage). The expiry is now driven by an independent
        async_call_later timer scheduled in _set_force_context.
        """
        alarm = make_alarm()
        alarm._force_context = {
            "reference_id": "ref-123",
            "suid": "suid-123",
            "mode": AlarmControlPanelState.ARMED_HOME,
            "exceptions": [],
            "created_at": datetime.now() - timedelta(seconds=300),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True
        alarm._attr_extra_state_attributes["arm_exceptions"] = ["Door"]

        await alarm._async_handle_force_arm_expiry(datetime.now())

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
                protom_response_date="",
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
        handler_cb = next(
            c[0][1]
            for c in alarm.hass.bus.async_listen.call_args_list
            if c[0][0] == "verisure_owa_arming_exception"
        )

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
        handler_cb = next(
            c[0][1]
            for c in alarm.hass.bus.async_listen.call_args_list
            if c[0][0] == "verisure_owa_arming_exception"
        )

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
        handler_cb = next(
            c[0][1]
            for c in alarm.hass.bus.async_listen.call_args_list
            if c[0][0] == "verisure_owa_arming_exception"
        )

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
                protom_response_date="",
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


class TestForceArmExpiredEventFire:
    """Tests that the verisure_owa_force_arm_expired event is fired when the
    180s force-arm context expires."""

    @staticmethod
    def _expired_context(mode=AlarmControlPanelState.ARMED_AWAY):
        return {
            "reference_id": "ref-expire",
            "suid": "suid-expire",
            "mode": mode,
            "exceptions": [
                {"alias": "Front door", "deviceType": "MG", "zone_id": "1"},
                {"alias": "Garage", "deviceType": "MG", "zone_id": "2"},
            ],
            "created_at": datetime.now() - timedelta(seconds=300),
        }

    async def test_event_fires_on_expiry_timer_callback(self):
        """Expiry timer callback fires verisure_owa_force_arm_expired with the
        original mode + zones derived from the saved exceptions.

        Previously this exercised the coordinator-update-driven TTL check;
        the TTL is now timer-driven (see TestForceArmExpiryTimer).
        """
        alarm = make_alarm()
        alarm._force_context = self._expired_context()
        alarm._attr_extra_state_attributes["force_arm_available"] = True
        alarm._attr_extra_state_attributes["arm_exceptions"] = ["Front door", "Garage"]

        await alarm._async_handle_force_arm_expiry(datetime.now())

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        force_expired = [
            c for c in fire_calls if c[0][0] == "verisure_owa_force_arm_expired"
        ]
        assert len(force_expired) == 1
        payload = force_expired[0][0][1]
        assert payload["entity_id"] == alarm.entity_id
        assert payload["mode"] == AlarmControlPanelState.ARMED_AWAY
        assert payload["zones"] == ["Front door", "Garage"]
        assert payload["details"]["installation"] == "123456"
        assert payload["details"]["exceptions"] == [
            {"alias": "Front door", "deviceType": "MG", "zone_id": "1"},
            {"alias": "Garage", "deviceType": "MG", "zone_id": "2"},
        ]
        assert "_event_id" in payload

    def test_event_does_not_fire_on_direct_clear(self):
        """Direct _clear_force_context (cancel/confirm/sibling-dismiss path) must
        not fire the expired event — that is the timer callback's job alone."""
        alarm = make_alarm()
        alarm._force_context = self._expired_context()  # even when expired

        alarm._clear_force_context()

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        force_expired = [
            c for c in fire_calls if c[0][0] == "verisure_owa_force_arm_expired"
        ]
        assert force_expired == []

    def test_timer_scheduled_with_correct_delay(self):
        """_set_force_context schedules the timer at exactly _FORCE_ARM_TTL.

        Previously the "still fresh" test asserted that _clear_force_context
        early-returned within the TTL — but that semantic is gone: the timer
        fires exactly at TTL and the canonical clear path is unconditional.
        What's worth asserting now is that the timer is scheduled with the
        right delay; the rest is HA's scheduler.
        """
        alarm = make_alarm()
        exc = ArmingExceptionError("ref-x", "suid-x", [{"alias": "Door"}])
        with patch(
            "custom_components.securitas.alarm_control_panel._base.async_call_later"
        ) as mock_call_later:
            mock_call_later.return_value = MagicMock()
            alarm._set_force_context(exc, AlarmControlPanelState.ARMED_HOME)

        mock_call_later.assert_called_once()
        delay = mock_call_later.call_args[0][1]
        # async_call_later accepts a timedelta directly — we pass the field
        # itself rather than .total_seconds() so the unit lives at the
        # declaration site.
        assert delay == alarm._FORCE_ARM_TTL
        assert delay.total_seconds() == 180

    async def test_event_fires_even_when_notifications_disabled(self):
        """Events are the public API and fire regardless of the notification toggle."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = False
        alarm._force_context = self._expired_context()

        await alarm._async_handle_force_arm_expiry(datetime.now())

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        force_expired = [
            c for c in fire_calls if c[0][0] == "verisure_owa_force_arm_expired"
        ]
        assert len(force_expired) == 1


class TestForceArmExpiryTimer:
    """Tests for the independent timer driving force-arm TTL expiry.

    Replaces the previous coordinator-update-driven TTL check, which
    missed the expiry event entirely during sustained API outages
    (HA's DataUpdateCoordinator does not call listeners on consecutive
    failures).
    """

    @staticmethod
    def _make_exception():
        return ArmingExceptionError(
            "ref-timer",
            "suid-timer",
            [{"alias": "Front door", "deviceType": "MG", "zone_id": "1"}],
        )

    def test_set_force_context_schedules_timer(self):
        """_set_force_context schedules async_call_later with the TTL."""
        alarm = make_alarm()
        exc = self._make_exception()
        with patch(
            "custom_components.securitas.alarm_control_panel._base.async_call_later"
        ) as mock_call_later:
            mock_call_later.return_value = MagicMock()
            alarm._set_force_context(exc, AlarmControlPanelState.ARMED_AWAY)

        mock_call_later.assert_called_once()
        args = mock_call_later.call_args[0]
        assert args[0] is alarm.hass
        # Delay is the TTL — async_call_later accepts a timedelta directly.
        assert args[1] == alarm._FORCE_ARM_TTL
        # Callback is the expiry handler.
        assert args[2] == alarm._async_handle_force_arm_expiry

    def test_clear_force_context_cancels_timer(self):
        """_clear_force_context cancels the pending expiry timer."""
        alarm = make_alarm()
        exc = self._make_exception()
        unsub_mock = MagicMock()
        with patch(
            "custom_components.securitas.alarm_control_panel._base.async_call_later",
            return_value=unsub_mock,
        ):
            alarm._set_force_context(exc, AlarmControlPanelState.ARMED_AWAY)

        alarm._clear_force_context()

        unsub_mock.assert_called_once()
        assert alarm._force_arm_expiry_unsub is None

    async def test_timer_callback_fires_expired_event_when_context_alive(self):
        """The captured timer callback fires the expired event + wipes context."""
        alarm = make_alarm()
        exc = self._make_exception()
        unsub_mock = MagicMock()
        with patch(
            "custom_components.securitas.alarm_control_panel._base.async_call_later",
            return_value=unsub_mock,
        ) as mock_call_later:
            alarm._set_force_context(exc, AlarmControlPanelState.ARMED_AWAY)
            callback_fn = mock_call_later.call_args[0][2]

        # Reset fire-call tracking to isolate the timer-driven event.
        alarm.hass.bus.async_fire.reset_mock()

        await callback_fn(datetime.now())

        # Expired event fired.
        fire_calls = alarm.hass.bus.async_fire.call_args_list
        force_expired = [
            c for c in fire_calls if c[0][0] == "verisure_owa_force_arm_expired"
        ]
        assert len(force_expired) == 1
        payload = force_expired[0][0][1]
        assert payload["entity_id"] == alarm.entity_id
        assert payload["mode"] == AlarmControlPanelState.ARMED_AWAY
        assert payload["zones"] == ["Front door"]

        # Context wiped.
        assert alarm._force_context is None
        assert "arm_exceptions" not in alarm._attr_extra_state_attributes
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        # Timer slot cleared so the unsub is never called twice on teardown.
        assert alarm._force_arm_expiry_unsub is None
        alarm.async_write_ha_state.assert_called()

    async def test_timer_callback_noops_when_context_already_cleared(self):
        """If context is cleared between scheduling and firing, callback no-ops."""
        alarm = make_alarm()
        exc = self._make_exception()
        unsub_mock = MagicMock()
        with patch(
            "custom_components.securitas.alarm_control_panel._base.async_call_later",
            return_value=unsub_mock,
        ) as mock_call_later:
            alarm._set_force_context(exc, AlarmControlPanelState.ARMED_AWAY)
            callback_fn = mock_call_later.call_args[0][2]

        # Wipe context manually as if a canonical resolution path already ran.
        alarm._force_context = None
        alarm.hass.bus.async_fire.reset_mock()

        await callback_fn(datetime.now())

        # No event fired.
        fire_calls = alarm.hass.bus.async_fire.call_args_list
        force_expired = [
            c for c in fire_calls if c[0][0] == "verisure_owa_force_arm_expired"
        ]
        assert force_expired == []
        # Timer slot still cleared.
        assert alarm._force_arm_expiry_unsub is None

    async def test_force_arm_cancels_timer(self):
        """async_force_arm cancels the pending expiry timer (force=True path)."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED
        exc = self._make_exception()
        unsub_mock = MagicMock()
        with patch(
            "custom_components.securitas.alarm_control_panel._base.async_call_later",
            return_value=unsub_mock,
        ):
            alarm._set_force_context(exc, AlarmControlPanelState.ARMED_AWAY)

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_date="",
            )
        )

        await alarm.async_force_arm()

        unsub_mock.assert_called_once()

    async def test_dismissed_path_cancels_timer(self):
        """_dismiss_pending_force_context_on_siblings cancels the timer."""
        from custom_components.securitas import DOMAIN

        alarm = make_alarm()
        # Wire up the entry-data shape the dismissal helper walks.
        alarm.hass.data = {DOMAIN: {}}
        alarm.hass.data[DOMAIN]["entry-id-1"] = {
            "combined_alarm_panels": {alarm.installation.number: alarm},
            "axis_alarm_panels": {alarm.installation.number: {}},
        }
        exc = self._make_exception()
        unsub_mock = MagicMock()
        with patch(
            "custom_components.securitas.alarm_control_panel._base.async_call_later",
            return_value=unsub_mock,
        ):
            alarm._set_force_context(exc, AlarmControlPanelState.ARMED_AWAY)

        await alarm._dismiss_pending_force_context_on_siblings(
            reason="user_arm",
            new_mode=AlarmControlPanelState.ARMED_NIGHT,
        )

        unsub_mock.assert_called_once()


class TestArmingExceptionDismissedOnEntityRemoval:
    """Reload-path safety net: fire the dismissed event when the entity is
    torn down with a live force-arm context (covers integration-reload
    scenarios — options change, reauth, etc.)."""

    @staticmethod
    def _make_exception():
        return ArmingExceptionError(
            "ref-reload",
            "suid-reload",
            [{"alias": "Window", "deviceType": "MG"}],
        )

    async def test_will_remove_fires_dismissed_when_context_alive(self):
        """async_will_remove_from_hass fires the dismissed event with
        reason='integration_reload' and new_mode=None when context is alive."""
        alarm = make_alarm()
        alarm._force_context = {
            "reference_id": "ref-reload",
            "suid": "suid-reload",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"alias": "Window"}],
            "created_at": datetime.now(),
        }

        await alarm.async_will_remove_from_hass()

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert len(dismissed) == 1
        payload = dismissed[0][0][1]
        assert payload["entity_id"] == alarm.entity_id
        assert payload["reason"] == "integration_reload"
        assert payload["new_mode"] is None
        assert payload["details"] == {"installation": "123456"}

    async def test_will_remove_no_event_when_context_already_cleared(self):
        """No dismissed event fires when context is already None."""
        alarm = make_alarm()
        alarm._force_context = None

        await alarm.async_will_remove_from_hass()

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert dismissed == []

    async def test_will_remove_cancels_timer(self):
        """async_will_remove_from_hass cancels any pending expiry timer."""
        alarm = make_alarm()
        exc = ArmingExceptionError("ref-x", "suid-x", [{"alias": "Door"}])
        unsub_mock = MagicMock()
        with patch(
            "custom_components.securitas.alarm_control_panel._base.async_call_later",
            return_value=unsub_mock,
        ):
            alarm._set_force_context(exc, AlarmControlPanelState.ARMED_AWAY)

        await alarm.async_will_remove_from_hass()

        unsub_mock.assert_called_once()


class TestForceArmExpiredMobileNotification:
    """The button-less informational mobile notification sent on expiry."""

    @staticmethod
    def _make_event(entity_id="alarm_control_panel.home"):
        """Build a mock event matching the FORCE_ARM_EXPIRED payload."""
        from uuid import uuid4

        ev = MagicMock()
        ev.data = {
            "entity_id": entity_id,
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "zones": ["Front door"],
            "details": {
                "installation": "123456",
                "exceptions": [{"alias": "Front door"}],
            },
            "_event_id": str(uuid4()),
        }
        return ev

    async def test_handler_sends_buttonless_mobile_with_same_tag(self):
        """With notify_group + notifications enabled, expiry handler sends a
        notify call with the same tag and no actions array."""
        alarm = make_alarm()
        alarm.hass.services.async_call = AsyncMock()
        alarm.client.config["force_arm_notifications"] = True
        alarm.client.config["notify_group"] = "mobile_app_phone"
        # Make entity_id match the event payload
        ev = self._make_event(entity_id=alarm.entity_id)

        await alarm._async_notify_force_arm_expired_mobile(ev)

        calls = alarm.hass.services.async_call.call_args_list
        notify_calls = [c for c in calls if c[1].get("domain") == "notify"]
        assert len(notify_calls) == 1
        sd = notify_calls[0][1]["service_data"]
        # Same tag as the original arming-exception notification (so the
        # mobile OS replaces the existing card in place).
        assert (
            sd["data"]["tag"]
            == f"securitas.arming_exception_{alarm.installation.number}"
        )
        # No actions array — buttons removed.
        assert "actions" not in sd["data"]
        # Body is the mobile_message from the force_arm_expired translation.
        from custom_components.securitas.notification_translations import (
            get_notification_strings,
        )

        expected = get_notification_strings(alarm.hass, "force_arm_expired")
        assert sd["message"] == expected["mobile_message"]
        assert sd["title"] == expected["title"]

    async def test_handler_no_op_without_notify_group(self):
        """Without a notify_group configured, no mobile notify call fires."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = True
        # Explicitly no notify_group set
        ev = self._make_event(entity_id=alarm.entity_id)

        await alarm._async_notify_force_arm_expired_mobile(ev)

        calls = alarm.hass.services.async_call.call_args_list
        notify_calls = [c for c in calls if c[1].get("domain") == "notify"]
        assert notify_calls == []

    async def test_handler_no_op_when_notifications_disabled(self):
        """force_arm_notifications=False suppresses the mobile call."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = False
        alarm.client.config["notify_group"] = "mobile_app_phone"
        ev = self._make_event(entity_id=alarm.entity_id)

        await alarm._async_notify_force_arm_expired_mobile(ev)

        calls = alarm.hass.services.async_call.call_args_list
        notify_calls = [c for c in calls if c[1].get("domain") == "notify"]
        assert notify_calls == []

    async def test_handler_skips_event_for_other_entity(self):
        """Handler ignores events whose entity_id does not match self."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = True
        alarm.client.config["notify_group"] = "mobile_app_phone"
        ev = self._make_event(entity_id="alarm_control_panel.different")

        await alarm._async_notify_force_arm_expired_mobile(ev)

        calls = alarm.hass.services.async_call.call_args_list
        notify_calls = [c for c in calls if c[1].get("domain") == "notify"]
        assert notify_calls == []


class TestForceArmExpiredHandlerRegistration:
    """The expiry-event handler is registered alongside the arming-exception one."""

    def test_register_subscribes_to_force_arm_expired(self):
        alarm = make_alarm()

        alarm._register_arming_exception_handler()

        listen_calls = alarm.hass.bus.async_listen.call_args_list
        expired_calls = [
            c for c in listen_calls if c[0][0] == "verisure_owa_force_arm_expired"
        ]
        assert len(expired_calls) == 1

    async def test_handler_dedupes_via_event_id(self):
        """A repeated _event_id triggers the handler at most once."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = True
        alarm.client.config["notify_group"] = "mobile_app_phone"

        alarm._register_arming_exception_handler()

        # Capture the registered callback.
        listen_calls = alarm.hass.bus.async_listen.call_args_list
        expired_cb = next(
            c[0][1] for c in listen_calls if c[0][0] == "verisure_owa_force_arm_expired"
        )

        ev = MagicMock()
        ev.data = {
            "entity_id": alarm.entity_id,
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "zones": ["Front door"],
            "details": {"installation": "123456", "exceptions": []},
            "_event_id": "same-id",
        }
        expired_cb(ev)
        # Same event id again — must be ignored.
        expired_cb(ev)

        # Only one async_create_task scheduled across the two calls — the
        # second invocation hit the dedup guard and bailed before scheduling.
        first_count = alarm.hass.async_create_task.call_count
        assert first_count == 1
        # Third invocation with the same event id is idempotent — no growth.
        expired_cb(ev)
        assert alarm.hass.async_create_task.call_count == first_count


class TestSiblingPanelLookup:
    """The cross-panel sibling-lookup helper for installation-wide coordination."""

    def test_lookup_returns_self_only_when_no_sub_panels(self):
        alarm = make_alarm()
        setup_alarm_entry_data(alarm)

        siblings = alarm._siblings_on_installation()

        assert siblings == [alarm]

    def test_lookup_returns_combined_plus_sub_panels(self):
        alarm = make_alarm()
        sub1 = MagicMock()
        sub1._AXIS = "interior"
        sub2 = MagicMock()
        sub2._AXIS = "perimeter"
        setup_alarm_entry_data(alarm, sub_panels=(sub1, sub2))

        siblings = alarm._siblings_on_installation()

        # Combined panel always present; sub-panel order is by axis-key
        # iteration which we don't promise — assert as a set.
        assert set(siblings) == {alarm, sub1, sub2}

    def test_lookup_skips_other_installations(self):
        """Only panels for THIS installation number are returned."""
        from custom_components.securitas import DOMAIN

        alarm = make_alarm()
        # Another combined panel for a different installation in the same
        # hass.data entry block.
        other = MagicMock()
        other.installation = MagicMock(number="999999")

        alarm.hass.data = {DOMAIN: {}}
        alarm.hass.data[DOMAIN]["entry-id-1"] = {
            "combined_alarm_panels": {
                alarm.installation.number: alarm,
                "999999": other,
            },
            "axis_alarm_panels": {alarm.installation.number: {}},
        }

        siblings = alarm._siblings_on_installation()

        assert siblings == [alarm]
        assert other not in siblings

    def test_lookup_handles_missing_entry_data_gracefully(self):
        """If hass.data[DOMAIN] is empty, helper returns just self.

        Defensive: setup ordering means the entry data dict could be
        missing during very early registration paths.
        """
        from custom_components.securitas import DOMAIN

        alarm = make_alarm()
        alarm.hass.data = {DOMAIN: {}}

        siblings = alarm._siblings_on_installation()

        assert siblings == [alarm]

    def test_lookup_walks_multiple_config_entries(self):
        """Helper iterates ALL config entries — a panel in entry-2 is found
        even when self lives in entry-1's registry.

        Real-world scenario: multiple Verisure accounts (one config entry per
        account), each with its own installation. The helper walks every
        entry's bucket so cross-installation arm/disarm coordination works.
        """
        from custom_components.securitas import DOMAIN

        alarm = make_alarm()
        # A second installation living in a different config entry.
        other = MagicMock()
        other.installation = MagicMock(number="999999")
        other_sub = MagicMock()
        other_sub._AXIS = "interior"

        alarm.hass.data = {DOMAIN: {}}
        alarm.hass.data[DOMAIN]["entry-id-1"] = {
            "combined_alarm_panels": {alarm.installation.number: alarm},
            "axis_alarm_panels": {alarm.installation.number: {}},
        }
        alarm.hass.data[DOMAIN]["entry-id-2"] = {
            "combined_alarm_panels": {"999999": other},
            "axis_alarm_panels": {"999999": {"interior": other_sub}},
        }

        siblings = alarm._siblings_on_installation()

        # Only this installation's panels, drawn from entry-id-1.
        assert siblings == [alarm]
        assert other not in siblings
        assert other_sub not in siblings


class TestFireArmingExceptionDismissedEvent:
    """The verisure_owa_arming_exception_dismissed event fired when a panel's
    force-arm context is cleared by a different arm/disarm action."""

    def test_payload_shape(self):
        alarm = make_alarm()

        alarm._fire_arming_exception_dismissed_event(
            reason="user_arm",
            new_mode=AlarmControlPanelState.ARMED_HOME,
        )

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert len(dismissed) == 1
        payload = dismissed[0][0][1]
        assert payload["entity_id"] == alarm.entity_id
        assert payload["reason"] == "user_arm"
        assert payload["new_mode"] == AlarmControlPanelState.ARMED_HOME
        assert payload["details"] == {"installation": "123456"}
        assert "_event_id" in payload


class TestDismissPendingForceContextOnSiblings:
    """The cross-panel dismissal helper called by _async_arm / async_alarm_disarm."""

    async def test_no_op_when_no_panel_has_context(self):
        """No siblings hold a force context — nothing fires, nothing clears."""
        alarm = make_alarm()
        setup_alarm_entry_data(alarm)

        await alarm._dismiss_pending_force_context_on_siblings(
            reason="user_arm",
            new_mode=AlarmControlPanelState.ARMED_HOME,
        )

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert dismissed == []

    async def test_fires_for_self_when_self_has_context(self):
        alarm = make_alarm()
        setup_alarm_entry_data(alarm)
        alarm._force_context = {
            "reference_id": "ref-1",
            "suid": "suid-1",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"alias": "Door"}],
            "created_at": datetime.now(),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True

        await alarm._dismiss_pending_force_context_on_siblings(
            reason="user_disarm",
            new_mode="disarmed",
        )

        # Event fired with self.entity_id
        fire_calls = alarm.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert len(dismissed) == 1
        payload = dismissed[0][0][1]
        assert payload["entity_id"] == alarm.entity_id
        assert payload["reason"] == "user_disarm"
        # Self's context cleared
        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        # State was written so HA sees the cleared attributes immediately.
        alarm.async_write_ha_state.assert_called()

    async def test_writes_ha_state_on_cleared_sibling(self):
        """When a sibling's force-context is cleared, its async_write_ha_state
        must fire so HA sees the wiped force_arm_available / arm_exceptions
        attributes without waiting for the next coordinator update."""
        combined = make_alarm()
        sub = _make_interior_panel()
        sub.entity_id = "alarm_control_panel.home_interior"
        sub.hass = combined.hass
        sub._installation = combined.installation
        sub.async_write_ha_state = MagicMock()
        sub._force_context = {
            "reference_id": "ref-sub",
            "suid": "suid-sub",
            "mode": AlarmControlPanelState.ARMED_NIGHT,
            "exceptions": [{"alias": "Window"}],
            "created_at": datetime.now(),
        }
        setup_alarm_entry_data(combined, sub_panels=(sub,))

        await combined._dismiss_pending_force_context_on_siblings(
            reason="user_arm",
            new_mode=AlarmControlPanelState.ARMED_AWAY,
        )

        # The sibling panel got its context cleared AND its state written.
        assert sub._force_context is None
        sub.async_write_ha_state.assert_called()

    async def test_fires_for_sibling_with_context_attributing_to_sibling(self):
        """If Combined holds context and Interior triggered the dismissal,
        the event must carry Combined's entity_id (the panel that held
        the context)."""
        combined = make_alarm()
        # Build a sibling sub-panel as a MagicMock with the minimum
        # surface the helper depends on.
        sub = MagicMock()
        sub._AXIS = "interior"
        sub.entity_id = "alarm_control_panel.home_interior"
        sub._force_context = None  # sibling doesn't hold context
        sub._clear_force_context = MagicMock()
        # Combined holds the context.
        combined._force_context = {
            "reference_id": "ref-1",
            "suid": "suid-1",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"alias": "Door"}],
            "created_at": datetime.now(),
        }
        setup_alarm_entry_data(combined, sub_panels=(sub,))

        # Interior triggers dismissal.
        # Use combined's helper but invoke from sub's perspective by
        # binding the unbound method (sub is a MagicMock so it can't run
        # the real coroutine). Equivalently: call combined's helper —
        # the helper attributes events to whichever sibling held the
        # context, which is the property under test.
        await combined._dismiss_pending_force_context_on_siblings(
            reason="user_arm",
            new_mode=AlarmControlPanelState.ARMED_NIGHT,
        )

        fire_calls = combined.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert len(dismissed) == 1
        payload = dismissed[0][0][1]
        # Attributed to the panel that held the context (Combined),
        # not the panel that triggered the dismissal.
        assert payload["entity_id"] == combined.entity_id
        # Sibling without context: not cleared.
        sub._clear_force_context.assert_not_called()

    async def test_fires_one_event_per_panel_with_context(self):
        """If multiple siblings hold contexts (theoretically possible),
        each gets its own dismissed event."""
        combined = make_alarm()
        # Build a real sub-panel sibling so the helper's delegation to
        # panel._fire_arming_exception_dismissed_event actually executes
        # the production method (a MagicMock auto-attribute would no-op).
        sub = _make_interior_panel()
        sub.entity_id = "alarm_control_panel.home_interior"
        sub.hass = combined.hass  # share the bus mock
        # `installation` is a read-only @property — assign via the underlying
        # attribute used by VerisureEntity.__init__.
        sub._installation = combined.installation
        # Stub out async_write_ha_state — the real method needs HA's loaded-
        # integrations cache, which the MagicMock'd hass doesn't have.
        sub.async_write_ha_state = MagicMock()
        sub._force_context = {
            "reference_id": "ref-sub",
            "suid": "suid-sub",
            "mode": AlarmControlPanelState.ARMED_NIGHT,
            "exceptions": [{"alias": "Window"}],
            "created_at": datetime.now(),
        }

        combined._force_context = {
            "reference_id": "ref-comb",
            "suid": "suid-comb",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"alias": "Door"}],
            "created_at": datetime.now(),
        }

        setup_alarm_entry_data(combined, sub_panels=(sub,))

        await combined._dismiss_pending_force_context_on_siblings(
            reason="user_disarm",
            new_mode="disarmed",
        )

        fire_calls = combined.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert len(dismissed) == 2
        attributed_ids = {c[0][1]["entity_id"] for c in dismissed}
        assert attributed_ids == {combined.entity_id, sub.entity_id}
        # Both contexts cleared via the real _clear_force_context method.
        assert combined._force_context is None
        assert sub._force_context is None


class TestArmDisarmDismissesPendingForceContext:
    """Regular arm/disarm entry points must clear stale force contexts
    BEFORE dispatching, so the user sees notifications vanish immediately."""

    async def test_async_arm_fires_dismissed_when_context_present(self):
        alarm = make_alarm()
        setup_alarm_entry_data(alarm)
        alarm._force_context = {
            "reference_id": "ref-1",
            "suid": "suid-1",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"alias": "Door"}],
            "created_at": datetime.now(),
        }
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="N",
                protom_response_date="",
            )
        )

        await alarm._async_arm(AlarmControlPanelState.ARMED_HOME)

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert len(dismissed) == 1
        payload = dismissed[0][0][1]
        assert payload["reason"] == "user_arm"
        assert payload["new_mode"] == AlarmControlPanelState.ARMED_HOME

    async def test_async_arm_no_event_when_no_context(self):
        alarm = make_alarm()
        setup_alarm_entry_data(alarm)
        assert alarm._force_context is None
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="N",
                protom_response_date="",
            )
        )

        await alarm._async_arm(AlarmControlPanelState.ARMED_HOME)

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert dismissed == []

    async def test_async_alarm_disarm_fires_dismissed_when_context_present(self):
        alarm = make_alarm()
        setup_alarm_entry_data(alarm)
        alarm._force_context = {
            "reference_id": "ref-1",
            "suid": "suid-1",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"alias": "Door"}],
            "created_at": datetime.now(),
        }
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"
        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="D",
                protom_response_date="",
            )
        )
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="D",
                protom_response_date="",
            )
        )

        await alarm.async_alarm_disarm()

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert len(dismissed) == 1
        payload = dismissed[0][0][1]
        assert payload["reason"] == "user_disarm"
        assert payload["new_mode"] == "disarmed"

    async def test_dismiss_runs_before_dispatch(self):
        """The dismissed event fires BEFORE the new arm operation dispatches —
        so the user sees notifications vanish immediately even if the new
        arm itself fails or hangs."""
        alarm = make_alarm()
        setup_alarm_entry_data(alarm)
        alarm._force_context = {
            "reference_id": "ref-1",
            "suid": "suid-1",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"alias": "Door"}],
            "created_at": datetime.now(),
        }
        # New arm raises — confirms the dismissed event still fires.
        alarm.client.arm_alarm = AsyncMock(side_effect=VerisureOwaError("boom"))

        await alarm._async_arm(AlarmControlPanelState.ARMED_HOME)

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert len(dismissed) == 1

    async def test_force_arm_does_not_fire_dismissed_event(self):
        """async_force_arm is the canonical resolution — must not fire dismissed."""
        alarm = make_alarm()
        setup_alarm_entry_data(alarm)
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._force_context = {
            "reference_id": "ref-1",
            "suid": "suid-1",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"alias": "Door"}],
            "created_at": datetime.now(),
        }
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_date="",
            )
        )

        await alarm.async_force_arm()

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert dismissed == []

    async def test_force_arm_cancel_does_not_fire_dismissed_event(self):
        """async_force_arm_cancel is the canonical resolution — must not fire."""
        alarm = make_alarm()
        setup_alarm_entry_data(alarm)
        alarm._force_context = {
            "reference_id": "ref-1",
            "suid": "suid-1",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"alias": "Door"}],
            "created_at": datetime.now(),
        }

        await alarm.async_force_arm_cancel()

        fire_calls = alarm.hass.bus.async_fire.call_args_list
        dismissed = [
            c
            for c in fire_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert dismissed == []


class TestArmingExceptionDismissedHandler:
    """The built-in handler that responds to verisure_owa_arming_exception_dismissed."""

    @staticmethod
    def _make_event(entity_id, reason="user_arm"):
        ev = MagicMock()
        ev.data = {
            "entity_id": entity_id,
            "reason": reason,
            "new_mode": AlarmControlPanelState.ARMED_HOME,
            "details": {"installation": "123456"},
            "_event_id": "ev-1",
        }
        return ev

    def test_register_subscribes_to_dismissed(self):
        alarm = make_alarm()

        alarm._register_arming_exception_handler()

        listen_calls = alarm.hass.bus.async_listen.call_args_list
        dismissed_calls = [
            c
            for c in listen_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        ]
        assert len(dismissed_calls) == 1

    def test_handler_dismisses_when_enabled(self):
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = True
        alarm.client.config["notify_group"] = "mobile_app_phone"

        alarm._register_arming_exception_handler()

        # Capture the dismissed callback.
        listen_calls = alarm.hass.bus.async_listen.call_args_list
        dismissed_cb = next(
            c[0][1]
            for c in listen_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        )

        ev = self._make_event(alarm.entity_id)
        dismissed_cb(ev)

        # Persistent dismiss + mobile clear_notification both scheduled.
        # _dismiss_arming_exception_notification creates 2 tasks when
        # notify_group is set (one per service call).
        assert alarm.hass.async_create_task.call_count == 2

    def test_handler_skips_when_disabled(self):
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = False

        alarm._register_arming_exception_handler()
        # No listener even registered when disabled — async_added_to_hass
        # gates _register_arming_exception_handler on _notifications_enabled.
        # But the method itself, if called, must still subscribe (the
        # gate lives at registration time, not in the handler).
        # However, when the handler is invoked under disabled config,
        # it must skip the dismiss work.
        listen_calls = alarm.hass.bus.async_listen.call_args_list
        dismissed_cb = next(
            (
                c[0][1]
                for c in listen_calls
                if c[0][0] == "verisure_owa_arming_exception_dismissed"
            ),
            None,
        )
        # If registered, invoke it; either way, no async_create_task fires.
        alarm.hass.async_create_task.reset_mock()
        if dismissed_cb is not None:
            ev = self._make_event(alarm.entity_id)
            dismissed_cb(ev)
        alarm.hass.async_create_task.assert_not_called()

    def test_handler_skips_event_for_other_entity(self):
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = True
        alarm.client.config["notify_group"] = "mobile_app_phone"

        alarm._register_arming_exception_handler()

        listen_calls = alarm.hass.bus.async_listen.call_args_list
        dismissed_cb = next(
            c[0][1]
            for c in listen_calls
            if c[0][0] == "verisure_owa_arming_exception_dismissed"
        )

        ev = self._make_event(entity_id="alarm_control_panel.different")
        dismissed_cb(ev)

        # No dismiss tasks scheduled for an event targeted at a different entity.
        alarm.hass.async_create_task.assert_not_called()


# ===========================================================================
# force_arm_cancel service
# ===========================================================================


class TestUnmappedProtoCodeLogging:
    """When a proto code falls through to ARMED_CUSTOM_BYPASS the log line
    must identify the installation, distinguish recognised-but-unmapped
    from unknown-code, and not spam every poll."""

    @staticmethod
    def _config_without_total():
        # STD_DEFAULTS map_away → TOTAL; replace it so 'T' is unmapped.
        return {
            "map_home": STD_DEFAULTS["map_home"],
            "map_away": VerisureOwaState.PARTIAL_DAY.value,
            "map_night": STD_DEFAULTS["map_night"],
            "scan_interval": 120,
        }

    def test_recognised_unmapped_code_logs_state_name_and_installation(self, caplog):
        """Code in PROTO_TO_STATE but not bound to any HA button → WARNING
        naming the state, the installation number, and the entity_id."""
        import logging

        alarm = make_alarm(config=self._config_without_total())
        alarm.entity_id = "alarm_control_panel.home"

        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="T",
            protom_response_date="",
        )
        with caplog.at_level(logging.WARNING, logger="custom_components.securitas"):
            alarm.update_status_alarm(status)

        msg = caplog.text
        assert "Total" in msg, msg  # human label
        assert "T" in msg
        assert "123456" in msg
        assert "alarm_control_panel.home" in msg

    def test_unknown_code_logs_unrecognised_message(self, caplog):
        """Code not in PROTO_TO_STATE → WARNING saying the integration
        doesn't recognise it."""
        import logging

        alarm = make_alarm(config=self._config_without_total())
        alarm.entity_id = "alarm_control_panel.home"

        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="Z",
            protom_response_date="",
        )
        with caplog.at_level(logging.WARNING, logger="custom_components.securitas"):
            alarm.update_status_alarm(status)

        msg = caplog.text
        assert "Z" in msg
        assert "123456" in msg
        # Phrasing must clearly mark this as integration-unknown, not user-config.
        assert (
            "unknown" in msg.lower()
            or "not recognised" in msg.lower()
            or "not recognized" in msg.lower()
        )

    def test_repeat_unmapped_code_does_not_spam_log(self, caplog):
        """Two polls with the same unmapped code → only one warning."""
        import logging

        alarm = make_alarm(config=self._config_without_total())

        status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="T",
            protom_response_date="",
        )
        with caplog.at_level(logging.WARNING, logger="custom_components.securitas"):
            alarm.update_status_alarm(status)
            alarm.update_status_alarm(status)

        warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "Unmapped" in r.message
        ]
        assert len(warnings) == 1

    def test_unmapped_code_warns_again_after_returning_to_mapped_state(self, caplog):
        """Unmapped → mapped → same unmapped: the second occurrence must
        warn again so the issue resurfaces in the log instead of being
        silenced for the entity's lifetime."""
        import logging

        alarm = make_alarm(config=self._config_without_total())

        unmapped = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="T",
            protom_response_date="",
        )
        disarmed = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protom_response="D",
            protom_response_date="",
        )
        with caplog.at_level(logging.WARNING, logger="custom_components.securitas"):
            alarm.update_status_alarm(unmapped)
            alarm.update_status_alarm(disarmed)
            alarm.update_status_alarm(unmapped)

        warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "Unmapped" in r.message
        ]
        assert len(warnings) == 2


class TestForceArmCodeGate:
    """force_arm trusts the force context as proof of recent PIN auth.

    The context is set only after _check_code_for_arm_if_required passes
    in _async_arm, so its existence is itself proof.  We additionally
    accept an optional code argument and validate it for defence-in-depth
    callers.
    """

    @staticmethod
    def _make_alarm_with_code(code_required: bool):
        """make_alarm with a configured PIN, optionally requiring code on arm."""
        config = {
            **STD_DEFAULTS,
            "scan_interval": 120,
            "code": "1234",
            "code_arm_required": code_required,
        }
        return make_alarm(config=config)

    @staticmethod
    def _seed_force_context(alarm):
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._force_context = {
            "reference_id": "ref-789",
            "suid": "suid-789",
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
                protom_response_date="",
            )
        )

    async def test_force_arm_with_context_proceeds_without_code(self):
        """Force context exists → arm without re-prompting for the PIN.

        The context is set only after a PIN-authenticated arm reached
        the server, so re-prompting on the second-half completion would
        be redundant and would break the mobile-notification flow.
        """
        alarm = self._make_alarm_with_code(code_required=True)
        self._seed_force_context(alarm)

        await alarm.async_force_arm()

        alarm.client.arm_alarm.assert_awaited_once()

    async def test_force_arm_no_context_no_op(self):
        """No force context → no client call, regardless of code_arm_required."""
        alarm = self._make_alarm_with_code(code_required=True)
        alarm.client.arm_alarm = AsyncMock()
        # No _seed_force_context — context is None.

        await alarm.async_force_arm()

        alarm.client.arm_alarm.assert_not_awaited()

    async def test_force_arm_with_explicit_wrong_code_raises(self):
        """Defence-in-depth: explicit wrong code rejected even with context."""
        alarm = self._make_alarm_with_code(code_required=True)
        self._seed_force_context(alarm)

        with pytest.raises(ServiceValidationError):
            await alarm.async_force_arm(code="9999")

        alarm.client.arm_alarm.assert_not_awaited()
        # Force context must remain so the user can retry with the right code.
        assert alarm._force_context is not None

    async def test_force_arm_with_explicit_correct_code_proceeds(self):
        """Defence-in-depth: explicit correct code accepted."""
        alarm = self._make_alarm_with_code(code_required=True)
        self._seed_force_context(alarm)

        await alarm.async_force_arm(code="1234")

        alarm.client.arm_alarm.assert_awaited_once()


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
        "map_night": VerisureOwaState.PARTIAL_NIGHT_PERI.value,
        "map_custom": PERI_DEFAULTS["map_custom"],
        "scan_interval": 120,
    }


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
                raise VerisureOwaError("does not exist", http_status=400)
            proto = "Q" if command == "ARMNIGHT1" else "C"
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response=proto,
                protom_response_date="",
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
                protom_response_date="",
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
                protom_response_date="",
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
                protom_response_date="",
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
                    protom_response_date="",
                )
            raise VerisureOwaError("PERI1 failed")

        alarm.client.arm_alarm = arm_side_effect

        with patch(
            "custom_components.securitas.alarm_control_panel._base._notify"
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
        from custom_components.securitas.verisure_owa_api.command_resolver import (
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
            side_effect=VerisureOwaError("API error", http_status=400)
        )

        with pytest.raises(HomeAssistantError) as excinfo:
            await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        assert excinfo.value.translation_domain == "securitas"
        assert excinfo.value.translation_key == "unsupported_alarm_mode"
        # Tried compound ARMNIGHT1PERI1 then ARMNIGHT1 (first sub-cmd of ARMNIGHT1+PERI1)
        assert alarm.client.arm_alarm.call_count == 2
        assert "ARMNIGHT1PERI1" in alarm._resolver.unsupported
        assert alarm._state == AlarmControlPanelState.DISARMED

    @pytest.mark.parametrize("transient_status", [401, 422, 429, 451])
    async def test_non_400_4xx_does_not_blacklist_command(self, transient_status):
        """Only HTTP 400 (BAD_USER_INPUT / "command not valid for panel") means
        the panel rejected the command. Other 4xx statuses (401 auth-blip,
        422 validation, 429 rate-limit, etc.) are transient or environmental
        and must NOT mark the command unsupported — otherwise a single bad
        moment permanently disables an arming mode the user actually has.

        Sibling concern from PR #467 review: blacklisting too broadly lets
        ``unsupported_commands`` get polluted by transient auth or rate-limit
        problems.
        """
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        alarm.client.arm_alarm = AsyncMock(
            side_effect=VerisureOwaError("transient", http_status=transient_status)
        )

        # set_arm_state catches VerisureOwaError and routes through the
        # arm-failed error handler (notify + log) without re-raising —
        # so the call returns normally; the critical check is below.
        await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        # Critically: no command was marked unsupported.
        assert alarm._resolver.unsupported == frozenset(), (
            f"transient {transient_status} must not blacklist any command, "
            f"but resolver.unsupported = {alarm._resolver.unsupported!r}"
        )
        # And no alternatives were attempted — the 4xx propagated out of
        # _execute_step, the executor stopped at the first failure
        # rather than trying every command in the step (which would
        # also fail and add latency).
        assert alarm.client.arm_alarm.call_count == 1, (
            f"transient {transient_status} should stop at first failure, "
            f"but tried {alarm.client.arm_alarm.call_count} alternatives"
        )

    async def test_unsupported_command_is_persisted_to_entry_data(self):
        """After a 400 marks a command unsupported, the entry's data must
        gain the command in CONF_UNSUPPORTED_COMMANDS so the next setup
        starts with the resolver pre-loaded — sub-panels otherwise expose
        the failing mode again on restart and the user pays the same
        rejection over and over.

        Persisted shape is ``{<installation.number>: [<commands>...]}``
        (a dict keyed by installation number) so that legacy entries
        covering multiple installations don't share one global list and
        cross-contaminate sibling panels' resolvers.
        """
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        entry = MagicMock()
        entry.data = {"username": "u", "country": "IT"}
        alarm._client.config_entry = entry
        alarm.hass.config_entries = MagicMock()

        alarm.client.arm_alarm = AsyncMock(
            side_effect=VerisureOwaError("API error", http_status=400)
        )

        with pytest.raises(HomeAssistantError):
            await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        assert alarm.hass.config_entries.async_update_entry.called, (
            "Expected entry data to be persisted after mark_unsupported"
        )
        kwargs = alarm.hass.config_entries.async_update_entry.call_args.kwargs
        persisted = kwargs.get("data", {}).get("unsupported_commands", {})
        # Per-installation keyed format — Main panel's installation number is "123456"
        assert isinstance(persisted, dict), (
            f"Persisted unsupported_commands must be a dict, got {type(persisted).__name__}"
        )
        installation_num = str(alarm._installation.number)
        assert "ARMNIGHT1PERI1" in persisted.get(installation_num, []), (
            f"Persisted unsupported list missing ARMNIGHT1PERI1 for "
            f"installation {installation_num!r}, got {persisted!r}"
        )

    async def test_persist_unsupported_migrates_legacy_flat_list(self):
        """On upgrade from the v5.0.1-pre flat-list format, the first
        persist call must convert ``["ARMHOME1"]`` into
        ``{<installation.number>: [<new sorted list>]}`` — preserving
        the legacy rejection under THIS installation's slot rather than
        dropping it on the floor.

        In production ``client.config["unsupported_commands"]`` is sourced
        from ``entry.data["unsupported_commands"]`` (see ``__init__.py``'s
        setup hydration), so the legacy flat list is what the resolver
        starts pre-loaded with on the new build. By the time
        ``_persist_unsupported`` runs, the resolver already contains the
        legacy rejection plus any new one — and the write must reflect
        that union under the per-installation slot.
        """
        # Mirror production: client.config + entry.data both carry the
        # same legacy flat-list rejection. The resolver hydrates from
        # client.config at __init__; entry.data is what _persist reads.
        config = _night_peri_config()
        config["unsupported_commands"] = ["ARMHOME1"]
        alarm = make_alarm(config=config)
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        entry = MagicMock()
        entry.data = {
            "username": "u",
            "country": "IT",
            "unsupported_commands": ["ARMHOME1"],  # legacy rejection
        }
        alarm._client.config_entry = entry
        alarm.hass.config_entries = MagicMock()

        alarm.client.arm_alarm = AsyncMock(
            side_effect=VerisureOwaError("API error", http_status=400)
        )

        with pytest.raises(HomeAssistantError):
            await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        kwargs = alarm.hass.config_entries.async_update_entry.call_args.kwargs
        persisted = kwargs.get("data", {}).get("unsupported_commands", {})
        installation_num = str(alarm._installation.number)
        assert isinstance(persisted, dict), "Migration should produce dict format"
        # Both the legacy rejection AND the new one must end up under
        # this installation's slot (legacy list was associated with THIS
        # installation's resolver because the resolver-init read both).
        assert "ARMHOME1" in persisted.get(installation_num, [])
        assert "ARMNIGHT1PERI1" in persisted.get(installation_num, [])

    async def test_persist_unsupported_preserves_sibling_installation_slot(self):
        """When entry.data already has the keyed-dict format with another
        installation's rejections, persisting from THIS installation must
        only touch THIS installation's slot — siblings' lists stay intact."""
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        entry = MagicMock()
        entry.data = {
            "username": "u",
            "country": "IT",
            "unsupported_commands": {
                "999999": ["ARMDAY1"],  # sibling installation's rejections
            },
        }
        alarm._client.config_entry = entry
        alarm.hass.config_entries = MagicMock()

        alarm.client.arm_alarm = AsyncMock(
            side_effect=VerisureOwaError("API error", http_status=400)
        )

        with pytest.raises(HomeAssistantError):
            await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        kwargs = alarm.hass.config_entries.async_update_entry.call_args.kwargs
        persisted = kwargs.get("data", {}).get("unsupported_commands", {})
        installation_num = str(alarm._installation.number)
        assert persisted.get("999999") == ["ARMDAY1"], (
            f"Sibling installation 999999 slot was mutated: {persisted!r}"
        )
        assert "ARMNIGHT1PERI1" in persisted.get(installation_num, [])

    async def test_disarm_preserves_protom_response_date_in_state_attrs(self):
        """OperationStatus fields beyond protom_response (notably
        protom_response_date) must survive the disarm path. _build_operation_status
        used to drop everything except operation_status/message/protom_response,
        which broke `update_status_alarm`'s `response_data` extra-state-attribute.
        """
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"

        alarm.client.disarm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="D",
                protom_response_date="2026-05-07T12:00:00Z",
            )
        )

        await alarm.async_alarm_disarm()

        assert (
            alarm._attr_extra_state_attributes.get("response_data")
            == "2026-05-07T12:00:00Z"
        )

    async def test_5xx_error_does_not_mark_command_unsupported(self):
        """Transient 5xx server errors must not permanently blacklist valid commands.

        Marking on any non-None status would let a one-off 503 freeze a working
        command for the rest of the HA session. set_arm_state catches the
        VerisureOwaError; the observable is that the command is NOT in
        the unsupported set and only one API call was attempted (no fallback
        cascade).
        """
        alarm = make_alarm(config=_night_peri_config())
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        alarm.client.arm_alarm = AsyncMock(
            side_effect=VerisureOwaError("Internal server error", http_status=503)
        )

        # set_arm_state catches and handles VerisureOwaError internally
        await alarm.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

        # Command must NOT be marked unsupported on transient server errors
        assert "ARMNIGHT1PERI1" not in alarm._resolver.unsupported
        # No fallback cascade — first attempt should re-raise immediately
        assert alarm.client.arm_alarm.call_count == 1

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
                protom_response_date="",
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
            side_effect=VerisureOwaError(
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
                raise VerisureOwaError(
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
                protom_response_date="",
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
                raise VerisureOwaError("does not exist", http_status=400)
            proto = "T" if command == "ARM1" else "A"
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response=proto,
                protom_response_date="",
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
            "map_home": VerisureOwaState.PARTIAL_DAY_PERI.value,
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
                raise VerisureOwaError("does not exist", http_status=400)
            proto = "P" if command == "ARMDAY1" else "B"
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response=proto,
                protom_response_date="",
            )

        alarm.client.arm_alarm = track_arm

        await alarm.async_alarm_arm_home()

        assert calls == ["ARMDAY1PERI1", "ARMDAY1", "PERI1"]
        assert "ARMDAY1PERI1" in alarm._resolver.unsupported
        assert alarm._state == AlarmControlPanelState.ARMED_HOME


# ===========================================================================
# Dynamic disarm command (based on current state and auto-detection)
# ===========================================================================


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
                protom_response_date="",
            )
        )

        await alarm.async_alarm_disarm()

        alarm.client.disarm_alarm.assert_called_once_with(
            alarm.installation, "DARM1DARMPERI"
        )
        assert alarm._state == AlarmControlPanelState.DISARMED

    async def test_peri_armed_falls_back_to_darm1(self):
        """When DARM1DARMPERI fails with 404 (panel rejects from current state),
        falls back to DARM1.

        Real Spanish panels reject DARM1DARMPERI with a GraphQL ApiError whose
        inner ``data.status`` is 404 ("Requested data not found error") when the
        panel is in a state where the combined disarm isn't supported. The
        executor must treat 404 the same way it treats 400 BAD_USER_INPUT —
        as a panel-side rejection that should fall through to the next
        alternative in the step.
        """
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"  # total_peri = peri armed
        alarm._state = AlarmControlPanelState.ARMED_AWAY

        calls = []

        async def disarm_side_effect(installation, command):
            calls.append(command)
            if command == "DARM1DARMPERI":
                raise VerisureOwaError(
                    "4: Requested data not found error.", http_status=404
                )
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_date="",
            )

        alarm.client.disarm_alarm = disarm_side_effect

        await alarm.async_alarm_disarm()

        assert calls == ["DARM1DARMPERI", "DARM1"]
        assert alarm._state == AlarmControlPanelState.DISARMED
        # 404 is a permanent panel-side rejection, same as 400 — the resolver
        # should have blacklisted the combined command for the session.
        assert "DARM1DARMPERI" in alarm._resolver.unsupported

    async def test_peri_armed_falls_back_to_darm1_on_400(self):
        """When DARM1DARMPERI fails with 400 BAD_USER_INPUT, falls back to DARM1.

        Parallel of ``test_peri_armed_falls_back_to_darm1`` covering the
        original 400 case (command not in panel's ArmCodeRequest enum) — kept
        as a separate test so future refactors can't conflate the two status
        codes and lose coverage of either path.
        """
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"  # total_peri = peri armed
        alarm._state = AlarmControlPanelState.ARMED_AWAY

        calls = []

        async def disarm_side_effect(installation, command):
            calls.append(command)
            if command == "DARM1DARMPERI":
                raise VerisureOwaError(
                    'Variable "$request" got invalid value "DARM1DARMPERI"',
                    http_status=400,
                )
            return OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="D",
                protom_response_date="",
            )

        alarm.client.disarm_alarm = disarm_side_effect

        await alarm.async_alarm_disarm()

        assert calls == ["DARM1DARMPERI", "DARM1"]
        assert alarm._state == AlarmControlPanelState.DISARMED
        assert "DARM1DARMPERI" in alarm._resolver.unsupported

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
                protom_response_date="",
            )
        )

        await alarm.async_alarm_disarm()

        alarm.client.disarm_alarm.assert_called_once_with(alarm.installation, "DARM1")

    async def test_no_peri_config_uses_darm1(self):
        """Without peri config, always sends DARM1."""
        alarm = make_alarm(has_peri=False)
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"  # resolver needs armed proto

        alarm.client.disarm_alarm = AsyncMock(side_effect=VerisureOwaError("API down"))

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
                protom_response_date="",
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
            side_effect=VerisureOwaError("permanent failure", http_status=400)
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
            side_effect=VerisureOwaError(
                "alarm-manager.alarm_process_error", http_status=409
            )
        )

        with patch(
            "custom_components.securitas.alarm_control_panel._base._notify"
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

        _err = VerisureOwaError("API error message", http_status=500)
        _err.response_body = {"response": "data", "auth": "secret-token"}
        alarm.client.disarm_alarm = AsyncMock(side_effect=_err)

        with patch(
            "custom_components.securitas.alarm_control_panel._base._notify"
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
                raise VerisureOwaError(
                    "4: Requested data not found error.", http_status=404
                )
            return OperationStatus(protom_response="D", operation_status="OK")

        alarm.client.disarm_alarm = track_disarm
        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="A",
                protom_response_date="",
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
                VerisureOwaError("unsupported", http_status=400),
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
                VerisureOwaError("unsupported", http_status=400),
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
            side_effect=VerisureOwaError("busy", http_status=409)
        )
        with pytest.raises(VerisureOwaError, match="busy"):
            await alarm._execute_transition(
                AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
            )
        assert "DARM1DARMPERI" not in alarm._resolver.unsupported

    async def test_403_waf_reraises_without_marking_unsupported(self):
        """403 WAF block re-raises immediately without marking command unsupported."""
        alarm = make_alarm(has_peri=True)
        alarm._last_proto_code = "A"
        alarm.client.disarm_alarm = AsyncMock(
            side_effect=VerisureOwaError("HTTP 403 from Securitas API", http_status=403)
        )
        with pytest.raises(VerisureOwaError, match="403"):
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
            side_effect=VerisureOwaError("Disarm command failed: TECHNICAL_ERROR"),
        )
        with pytest.raises(VerisureOwaError, match="TECHNICAL_ERROR"):
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
            side_effect=VerisureOwaError("fail", http_status=400)
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
# Refuse arm/disarm when current state is unknown
# ===========================================================================


class TestExecuteTransitionRefusesUnknownState:
    """When _last_proto_code is None or an unrecognised proto, refuse to act.

    Acting on a stale or unknown current state is the v5.0.0 disarm-fails-when-
    annex-armed bug (#441): the resolver computed a no-op transition off a stale
    'D' and silently skipped DARM1.  We now refuse outright and surface the
    actual code so the user can report it.
    """

    async def test_disarm_refused_when_last_proto_code_none(self):
        """No status poll yet → refuse, do not call disarm_alarm."""
        alarm = make_alarm()
        alarm._last_proto_code = None
        alarm.client.disarm_alarm = AsyncMock()

        with pytest.raises(VerisureOwaError):
            await alarm._execute_transition(
                AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
            )

        alarm.client.disarm_alarm.assert_not_called()

    async def test_arm_refused_when_last_proto_code_none(self):
        """No status poll yet → refuse, do not call arm_alarm."""
        alarm = make_alarm()
        alarm._last_proto_code = None
        alarm.client.arm_alarm = AsyncMock()

        with pytest.raises(VerisureOwaError):
            await alarm._execute_transition(
                AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF)
            )

        alarm.client.arm_alarm.assert_not_called()

    async def test_disarm_refused_when_last_proto_code_unknown_letter(self):
        """Unknown letter (e.g. 'O' on v5.0.0) → refuse rather than silent no-op."""
        alarm = make_alarm()
        alarm._last_proto_code = "Z"  # unrecognised
        alarm.client.disarm_alarm = AsyncMock()

        with pytest.raises(VerisureOwaError):
            await alarm._execute_transition(
                AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
            )

        alarm.client.disarm_alarm.assert_not_called()

    async def test_arm_refused_when_last_proto_code_unknown_letter(self):
        """Unknown letter → refuse arm too, even though resolver could compute a delta."""
        alarm = make_alarm()
        alarm._last_proto_code = "Z"
        alarm.client.arm_alarm = AsyncMock()

        with pytest.raises(VerisureOwaError):
            await alarm._execute_transition(
                AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF)
            )

        alarm.client.arm_alarm.assert_not_called()

    async def test_unknown_state_error_contains_code(self):
        """Refusal message names the unrecognised code so users can report it."""
        alarm = make_alarm()
        alarm._last_proto_code = "Z"

        with pytest.raises(VerisureOwaError) as excinfo:
            await alarm._execute_transition(
                AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
            )

        assert "'Z'" in excinfo.value.message

    async def test_unknown_state_error_points_to_issue_tracker(self):
        """Refusal message points users to the upstream issue tracker."""
        alarm = make_alarm()
        alarm._last_proto_code = "Z"

        with pytest.raises(VerisureOwaError) as excinfo:
            await alarm._execute_transition(
                AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
            )

        assert (
            "github.com/guerrerotook/securitas-direct-new-api/issues"
            in excinfo.value.message
        )

    async def test_disarm_via_public_api_fires_disarm_failed_notification(self):
        """async_alarm_disarm with unknown current state surfaces translated notification."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        alarm._last_proto_code = "Z"
        alarm.client.disarm_alarm = AsyncMock()

        with patch(
            "custom_components.securitas.alarm_control_panel._base._notify"
        ) as mock_notify:
            await alarm.async_alarm_disarm()

        alarm.client.disarm_alarm.assert_not_called()
        mock_notify.assert_called_once()
        args, _ = mock_notify.call_args
        # _notify(hass, notification_id, translation_key, params)
        assert args[2] == "disarm_failed"
        assert "'Z'" in args[3]["error"]

    async def test_arm_via_public_api_fires_arm_failed_notification(self):
        """set_arm_state with unknown current state surfaces translated notification."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        alarm._last_proto_code = "Z"
        alarm.client.arm_alarm = AsyncMock()

        with patch(
            "custom_components.securitas.alarm_control_panel._base._notify"
        ) as mock_notify:
            await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        alarm.client.arm_alarm.assert_not_called()
        mock_notify.assert_called_once()
        args, _ = mock_notify.call_args
        assert args[2] == "arm_failed"
        assert "'Z'" in args[3]["error"]

    async def test_arm_failure_injects_arming_failed_event(self):
        """When the API rejects an arm, inject a HA-side ARMING_FAILED
        event so the activity log surfaces it with HA-user attribution
        (instead of the panel's later polled type-5xx 'Error conectando'
        message — which dedups against this synthetic row via the
        HA_INJECTABLE_CATEGORIES filter in the coordinator)."""
        from custom_components.securitas.verisure_owa_api.models import (
            ActivityCategory,
        )
        from custom_components.securitas.verisure_owa_api.exceptions import (
            VerisureOwaError,
        )

        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._last_proto_code = "D"
        alarm._execute_transition = AsyncMock(side_effect=VerisureOwaError("boom"))

        with (
            patch("custom_components.securitas.alarm_control_panel._base._notify"),
            patch(
                "custom_components.securitas.alarm_control_panel._base.inject_ha_event"
            ) as mock_inject,
        ):
            await alarm.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

        mock_inject.assert_awaited_once()
        kwargs = mock_inject.await_args.kwargs
        assert kwargs["category"] == ActivityCategory.ARMING_FAILED
        assert "Arm failed" in kwargs["alias"]

    async def test_disarm_failure_injects_communication_failed_event(self):
        """A failed disarm round-trip (panel-side comms error) injects
        COMMUNICATION_FAILED so the timeline picks up the failure with HA
        context."""
        from custom_components.securitas.verisure_owa_api.models import (
            ActivityCategory,
        )
        from custom_components.securitas.verisure_owa_api.exceptions import (
            VerisureOwaError,
        )

        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMED_AWAY
        alarm._last_proto_code = "T"
        alarm._execute_transition = AsyncMock(side_effect=VerisureOwaError("boom"))

        with patch(
            "custom_components.securitas.alarm_control_panel._base.inject_ha_event"
        ) as mock_inject:
            await alarm.async_alarm_disarm()

        mock_inject.assert_awaited_once()
        kwargs = mock_inject.await_args.kwargs
        assert kwargs["category"] == ActivityCategory.COMMUNICATION_FAILED
        assert "Disarm failed" in kwargs["alias"]


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
            protom_response_date="",
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
            protom_response_date="",
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
            protom_response_date="",
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
            protom_response_date="",
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
            "custom_components.securitas.alarm_control_panel._base.get_notification_strings",
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
            "custom_components.securitas.alarm_control_panel._base.get_notification_strings",
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
            "custom_components.securitas.alarm_control_panel._base.get_notification_strings",
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
            "custom_components.securitas.alarm_control_panel._base.get_notification_strings",
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
            "custom_components.securitas.alarm_control_panel._base.get_notification_strings",
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
            "custom_components.securitas.alarm_control_panel._base.get_notification_strings",
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
            "custom_components.securitas.alarm_control_panel._base.get_notification_strings",
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
            "custom_components.securitas.alarm_control_panel._base.get_notification_strings",
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
        """async_added_to_hass registers listener for verisure_owa_arming_exception.

        fire_event always emits both names, so subscribing only to the
        recommended verisure_owa_arming_exception form catches every
        emission the integration produces.
        """
        alarm = make_alarm()

        await alarm.async_added_to_hass()

        listen_calls = alarm.hass.bus.async_listen.call_args_list
        arming_exc_calls = [
            c for c in listen_calls if c[0][0] == "verisure_owa_arming_exception"
        ]
        assert len(arming_exc_calls) == 1

    async def test_no_listeners_when_notifications_disabled(self):
        """async_added_to_hass registers no listeners when notifications disabled."""
        alarm = make_alarm(
            config={
                "map_home": STD_DEFAULTS["map_home"],
                "map_away": STD_DEFAULTS["map_away"],
                "map_night": STD_DEFAULTS["map_night"],
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
            protom_response_date="",
        )
        # First call raises ArmingExceptionError, second succeeds
        alarm.client.arm_alarm = AsyncMock(side_effect=[exc, success_result])

        # Register handler (simulates async_added_to_hass)
        alarm._register_arming_exception_handler()
        handler_cb = next(
            c[0][1]
            for c in alarm.hass.bus.async_listen.call_args_list
            if c[0][0] == "verisure_owa_arming_exception"
        )

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
            protom_response_date="",
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


# ===========================================================================


class TestPanelHooks:
    def test_base_resolve_target_state_raises(self):
        from custom_components.securitas.alarm_control_panel import (
            BaseVerisureOwaAlarmPanel,
        )

        with pytest.raises(NotImplementedError):
            BaseVerisureOwaAlarmPanel._resolve_target_state(None, "armed_home")  # type: ignore[arg-type]

    def test_base_extract_state_raises(self):
        from custom_components.securitas.alarm_control_panel import (
            BaseVerisureOwaAlarmPanel,
        )
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
        )

        joint = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        with pytest.raises(NotImplementedError):
            BaseVerisureOwaAlarmPanel._extract_state(None, joint)  # type: ignore[arg-type]


# ===========================================================================
# InteriorVerisureOwaAlarmPanel sub-panel tests (Task 13)
# ===========================================================================


def _make_interior_panel(
    capabilities: frozenset = frozenset(["ARM", "ARMDAY", "ARMNIGHT"]),
    current_state=None,
):
    """Build an InteriorVerisureOwaAlarmPanel with mocked dependencies."""
    from custom_components.securitas.alarm_control_panel import (
        InteriorVerisureOwaAlarmPanel,
    )
    from custom_components.securitas.verisure_owa_api.models import (
        AnnexMode,
        InteriorMode,
        PerimeterMode,
    )

    if current_state is None:
        current_state = AlarmState(
            interior=InteriorMode.OFF,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.OFF,
        )

    coordinator = MagicMock()
    coordinator.has_peri = "PERI" in capabilities
    coordinator.has_annex = "ARMANNEX" in capabilities and "DARMANNEX" in capabilities
    coordinator.capabilities = capabilities
    coordinator.alarm_state = current_state

    installation = MagicMock()
    installation.number = "12345"
    installation.alias = "TestHome"
    installation.address = "123 Test St"

    client = MagicMock()
    client.config = {}

    hass = MagicMock()

    with (
        patch.object(
            InteriorVerisureOwaAlarmPanel, "async_schedule_update_ha_state", MagicMock()
        ),
        patch.object(
            InteriorVerisureOwaAlarmPanel, "async_write_ha_state", MagicMock()
        ),
    ):
        panel = InteriorVerisureOwaAlarmPanel(installation, client, hass, coordinator)
    panel.async_schedule_update_ha_state = MagicMock()
    panel.async_write_ha_state = MagicMock()
    return panel


def _make_perimeter_panel(
    capabilities: frozenset = frozenset(["PERI"]),
    current_state=None,
):
    """Build a PerimeterVerisureOwaAlarmPanel with mocked dependencies."""
    from custom_components.securitas.alarm_control_panel import (
        PerimeterVerisureOwaAlarmPanel,
    )
    from custom_components.securitas.verisure_owa_api.models import (
        AnnexMode,
        InteriorMode,
        PerimeterMode,
    )

    if current_state is None:
        current_state = AlarmState(
            interior=InteriorMode.OFF,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.OFF,
        )

    coordinator = MagicMock()
    coordinator.has_peri = "PERI" in capabilities
    coordinator.has_annex = "ARMANNEX" in capabilities and "DARMANNEX" in capabilities
    coordinator.capabilities = capabilities
    coordinator.alarm_state = current_state

    installation = MagicMock()
    installation.number = "12345"
    installation.alias = "TestHome"
    installation.address = "123 Test St"

    client = MagicMock()
    client.config = {}

    hass = MagicMock()

    with (
        patch.object(
            PerimeterVerisureOwaAlarmPanel,
            "async_schedule_update_ha_state",
            MagicMock(),
        ),
        patch.object(
            PerimeterVerisureOwaAlarmPanel, "async_write_ha_state", MagicMock()
        ),
    ):
        return PerimeterVerisureOwaAlarmPanel(installation, client, hass, coordinator)


class TestSubPanelSuggestedObjectId:
    """Sub-panels must seed a single-alias entity_id slot.

    HA's entity_platform routes ``entity.suggested_object_id`` into the
    registry's ``object_id_base`` parameter, and HA 2026.5+ unconditionally
    prepends the device name onto ``object_id_base`` (for entities with
    ``has_entity_name=False``) — running a strip-prefix heuristic first to
    avoid doubling the name. That heuristic only recognises space, dash, or
    colon as the separator following the matched prefix; an underscore
    between ``<alias>`` and ``_<circuit>`` is NOT stripped, so the device
    name ends up prepended twice and the entity_id comes out as
    ``alarm_control_panel.<alias>_<alias>_<circuit>`` (the "doubled-alias
    collision form").

    The sub-panel mixin therefore returns ``"<alias> <circuit>"`` (space
    separator) from ``suggested_object_id`` — the space satisfies the
    strip-prefix heuristic on HA 2026.5+ and slugify still maps to the
    canonical ``<alias>_<circuit>`` slot in every supported HA version.
    """

    def test_interior(self):
        panel = _make_interior_panel()
        assert panel.suggested_object_id == "TestHome interior"

    def test_perimeter(self):
        panel = _make_perimeter_panel()
        assert panel.suggested_object_id == "TestHome perimeter"

    def test_annex(self):
        panel = _make_annex_panel()
        assert panel.suggested_object_id == "TestHome annex"

    @pytest.mark.skipif(
        not _HAS_OBJECT_ID_BASE_KWARG,
        reason=(
            "object_id_base kwarg on async_get_or_create was added after our "
            "minimum-supported HA (2025.2). The doubled-alias bug this test "
            "guards against is HA 2026.5+ behaviour — no point reproducing "
            "it on older HA where the registry-create path differs."
        ),
    )
    @pytest.mark.parametrize(
        "suffix,panel_factory",
        [
            ("_interior", _make_interior_panel),
            ("_perimeter", _make_perimeter_panel),
        ],
    )
    async def test_subpanel_entity_id_canonical_through_real_registry(
        self, hass, suffix, panel_factory
    ):
        """End-to-end regression: the mixin's ``suggested_object_id`` must
        produce ``alarm_control_panel.<alias>_<circuit>`` after going through
        HA's real ``async_get_or_create`` path with a device attached.

        Mirrors the call entity_platform makes for a fresh install: the
        property value lands in ``object_id_base``, HA prepends the device
        name and runs strip-prefix to undo the doubling. A space separator
        in the property's return value is what lets strip-prefix succeed on
        HA 2026.5+.

        Reproduces the doubled-alias bug regression if the separator regresses
        to an underscore (HA 2026.5+); also locks in the right outcome on HA
        < 2026.5 where the device name isn't prepended at all.
        """
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        from custom_components.securitas.const import DOMAIN

        entry = MockConfigEntry(domain=DOMAIN, data={"unsupported_commands": []})
        entry.add_to_hass(hass)

        # Device name == installation.alias — this is the prefix HA 2026.5+
        # would otherwise prepend onto object_id_base, doubling the alias.
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "v4_securitas_direct.12345")},
            name="TestHome",
            manufacturer="Verisure",
        )

        panel = panel_factory()
        # entity_platform routes entity.suggested_object_id into object_id_base
        # (because the entity doesn't set internal_integration_suggested_object_id).
        ent_reg = er.async_get(hass)
        registered = ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            panel.unique_id,
            object_id_base=panel.suggested_object_id,
            suggested_object_id=None,
            has_entity_name=panel.has_entity_name,
            original_name=panel.name,
            device_id=device.id,
            config_entry=entry,
        )
        assert registered.entity_id == f"alarm_control_panel.testhome{suffix}"


class TestInteriorSubPanel:
    def test_supported_features_all_three_when_nothing_unsupported(self):
        """Interior sub-panel exposes ARM_HOME + ARM_NIGHT + ARM_AWAY by default.

        We deliberately do not gate on JWT capabilities: the cap set is
        empirically unreliable (e.g. Italian SDVECU advertises ARMNIGHT but
        the panel rejects ARMNIGHT1 and accepts the un-advertised ARMDAY1).
        """
        from homeassistant.components.alarm_control_panel import (
            AlarmControlPanelEntityFeature as F,
        )

        for caps in (
            frozenset(["ARM", "ARMDAY", "ARMNIGHT"]),
            frozenset(["ARM", "ARMNIGHT"]),
            frozenset(["ARM"]),
            frozenset(),
        ):
            panel = _make_interior_panel(capabilities=caps)
            feats = panel.supported_features
            assert feats & F.ARM_HOME, f"ARM_HOME missing for caps={caps}"
            assert feats & F.ARM_NIGHT, f"ARM_NIGHT missing for caps={caps}"
            assert feats & F.ARM_AWAY, f"ARM_AWAY missing for caps={caps}"

    def test_supported_features_drops_arm_night_when_armnight1_unsupported(self):
        """Once the panel has rejected ARMNIGHT1 (typical Italian SDVECU
        behaviour), the Interior sub-panel must stop offering ARM_NIGHT —
        otherwise the user keeps pressing a button that's known to fail.
        """
        from homeassistant.components.alarm_control_panel import (
            AlarmControlPanelEntityFeature as F,
        )

        panel = _make_interior_panel()
        panel._resolver.mark_unsupported("ARMNIGHT1")

        feats = panel.supported_features
        assert feats & F.ARM_HOME, "ARM_HOME should still be available"
        assert not (feats & F.ARM_NIGHT), (
            "ARM_NIGHT must be dropped after ARMNIGHT1 was rejected"
        )
        assert feats & F.ARM_AWAY, "ARM_AWAY should still be available"

    def test_supported_features_drops_arm_home_when_armday1_unsupported(self):
        """Symmetric: ARMDAY1 rejected ⇒ no ARM_HOME on the sub-panel."""
        from homeassistant.components.alarm_control_panel import (
            AlarmControlPanelEntityFeature as F,
        )

        panel = _make_interior_panel()
        panel._resolver.mark_unsupported("ARMDAY1")

        feats = panel.supported_features
        assert not (feats & F.ARM_HOME)
        assert feats & F.ARM_NIGHT
        assert feats & F.ARM_AWAY

    def test_supported_features_drops_arm_away_when_arm1_unsupported(self):
        """Symmetric: ARM1 rejected ⇒ no ARM_AWAY on the sub-panel."""
        from homeassistant.components.alarm_control_panel import (
            AlarmControlPanelEntityFeature as F,
        )

        panel = _make_interior_panel()
        panel._resolver.mark_unsupported("ARM1")

        feats = panel.supported_features
        assert feats & F.ARM_HOME
        assert feats & F.ARM_NIGHT
        assert not (feats & F.ARM_AWAY)

    def _make_subpanel_with_persisted_unsupported(self, persisted, installation_num):
        """Build an InteriorVerisureOwaAlarmPanel where ``client.config`` has
        the given ``unsupported_commands`` payload and the panel's
        ``installation.number`` is ``installation_num``.

        Shared helper for the resolver-hydration tests below (flat-list
        back-compat and per-installation dict format).
        """
        from custom_components.securitas.alarm_control_panel import (
            InteriorVerisureOwaAlarmPanel,
        )
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        coordinator = MagicMock()
        coordinator.has_peri = False
        coordinator.has_annex = False
        coordinator.alarm_state = AlarmState(
            interior=InteriorMode.OFF,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.OFF,
        )
        installation = MagicMock(number=installation_num, alias="A", address="x")
        client = MagicMock()
        client.config = {"unsupported_commands": persisted}
        hass = MagicMock()
        with (
            patch.object(
                InteriorVerisureOwaAlarmPanel,
                "async_schedule_update_ha_state",
                MagicMock(),
            ),
            patch.object(
                InteriorVerisureOwaAlarmPanel, "async_write_ha_state", MagicMock()
            ),
        ):
            return InteriorVerisureOwaAlarmPanel(
                installation, client, hass, coordinator
            )

    def test_hydrates_unsupported_from_legacy_flat_list(self):
        """Resolver starts pre-loaded with the persisted unsupported list so
        a previously-rejected command stays rejected across HA restarts.

        Legacy flat-list format (a bare list applied to every installation
        on the entry) must keep working — that's the v5.0.1-pre format,
        and an upgraded install needs the existing rejections to survive
        until the panel re-persists in the new keyed-dict shape.
        """
        panel = self._make_subpanel_with_persisted_unsupported(
            persisted=["ARMNIGHT1"], installation_num="1"
        )
        assert "ARMNIGHT1" in panel._resolver.unsupported

    def test_hydrates_unsupported_from_per_installation_dict(self):
        """New keyed-dict format scopes ``unsupported_commands`` per
        installation. Only the rejections under THIS installation's number
        are loaded into the resolver — siblings on the same legacy entry
        keep their own slot."""
        panel = self._make_subpanel_with_persisted_unsupported(
            persisted={"1": ["ARMNIGHT1"], "2": ["ARMDAY1"]},
            installation_num="1",
        )
        assert "ARMNIGHT1" in panel._resolver.unsupported
        assert "ARMDAY1" not in panel._resolver.unsupported, (
            "Rejections from another installation on the same entry must "
            "not contaminate this installation's resolver"
        )

    def test_dict_format_empty_when_installation_missing(self):
        """If the dict has no slot for THIS installation, the resolver
        starts empty — siblings' rejections don't apply."""
        panel = self._make_subpanel_with_persisted_unsupported(
            persisted={"42": ["ARMNIGHT1"]},
            installation_num="1",
        )
        assert "ARMNIGHT1" not in panel._resolver.unsupported

    def test_no_persisted_data_starts_empty(self):
        """Missing key entirely should yield an empty resolver."""
        from custom_components.securitas.alarm_control_panel import (
            InteriorVerisureOwaAlarmPanel,
        )
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        coordinator = MagicMock()
        coordinator.has_peri = False
        coordinator.has_annex = False
        coordinator.alarm_state = AlarmState(
            interior=InteriorMode.OFF,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.OFF,
        )
        installation = MagicMock(number="1", alias="A", address="x")
        client = MagicMock()
        client.config = {}  # no unsupported_commands key at all
        hass = MagicMock()
        with (
            patch.object(
                InteriorVerisureOwaAlarmPanel,
                "async_schedule_update_ha_state",
                MagicMock(),
            ),
            patch.object(
                InteriorVerisureOwaAlarmPanel, "async_write_ha_state", MagicMock()
            ),
        ):
            panel = InteriorVerisureOwaAlarmPanel(
                installation, client, hass, coordinator
            )
        assert panel._resolver.unsupported == frozenset()

    async def test_subpanel_raises_subpanel_error_when_command_unsupported(self):
        """Sub-panels have no user-editable mappings, so the rejection
        notification must use a sub-panel-specific translation key — not
        the main-panel one that points the user at the (non-existent)
        mappings UI."""
        from custom_components.securitas.verisure_owa_api import (
            VerisureOwaError,
        )
        from custom_components.securitas.verisure_owa_api.command_resolver import (
            CommandStep,
        )

        panel = _make_interior_panel()
        panel.client.arm_alarm = AsyncMock(
            side_effect=VerisureOwaError("rejected", http_status=400)
        )

        with pytest.raises(HomeAssistantError) as excinfo:
            await panel._execute_step(CommandStep(commands=["ARMNIGHT1"]))

        assert excinfo.value.translation_key == "unsupported_alarm_mode_subpanel"

    def test_resolve_target_state_armed_away(self):
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        panel = _make_interior_panel(
            capabilities=frozenset(["ARM", "ARMDAY", "ARMNIGHT"]),
            current_state=AlarmState(
                interior=InteriorMode.OFF,
                perimeter=PerimeterMode.ON,
                annex=AnnexMode.ON,
            ),
        )
        target = panel._resolve_target_state("armed_away")
        assert target.interior == InteriorMode.TOTAL
        # Other axes preserved
        assert target.perimeter == PerimeterMode.ON
        assert target.annex == AnnexMode.ON

    def test_resolve_target_disarmed_preserves_perimeter_and_annex(self):
        """Disarming the interior sub-panel must NOT touch perimeter or annex."""
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        panel = _make_interior_panel(
            capabilities=frozenset(["ARM", "ARMDAY", "ARMNIGHT"]),
            current_state=AlarmState(
                interior=InteriorMode.DAY,
                perimeter=PerimeterMode.ON,
                annex=AnnexMode.ON,
            ),
        )
        target = panel._resolve_target_state("disarmed")
        assert target.interior == InteriorMode.OFF
        assert target.perimeter == PerimeterMode.ON  # preserved
        assert target.annex == AnnexMode.ON  # preserved

    def test_extract_state_only_reads_interior(self):
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        panel = _make_interior_panel(
            capabilities=frozenset(["ARM", "ARMDAY", "ARMNIGHT"])
        )
        s = panel._extract_state(
            AlarmState(
                interior=InteriorMode.NIGHT,
                perimeter=PerimeterMode.ON,
                annex=AnnexMode.OFF,
            )
        )
        from homeassistant.components.alarm_control_panel import AlarmControlPanelState

        assert s == AlarmControlPanelState.ARMED_NIGHT

    def test_unique_id_suffix(self):
        panel = _make_interior_panel(capabilities=frozenset(["ARM"]))
        assert panel.unique_id is not None
        assert panel.unique_id.endswith("_interior")


class TestPerimeterSubPanel:
    def test_supported_features_only_arm_away(self):
        from homeassistant.components.alarm_control_panel import (
            AlarmControlPanelEntityFeature as F,
        )

        panel = _make_perimeter_panel()
        feats = panel.supported_features
        assert feats & F.ARM_AWAY
        assert not (feats & F.ARM_HOME)
        assert not (feats & F.ARM_NIGHT)

    def test_supported_features_drops_arm_away_when_peri1_unsupported(self):
        """If the panel has rejected ``PERI1`` (the only arm-perimeter
        command on the Perimeter sub-panel's standalone-axis branch), the
        sub-panel must stop offering ``ARM_AWAY`` — otherwise the user
        keeps pressing a button that's known to fail. Mirror of the
        Interior sub-panel's ``ARMNIGHT1`` drop.
        """
        from homeassistant.components.alarm_control_panel import (
            AlarmControlPanelEntityFeature as F,
        )

        panel = _make_perimeter_panel()
        panel._resolver.mark_unsupported("PERI1")

        feats = panel.supported_features
        assert not (feats & F.ARM_AWAY), (
            "ARM_AWAY must be dropped after PERI1 was rejected"
        )

    def test_recompute_supported_features_drops_arm_away_too(self):
        """``_recompute_supported_features`` is what propagates the
        feature change to the entity registry (HA's cached_property and
        the auto-update path read ``_attr_supported_features`` rather
        than the @property). It has to agree with the live property."""
        panel = _make_perimeter_panel()
        panel._resolver.mark_unsupported("PERI1")
        panel._recompute_supported_features()
        assert panel._attr_supported_features == panel.supported_features

    def test_resolve_target_armed_away(self):
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        panel = _make_perimeter_panel(
            current_state=AlarmState(
                interior=InteriorMode.TOTAL,
                perimeter=PerimeterMode.OFF,
                annex=AnnexMode.ON,
            )
        )
        s = panel._resolve_target_state("armed_away")
        assert s.perimeter == PerimeterMode.ON
        assert s.interior == InteriorMode.TOTAL  # preserved
        assert s.annex == AnnexMode.ON  # preserved

    def test_resolve_target_disarmed_preserves_interior_and_annex(self):
        """Disarming the perimeter sub-panel must NOT touch interior or annex."""
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        panel = _make_perimeter_panel(
            current_state=AlarmState(
                interior=InteriorMode.DAY,
                perimeter=PerimeterMode.ON,
                annex=AnnexMode.ON,
            )
        )
        s = panel._resolve_target_state("disarmed")
        assert s.perimeter == PerimeterMode.OFF
        assert s.interior == InteriorMode.DAY  # preserved
        assert s.annex == AnnexMode.ON  # preserved

    async def test_async_alarm_disarm_uses_axis_projection_not_full_disarm(self):
        """Regression: async_alarm_disarm must call _resolve_target_state, not hardcode full-disarm.

        The bug: pressing Disarm on the Perimeter sub-panel sent DARM1DARMPERI
        (full disarm) and on fallback DARM1, which on SDVFAST disarms everything
        — wiping interior even though the user only meant to disarm perimeter.
        """
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        panel = _make_perimeter_panel(
            current_state=AlarmState(
                interior=InteriorMode.DAY,
                perimeter=PerimeterMode.ON,
                annex=AnnexMode.OFF,
            )
        )
        panel._check_code = MagicMock(return_value=True)
        panel._execute_transition = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                numinst="123456",
                protom_response="P",  # PARTIAL_DAY (interior=DAY preserved, peri off)
                protom_response_date="",
            )
        )
        panel.coordinator.async_request_refresh = AsyncMock()
        panel.async_write_ha_state = MagicMock()

        await panel.async_alarm_disarm()

        panel._execute_transition.assert_called_once()
        target = panel._execute_transition.call_args[0][0]
        assert target.perimeter == PerimeterMode.OFF
        assert target.interior == InteriorMode.DAY  # preserved
        assert target.annex == AnnexMode.OFF  # preserved

    def test_extract_state(self):
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )
        from homeassistant.components.alarm_control_panel import AlarmControlPanelState

        panel = _make_perimeter_panel()
        on = panel._extract_state(
            AlarmState(
                interior=InteriorMode.OFF,
                perimeter=PerimeterMode.ON,
                annex=AnnexMode.OFF,
            )
        )
        off = panel._extract_state(
            AlarmState(
                interior=InteriorMode.OFF,
                perimeter=PerimeterMode.OFF,
                annex=AnnexMode.OFF,
            )
        )
        assert on == AlarmControlPanelState.ARMED_AWAY
        assert off == AlarmControlPanelState.DISARMED

    def test_unique_id_suffix(self):
        panel = _make_perimeter_panel()
        assert panel.unique_id is not None
        assert panel.unique_id.endswith("_perimeter")


def _make_annex_panel(
    capabilities: frozenset = frozenset(["ARMANNEX", "DARMANNEX"]),
    current_state=None,
):
    """Build an AnnexVerisureOwaAlarmPanel with mocked dependencies."""
    from custom_components.securitas.alarm_control_panel import (
        AnnexVerisureOwaAlarmPanel,
    )
    from custom_components.securitas.verisure_owa_api.models import (
        AnnexMode,
        InteriorMode,
        PerimeterMode,
    )

    if current_state is None:
        current_state = AlarmState(
            interior=InteriorMode.OFF,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.OFF,
        )

    coordinator = MagicMock()
    coordinator.has_peri = "PERI" in capabilities
    coordinator.has_annex = "ARMANNEX" in capabilities and "DARMANNEX" in capabilities
    coordinator.capabilities = capabilities
    coordinator.alarm_state = current_state

    installation = MagicMock()
    installation.number = "12345"
    installation.alias = "TestHome"
    installation.address = "123 Test St"

    client = MagicMock()
    client.config = {}

    hass = MagicMock()

    with (
        patch.object(
            AnnexVerisureOwaAlarmPanel, "async_schedule_update_ha_state", MagicMock()
        ),
        patch.object(AnnexVerisureOwaAlarmPanel, "async_write_ha_state", MagicMock()),
    ):
        return AnnexVerisureOwaAlarmPanel(installation, client, hass, coordinator)


class TestAnnexSubPanel:
    def test_supported_features_only_arm_away(self):
        from homeassistant.components.alarm_control_panel import (
            AlarmControlPanelEntityFeature as F,
        )

        panel = _make_annex_panel()
        feats = panel.supported_features
        assert feats & F.ARM_AWAY
        assert not (feats & F.ARM_HOME)
        assert not (feats & F.ARM_NIGHT)

    def test_supported_features_drops_arm_away_when_armannex1_unsupported(self):
        """If the panel has rejected ``ARMANNEX1`` (the only arm-annex
        wire command), the Annex sub-panel must stop offering
        ``ARM_AWAY``."""
        from homeassistant.components.alarm_control_panel import (
            AlarmControlPanelEntityFeature as F,
        )

        panel = _make_annex_panel()
        panel._resolver.mark_unsupported("ARMANNEX1")

        feats = panel.supported_features
        assert not (feats & F.ARM_AWAY), (
            "ARM_AWAY must be dropped after ARMANNEX1 was rejected"
        )

    def test_recompute_supported_features_drops_arm_away_too(self):
        panel = _make_annex_panel()
        panel._resolver.mark_unsupported("ARMANNEX1")
        panel._recompute_supported_features()
        assert panel._attr_supported_features == panel.supported_features

    def test_resolve_armed_away_preserves_other_axes(self):
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        panel = _make_annex_panel(
            current_state=AlarmState(
                interior=InteriorMode.DAY,
                perimeter=PerimeterMode.ON,
                annex=AnnexMode.OFF,
            )
        )
        s = panel._resolve_target_state("armed_away")
        assert s.annex == AnnexMode.ON
        assert s.interior == InteriorMode.DAY
        assert s.perimeter == PerimeterMode.ON

    def test_resolve_target_disarmed_preserves_interior_and_perimeter(self):
        """Disarming the annex sub-panel must NOT touch interior or perimeter."""
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        panel = _make_annex_panel(
            current_state=AlarmState(
                interior=InteriorMode.DAY,
                perimeter=PerimeterMode.ON,
                annex=AnnexMode.ON,
            )
        )
        s = panel._resolve_target_state("disarmed")
        assert s.annex == AnnexMode.OFF
        assert s.interior == InteriorMode.DAY  # preserved
        assert s.perimeter == PerimeterMode.ON  # preserved

    def test_extract_state(self):
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )
        from homeassistant.components.alarm_control_panel import AlarmControlPanelState

        panel = _make_annex_panel()
        on = panel._extract_state(
            AlarmState(
                interior=InteriorMode.OFF,
                perimeter=PerimeterMode.OFF,
                annex=AnnexMode.ON,
            )
        )
        off = panel._extract_state(
            AlarmState(
                interior=InteriorMode.OFF,
                perimeter=PerimeterMode.OFF,
                annex=AnnexMode.OFF,
            )
        )
        assert on == AlarmControlPanelState.ARMED_AWAY
        assert off == AlarmControlPanelState.DISARMED

    def test_unique_id_suffix(self):
        panel = _make_annex_panel()
        assert panel.unique_id is not None
        assert panel.unique_id.endswith("_annex")


# ===========================================================================
# TestSubPanelStateExtraction — Issue 1: sub-panels must use _extract_state
# ===========================================================================


class TestSubPanelStateExtraction:
    """Sub-panels project the joint coordinator state onto their axis.

    These tests verify that _update_from_coordinator and update_status_alarm
    use _extract_state(coordinator.alarm_state) — NOT _status_map[proto_code].
    """

    def test_interior_update_from_coordinator_uses_extract_state(self):
        """Interior panel derives state from joint state, ignoring user mapping."""
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        # Joint state: interior=NIGHT, perimeter=ON  → proto_code "C" (PARTIAL_NIGHT_PERI)
        # The combined panel's _status_map might map "C" to any user-chosen HA state,
        # but the interior sub-panel must read only the interior axis: ARMED_NIGHT.
        joint = AlarmState(
            interior=InteriorMode.NIGHT,
            perimeter=PerimeterMode.ON,
            annex=AnnexMode.OFF,
        )
        panel = _make_interior_panel(
            capabilities=frozenset(["ARM", "ARMDAY", "ARMNIGHT"]),
            current_state=joint,
        )
        # Feed proto code "C" (PARTIAL_NIGHT_PERI) through the coordinator path
        data = AlarmStatusData(status=SStatus(status="C"), protom_response="C")
        panel._update_from_coordinator(data)

        assert panel._state == AlarmControlPanelState.ARMED_NIGHT

    def test_interior_update_from_coordinator_disarmed(self):
        """Interior panel shows DISARMED when joint interior axis is OFF."""
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        joint = AlarmState(
            interior=InteriorMode.OFF,
            perimeter=PerimeterMode.ON,
            annex=AnnexMode.OFF,
        )
        panel = _make_interior_panel(
            capabilities=frozenset(["ARM", "ARMDAY", "ARMNIGHT"]),
            current_state=joint,
        )
        # Proto code "E" = PERIMETER_ONLY (interior=OFF, perimeter=ON)
        data = AlarmStatusData(status=SStatus(status="E"), protom_response="E")
        panel._update_from_coordinator(data)

        assert panel._state == AlarmControlPanelState.DISARMED

    def test_interior_update_status_alarm_uses_extract_state(self):
        """update_status_alarm uses _extract_state after a successful arm operation."""
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        # After arming interior to DAY+PERI, the API returns proto_code "B"
        # (PARTIAL_DAY_PERI = AlarmState(DAY, ON)).  The interior axis is DAY
        # → ARMED_HOME.  The combined-panel's _status_map might map "B" to
        # something else, but interior sub-panel must read only the interior axis.
        joint = AlarmState(
            interior=InteriorMode.DAY,
            perimeter=PerimeterMode.ON,
            annex=AnnexMode.OFF,
        )
        panel = _make_interior_panel(
            capabilities=frozenset(["ARM", "ARMDAY", "ARMNIGHT"]),
            current_state=joint,
        )
        op_status = OperationStatus(
            operation_status="OK",
            message="",
            protom_response="B",
            protom_response_date="",
            status="B",
        )
        panel.update_status_alarm(op_status)

        assert panel._state == AlarmControlPanelState.ARMED_HOME

    def test_perimeter_update_from_coordinator_uses_extract_state(self):
        """Perimeter panel derives state from perimeter axis only."""
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        joint = AlarmState(
            interior=InteriorMode.NIGHT,
            perimeter=PerimeterMode.ON,
            annex=AnnexMode.OFF,
        )
        panel = _make_perimeter_panel(
            capabilities=frozenset(["PERI"]),
            current_state=joint,
        )
        data = AlarmStatusData(status=SStatus(status="C"), protom_response="C")
        panel._update_from_coordinator(data)

        assert panel._state == AlarmControlPanelState.ARMED_AWAY

    def test_perimeter_update_from_coordinator_off(self):
        """Perimeter panel shows DISARMED when perimeter axis is OFF."""
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        joint = AlarmState(
            interior=InteriorMode.NIGHT,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.OFF,
        )
        panel = _make_perimeter_panel(
            capabilities=frozenset(["PERI"]),
            current_state=joint,
        )
        # Proto code "Q" = PARTIAL_NIGHT (interior=NIGHT, perimeter=OFF)
        data = AlarmStatusData(status=SStatus(status="Q"), protom_response="Q")
        panel._update_from_coordinator(data)

        assert panel._state == AlarmControlPanelState.DISARMED

    def test_annex_update_from_coordinator_uses_extract_state(self):
        """Annex panel derives state from annex axis only."""
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        joint = AlarmState(
            interior=InteriorMode.TOTAL,
            perimeter=PerimeterMode.ON,
            annex=AnnexMode.ON,
        )
        panel = _make_annex_panel(
            capabilities=frozenset(["ARMANNEX", "DARMANNEX"]),
            current_state=joint,
        )
        data = AlarmStatusData(status=SStatus(status="T"), protom_response="T")
        panel._update_from_coordinator(data)

        assert panel._state == AlarmControlPanelState.ARMED_AWAY

    def test_annex_update_from_coordinator_off(self):
        """Annex panel shows DISARMED when annex axis is OFF."""
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        joint = AlarmState(
            interior=InteriorMode.TOTAL,
            perimeter=PerimeterMode.ON,
            annex=AnnexMode.OFF,
        )
        panel = _make_annex_panel(
            capabilities=frozenset(["ARMANNEX", "DARMANNEX"]),
            current_state=joint,
        )
        data = AlarmStatusData(status=SStatus(status="T"), protom_response="T")
        panel._update_from_coordinator(data)

        assert panel._state == AlarmControlPanelState.DISARMED

    def test_combined_panel_unaffected_uses_status_map(self):
        """Combined panel still uses _status_map lookup (backward compat check)."""
        alarm = make_alarm()
        # The combined panel's _status_map maps proto "T" to armed_away by default
        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="T"), protom_response="T"
        )
        alarm._update_from_coordinator(alarm.coordinator.data)
        assert alarm._state == AlarmControlPanelState.ARMED_AWAY

    def test_annex_proto_codes_are_recognised(self):
        """Annex proto codes (X/R/S/O) must trigger state updates.

        Regression: an earlier check used const.PROTO_TO_STATE (8 entries,
        no annex) instead of PROTO_TO_ALARM_STATE (12 entries, includes
        annex codes). Without this fix, an annex-bearing state report
        ('X' = ANNEX_ONLY) would be treated as unknown — _last_proto_code
        wouldn't update and the resolver could compute transitions from
        a stale state.
        """
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        joint = AlarmState(
            interior=InteriorMode.OFF,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.ON,
        )
        panel = _make_annex_panel(
            capabilities=frozenset(["ARMANNEX", "DARMANNEX"]),
            current_state=joint,
        )
        # Proto code "X" = ANNEX_ONLY
        data = AlarmStatusData(status=SStatus(status="X"), protom_response="X")
        panel._update_from_coordinator(data)

        assert panel._state == AlarmControlPanelState.ARMED_AWAY
        assert panel._last_proto_code == "X"

    def test_subpanel_preserves_state_on_unknown_proto_code(self):
        """Unknown proto code must NOT silently flip the sub-panel to DISARMED.

        Regression: coordinator.alarm_state defaults to all-OFF when the proto
        code isn't recognised. Without guarding, _extract_state would then
        report DISARMED — wrong if the system is actually armed.
        """
        from custom_components.securitas.verisure_owa_api.models import (
            AnnexMode,
            InteriorMode,
            PerimeterMode,
        )

        joint = AlarmState(
            interior=InteriorMode.TOTAL,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.OFF,
        )
        panel = _make_perimeter_panel(current_state=joint)
        panel._state = AlarmControlPanelState.DISARMED  # last known
        # Feed an unknown status string (not a proto code letter)
        data = AlarmStatusData(
            status=SStatus(status="UNKNOWN_STATUS"), protom_response=""
        )
        panel._update_from_coordinator(data)
        # State preserved; not flipped via fallback all-OFF joint
        assert panel._state == AlarmControlPanelState.DISARMED


class TestResolverCapabilityRefresh:
    """The resolver is built at entity construction; capability detection
    can complete *after* that (e.g. transient API errors at startup that
    succeed on retry). The entity must refresh the resolver's flags from
    the coordinator on each update so it doesn't get stuck with stale flags.
    """

    def test_entity_refreshes_resolver_has_peri_on_coordinator_update(self):
        """When coordinator.has_peri flips False→True after entity construction,
        the next coordinator update must propagate the new flag to the resolver.
        """
        alarm = make_alarm(has_peri=False)
        assert alarm._resolver._has_peri is False

        # Capability detection now succeeds on a later refresh
        alarm.coordinator.has_peri = True

        # Coordinator delivers an update — entity must propagate
        data = AlarmStatusData(status=SStatus(status="D"), protom_response="D")
        alarm._update_from_coordinator(data)

        assert alarm._resolver._has_peri is True


# ===========================================================================
# TestSubPanelSetup — conditional instantiation in async_setup_entry (Task 16)
# ===========================================================================


class TestSubPanelSetup:
    """Tests for conditional sub-panel instantiation in async_setup_entry."""

    def _setup_kwargs(self, *, options: dict, has_peri: bool, has_annex: bool):
        """Build hass/entry/coordinator suitable for invoking async_setup_entry."""
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas import (
            VerisureDevice,
        )

        installation = Installation(
            number="123456",
            alias="Home",
            panel="SDVFAST",
            type="PLUS",
            address="123 St",
            city="Madrid",
        )
        device = MagicMock(spec=VerisureDevice)
        device.installation = installation

        client = MagicMock()
        client.config = {
            "map_home": STD_DEFAULTS["map_home"],
            "map_away": STD_DEFAULTS["map_away"],
            "map_night": STD_DEFAULTS["map_night"],
            "scan_interval": 120,
        }

        coordinator = MagicMock(spec=AlarmCoordinator)
        coordinator.has_peri = has_peri
        coordinator.has_annex = has_annex
        coordinator.capabilities = frozenset()
        coordinator.data = None

        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "entry-id": {
                    "hub": client,
                    "alarm_coordinator": coordinator,
                    "devices": [device],
                },
            },
        }

        entry = MagicMock()
        entry.entry_id = "entry-id"
        entry.options = options
        return hass, entry

    @pytest.mark.asyncio
    async def test_only_combined_when_no_toggles(self):
        from custom_components.securitas.alarm_control_panel import (
            async_setup_entry,
            CombinedVerisureOwaAlarmPanel,
        )

        hass, entry = self._setup_kwargs(options={}, has_peri=True, has_annex=True)
        added: list = []

        def add(entities, _update_before_add=False):
            added.extend(entities)

        with patch(
            "custom_components.securitas.alarm_control_panel.async_get_current_platform"
        ):
            await async_setup_entry(hass, entry, add)
        assert len(added) == 1
        assert isinstance(added[0], CombinedVerisureOwaAlarmPanel)

    @pytest.mark.asyncio
    async def test_perimeter_panel_created_when_toggle_on_even_if_caps_not_yet_detected(
        self,
    ):
        """Toggle is the source of truth — the options flow already gates the
        toggle on capability, so a saved toggle implies capability was supported
        at config time. If capability pre-population fails at setup (transient
        API error), the entity must still be created so a later background
        refresh sees the entity ready to serve. Otherwise the user has to
        reload the integration to recover.
        """
        from custom_components.securitas.alarm_control_panel import (
            async_setup_entry,
            PerimeterVerisureOwaAlarmPanel,
        )
        from custom_components.securitas.const import CONF_ENABLE_PERIMETER_PANEL

        hass, entry = self._setup_kwargs(
            options={CONF_ENABLE_PERIMETER_PANEL: True},
            has_peri=False,  # transient: not yet detected
            has_annex=False,
        )
        added: list = []

        def add(entities, _update_before_add=False):
            added.extend(entities)

        with patch(
            "custom_components.securitas.alarm_control_panel.async_get_current_platform"
        ):
            await async_setup_entry(hass, entry, add)
        assert any(isinstance(p, PerimeterVerisureOwaAlarmPanel) for p in added)

    @pytest.mark.asyncio
    async def test_annex_panel_created_when_toggle_on_even_if_caps_not_yet_detected(
        self,
    ):
        """See test_perimeter_panel_created_when_toggle_on_even_if_caps_not_yet_detected
        for the rationale — saved toggle is the source of truth.
        """
        from custom_components.securitas.alarm_control_panel import (
            async_setup_entry,
            AnnexVerisureOwaAlarmPanel,
        )
        from custom_components.securitas.const import CONF_ENABLE_ANNEX_PANEL

        hass, entry = self._setup_kwargs(
            options={CONF_ENABLE_ANNEX_PANEL: True},
            has_peri=True,
            has_annex=False,
        )
        added: list = []

        def add(entities, _update_before_add=False):
            added.extend(entities)

        with patch(
            "custom_components.securitas.alarm_control_panel.async_get_current_platform"
        ):
            await async_setup_entry(hass, entry, add)
        assert any(isinstance(p, AnnexVerisureOwaAlarmPanel) for p in added)

    @pytest.mark.asyncio
    async def test_interior_panel_created_when_capability_present_no_siblings_enabled(
        self,
    ):
        """Interior panel must be creatable standalone when any sibling
        capability is present, without requiring the user to also enable
        the Perimeter or Annex toggle. The Interior toggle was made
        capability-gated (not toggle-gated) in the options flow; the
        entity-creation guard must match.
        """
        from custom_components.securitas.alarm_control_panel import (
            async_setup_entry,
            InteriorVerisureOwaAlarmPanel,
        )
        from custom_components.securitas.const import CONF_ENABLE_INTERIOR_PANEL

        hass, entry = self._setup_kwargs(
            options={CONF_ENABLE_INTERIOR_PANEL: True},
            has_peri=True,
            has_annex=False,
        )
        added: list = []

        def add(entities, _update_before_add=False):
            added.extend(entities)

        with patch(
            "custom_components.securitas.alarm_control_panel.async_get_current_platform"
        ):
            await async_setup_entry(hass, entry, add)
        assert any(isinstance(p, InteriorVerisureOwaAlarmPanel) for p in added)

    @pytest.mark.asyncio
    async def test_interior_panel_created_when_toggle_on_even_if_caps_not_yet_detected(
        self,
    ):
        """Same rationale as the Perimeter/Annex variants: a saved Interior
        toggle implies any sibling capability was supported at config time
        (the toggle is hidden in options otherwise). Don't let a transient
        capability-detection failure at startup permanently hide the entity.
        """
        from custom_components.securitas.alarm_control_panel import (
            async_setup_entry,
            InteriorVerisureOwaAlarmPanel,
        )
        from custom_components.securitas.const import CONF_ENABLE_INTERIOR_PANEL

        hass, entry = self._setup_kwargs(
            options={CONF_ENABLE_INTERIOR_PANEL: True},
            has_peri=False,  # transient: not yet detected
            has_annex=False,
        )
        added: list = []

        def add(entities, _update_before_add=False):
            added.extend(entities)

        with patch(
            "custom_components.securitas.alarm_control_panel.async_get_current_platform"
        ):
            await async_setup_entry(hass, entry, add)
        assert any(isinstance(p, InteriorVerisureOwaAlarmPanel) for p in added)

    @pytest.mark.asyncio
    async def test_all_three_subpanels_with_full_capabilities(self):
        from custom_components.securitas.alarm_control_panel import (
            async_setup_entry,
        )
        from custom_components.securitas.const import (
            CONF_ENABLE_INTERIOR_PANEL,
            CONF_ENABLE_PERIMETER_PANEL,
            CONF_ENABLE_ANNEX_PANEL,
        )

        hass, entry = self._setup_kwargs(
            options={
                CONF_ENABLE_INTERIOR_PANEL: True,
                CONF_ENABLE_PERIMETER_PANEL: True,
                CONF_ENABLE_ANNEX_PANEL: True,
            },
            has_peri=True,
            has_annex=True,
        )
        added: list = []

        def add(entities, _update_before_add=False):
            added.extend(entities)

        with patch(
            "custom_components.securitas.alarm_control_panel.async_get_current_platform"
        ):
            await async_setup_entry(hass, entry, add)
        types = {type(p).__name__ for p in added}
        assert types == {
            "CombinedVerisureOwaAlarmPanel",
            "InteriorVerisureOwaAlarmPanel",
            "PerimeterVerisureOwaAlarmPanel",
            "AnnexVerisureOwaAlarmPanel",
        }

    @pytest.mark.asyncio
    async def test_alarm_entities_lookup_only_combined(self):
        """Combined panel is the one registered in alarm_entities for force_arm services."""
        from custom_components.securitas.alarm_control_panel import (
            async_setup_entry,
            CombinedVerisureOwaAlarmPanel,
        )
        from custom_components.securitas.const import (
            DOMAIN,
            CONF_ENABLE_INTERIOR_PANEL,
            CONF_ENABLE_PERIMETER_PANEL,
            CONF_ENABLE_ANNEX_PANEL,
        )

        hass, entry = self._setup_kwargs(
            options={
                CONF_ENABLE_INTERIOR_PANEL: True,
                CONF_ENABLE_PERIMETER_PANEL: True,
                CONF_ENABLE_ANNEX_PANEL: True,
            },
            has_peri=True,
            has_annex=True,
        )
        added: list = []

        def add(entities, _update_before_add=False):
            added.extend(entities)

        with patch(
            "custom_components.securitas.alarm_control_panel.async_get_current_platform"
        ):
            await async_setup_entry(hass, entry, add)
        lookup = hass.data[DOMAIN]["alarm_entities"]
        assert set(lookup.keys()) == {"123456"}
        assert isinstance(lookup["123456"], CombinedVerisureOwaAlarmPanel)


# Phase F: Service / Event / Static-URL aliases
# ===========================================================================


async def test_verisure_owa_force_arm_alias_forwards_to_securitas(hass):
    """verisure_owa.force_arm proxies to securitas.force_arm with the same payload.

    Inverse of the v5.0.1 direction: the canonical service is now
    securitas.force_arm (manifest domain), and register_service_aliases
    exposes verisure_owa.force_arm as a symmetric alias that forwards
    to it. Both names are equal-weight in HA's eyes; the alias is for
    forward-compat with the deferred domain rename (see
    docs/FUTURE_MIGRATION_PLAN.md).
    """
    from custom_components.securitas import register_service_aliases

    canonical_called = []

    async def fake_handler(call):
        canonical_called.append(dict(call.data))

    hass.services.async_register("securitas", "force_arm", fake_handler)
    register_service_aliases(hass)
    await hass.services.async_call(
        "verisure_owa",
        "force_arm",
        {"entity_id": "alarm_control_panel.x"},
        blocking=True,
    )
    assert canonical_called == [{"entity_id": "alarm_control_panel.x"}]


async def test_arming_exception_fires_both_legacy_and_new_events(hass):
    """_fire_arming_exception_event fires both verisure_owa_arming_exception
    and securitas_arming_exception with the same payload (including _event_id)."""
    legacy_events = []
    new_events = []
    hass.bus.async_listen(
        "securitas_arming_exception", lambda e: legacy_events.append(e)
    )
    hass.bus.async_listen(
        "verisure_owa_arming_exception", lambda e: new_events.append(e)
    )

    alarm = make_alarm()
    alarm.hass = hass

    exc = ArmingExceptionError(
        "ref-1",
        "suid-1",
        [{"alias": "Window 1", "status": "0", "deviceType": "MG", "zone_id": "3"}],
    )
    alarm._fire_arming_exception_event(exc, mode="ARM_HOME")
    await hass.async_block_till_done()

    assert len(legacy_events) == 1
    assert len(new_events) == 1
    # Both events carry identical payloads (same dict object under the hood).
    assert legacy_events[0].data == new_events[0].data
    # _event_id is present in the payload.
    assert "_event_id" in legacy_events[0].data


class TestBuildPartialDisarmTarget:
    """Tests for the partial-disarm target-state builder."""

    def test_disarm_interior_only_keeps_perimeter_and_annex(self):
        from custom_components.securitas.alarm_control_panel import (
            build_partial_disarm_target,
        )
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )

        current = AlarmState(
            interior=InteriorMode.TOTAL,
            perimeter=PerimeterMode.ON,
            annex=AnnexMode.ON,
        )
        target = build_partial_disarm_target(current, ["interior"])
        assert target.interior == InteriorMode.OFF
        assert target.perimeter == PerimeterMode.ON
        assert target.annex == AnnexMode.ON

    def test_disarm_multiple_circuits(self):
        from custom_components.securitas.alarm_control_panel import (
            build_partial_disarm_target,
        )
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )

        current = AlarmState(
            interior=InteriorMode.TOTAL,
            perimeter=PerimeterMode.ON,
            annex=AnnexMode.ON,
        )
        target = build_partial_disarm_target(current, ["interior", "annex"])
        assert target.interior == InteriorMode.OFF
        assert target.perimeter == PerimeterMode.ON
        assert target.annex == AnnexMode.OFF

    def test_disarm_empty_list_returns_unchanged(self):
        from custom_components.securitas.alarm_control_panel import (
            build_partial_disarm_target,
        )
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )

        current = AlarmState(
            interior=InteriorMode.NIGHT,
            perimeter=PerimeterMode.ON,
            annex=AnnexMode.OFF,
        )
        target = build_partial_disarm_target(current, [])
        assert target == current

    def test_disarm_unknown_circuit_is_ignored(self):
        from custom_components.securitas.alarm_control_panel import (
            build_partial_disarm_target,
        )
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
        )

        current = AlarmState(
            interior=InteriorMode.TOTAL,
            perimeter=PerimeterMode.ON,
        )
        target = build_partial_disarm_target(current, ["bogus"])
        assert target == current


# ===========================================================================
# execute_partial_disarm
# ===========================================================================


class TestExecutePartialDisarm:
    """Tests for CombinedVerisureOwaAlarmPanel.execute_partial_disarm."""

    async def test_returns_true_on_success_and_calls_execute_transition(self):
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )

        panel = make_alarm()  # existing helper
        # Pretend alarm is currently TOTAL + perimeter ON + annex ON.
        panel.coordinator.alarm_state = AlarmState(
            interior=InteriorMode.TOTAL,
            perimeter=PerimeterMode.ON,
            annex=AnnexMode.ON,
        )
        panel._execute_transition = AsyncMock(
            return_value=MagicMock(protom_response="D")
        )

        ok = await panel.execute_partial_disarm(["interior"])

        assert ok is True
        panel._execute_transition.assert_awaited_once()
        # Inspect the target passed to _execute_transition.
        target = panel._execute_transition.await_args.args[0]
        assert target.interior == InteriorMode.OFF
        assert target.perimeter == PerimeterMode.ON
        assert target.annex == AnnexMode.ON

    async def test_returns_false_on_verisure_error(self):
        from custom_components.securitas.verisure_owa_api import VerisureOwaError
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )

        panel = make_alarm()
        panel.coordinator.alarm_state = AlarmState(
            interior=InteriorMode.TOTAL,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.OFF,
        )
        panel._execute_transition = AsyncMock(side_effect=VerisureOwaError("boom"))
        ok = await panel.execute_partial_disarm(["interior"])
        assert ok is False

    async def test_skips_when_no_circuits_specified(self):
        panel = make_alarm()
        panel._execute_transition = AsyncMock()
        ok = await panel.execute_partial_disarm([])
        assert ok is True
        panel._execute_transition.assert_not_awaited()

    async def test_combined_panel_shows_disarming_during_transition(self):
        """Combined panel should briefly enter DISARMING before the API call resolves
        so the UI reflects an in-flight auto-disarm instead of jumping silently
        from armed to disarmed when the next coordinator poll arrives.
        """
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )
        from homeassistant.components.alarm_control_panel.const import (
            AlarmControlPanelState,
        )

        panel = make_alarm()
        panel.coordinator.alarm_state = AlarmState(
            interior=InteriorMode.TOTAL,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.OFF,
        )

        observed: list[str | None] = []

        async def _slow_transition(*_args, **_kwargs):
            observed.append(panel._state)  # state during the transition
            return MagicMock(protom_response="D", message="ok", protom_response_date="")

        panel._execute_transition = AsyncMock(side_effect=_slow_transition)

        ok = await panel.execute_partial_disarm(["interior"])

        assert ok is True
        assert observed == [AlarmControlPanelState.DISARMING]

    async def test_partial_disarm_refreshes_coordinator(self):
        """After a successful partial disarm we trigger a coordinator refresh so
        any other entity (sub-panel, lock) sees the new state immediately
        rather than waiting for the next poll."""
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )

        panel = make_alarm()
        panel.coordinator.alarm_state = AlarmState(
            interior=InteriorMode.TOTAL,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.OFF,
        )
        panel._execute_transition = AsyncMock(
            return_value=MagicMock(
                protom_response="D", message="ok", protom_response_date=""
            )
        )

        await panel.execute_partial_disarm(["interior"])

        panel.coordinator.async_request_refresh.assert_awaited_once()

    async def test_partial_disarm_drives_affected_axis_subpanels(self):
        """When a sub-panel for the affected axis is registered in entry_data,
        execute_partial_disarm should drive its state through DISARMING and into
        the post-result state too — so users see the same animation as a direct
        sub-panel disarm."""
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )
        from custom_components.securitas.const import DOMAIN
        from homeassistant.components.alarm_control_panel.const import (
            AlarmControlPanelState,
        )

        panel = make_alarm()
        panel.coordinator.alarm_state = AlarmState(
            interior=InteriorMode.TOTAL,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.OFF,
        )

        # A lightweight stand-in for a real Interior sub-panel — verifies the
        # combined-panel orchestration without dragging in HA's entity loader.
        interior = MagicMock()
        interior._state = AlarmControlPanelState.ARMED_AWAY
        interior._last_state = AlarmControlPanelState.ARMED_AWAY
        interior._operation_in_progress = False
        interior._operation_epoch = 0

        def _force_state(state):
            interior._last_state = interior._state
            interior._state = state

        interior._force_state.side_effect = _force_state

        # Wire entry_data so the combined panel can find the sub-panel.
        entry_id = "entry-test"
        panel._client.config_entry = MagicMock(entry_id=entry_id)
        panel.hass.data = {
            DOMAIN: {
                entry_id: {
                    "axis_alarm_panels": {
                        panel._installation.number: {"interior": interior}
                    }
                }
            }
        }

        observed_interior: list[str | None] = []

        async def _slow_transition(*_args, **_kwargs):
            observed_interior.append(interior._state)
            return MagicMock(protom_response="D", message="ok", protom_response_date="")

        panel._execute_transition = AsyncMock(side_effect=_slow_transition)

        await panel.execute_partial_disarm(["interior"])

        assert observed_interior == [AlarmControlPanelState.DISARMING]
        # Sub-panel was also driven through the post-result update + state write.
        interior.update_status_alarm.assert_called_once()
        interior.async_write_ha_state.assert_called()


# ===========================================================================
# TestCombinedPanelEntityId
# ===========================================================================


class TestCombinedPanelEntityId:
    """The combined panel must suggest `<alias>` as its entity-id slug.

    Without this, HA would use the friendly-name 'Main - <alias>' to slugify
    the entity_id and end up with `alarm_control_panel.main_<alias>` (or, in
    the documented breakage from registry collision recovery,
    `<alias>_main_<alias>`). Forcing the slug to `<alias>` matches the v4
    entity_id and means dashboards keep working through a fresh v5 setup.
    """

    def test_combined_panel_suggested_object_id_is_alias(self):
        alarm = make_alarm()
        # Reach into the combined panel and check the slug source HA uses
        # when generating the entity_id for a fresh install.
        assert alarm.suggested_object_id == alarm.installation.alias

    def test_combined_panel_friendly_name_keeps_main_prefix(self):
        alarm = make_alarm()
        assert alarm.name.startswith("Main - ")


# ===========================================================================
# TestCombinedPanelEntityIdHealer
# ===========================================================================


class TestCombinedPanelEntityIdHealer:
    """Healer for upgrade-path-broken entity_ids.

    Earlier v5 builds slugified the friendly name `Main - <alias>` and ended up
    with `alarm_control_panel.<alias>_main_<alias>`. Restoring an old version
    and re-upgrading leaves a stale entity squatting on the canonical slot,
    pushing the new entity to `_2`. The healer reclaims the slot at setup.
    """

    async def test_renames_non_canonical_to_alias(self, hass):
        from homeassistant.helpers import entity_registry as er
        from homeassistant.util import slugify

        from custom_components.securitas.alarm_control_panel import (
            _heal_combined_panel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation = Installation(
            number="100001",
            alias="Corso Vittorio Emanuele 252 Roma",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        entry = MockConfigEntry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        ent_reg = er.async_get(hass)
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation.number}",
            suggested_object_id="corso_vittorio_emanuele_252_roma_main_corso_vittorio_emanuele_252_roma",
            config_entry=entry,
        )

        await _heal_combined_panel_entity_id(hass, installation)

        canonical = f"alarm_control_panel.{slugify(installation.alias)}"
        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation.number}",
            )
            == canonical
        )

    async def test_no_op_when_already_canonical(self, hass):
        from homeassistant.helpers import entity_registry as er
        from homeassistant.util import slugify

        from custom_components.securitas.alarm_control_panel import (
            _heal_combined_panel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation = Installation(
            number="100001",
            alias="Home",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        entry = MockConfigEntry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        ent_reg = er.async_get(hass)
        canonical = f"alarm_control_panel.{slugify(installation.alias)}"
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation.number}",
            suggested_object_id=slugify(installation.alias),
            config_entry=entry,
        )

        await _heal_combined_panel_entity_id(hass, installation)

        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation.number}",
            )
            == canonical
        )

    async def test_evicts_squatting_orphan_in_our_domain(self, hass):
        """When a stale verisure_owa entity holds the canonical slot and ours
        is on the broken doubled-alias slug, the healer removes the squatter
        and renames ours into the freed slot.
        """
        from homeassistant.helpers import entity_registry as er
        from homeassistant.util import slugify

        from custom_components.securitas.alarm_control_panel import (
            _heal_combined_panel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation = Installation(
            number="100001",
            alias="Home",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        entry = MockConfigEntry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        ent_reg = er.async_get(hass)
        alias_slug = slugify(installation.alias)
        canonical = f"alarm_control_panel.{alias_slug}"
        # Stale verisure_owa entity squatting on the canonical slot.
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            "v4_securitas_direct.legacy-stub",
            suggested_object_id=alias_slug,
            config_entry=entry,
        )
        # Ours, on the broken doubled-alias slug.
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation.number}",
            suggested_object_id=f"{alias_slug}_main_{alias_slug}",
            config_entry=entry,
        )

        await _heal_combined_panel_entity_id(hass, installation)

        # Squatter gone; ours reclaimed the canonical slot.
        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel", DOMAIN, "v4_securitas_direct.legacy-stub"
            )
            is None
        )
        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation.number}",
            )
            == canonical
        )

    async def test_skips_when_slot_held_by_other_domain(self, hass):
        """If a non-verisure entity owns the slot, leave ours alone."""
        from homeassistant.helpers import entity_registry as er
        from homeassistant.util import slugify

        from custom_components.securitas.alarm_control_panel import (
            _heal_combined_panel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation = Installation(
            number="100001",
            alias="Home",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        entry = MockConfigEntry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        ent_reg = er.async_get(hass)
        alias_slug = slugify(installation.alias)
        canonical = f"alarm_control_panel.{alias_slug}"
        broken = f"{alias_slug}_main_{alias_slug}"
        # An unrelated integration's entity occupies the slot.
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            "manual_alarm",
            "manual-alarm-unique-id",
            suggested_object_id=alias_slug,
            config_entry=entry,
        )
        # Ours, on the broken doubled-alias slug.
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation.number}",
            suggested_object_id=broken,
            config_entry=entry,
        )

        await _heal_combined_panel_entity_id(hass, installation)

        # Other-domain entity still there; ours stays on the broken slug.
        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel", "manual_alarm", "manual-alarm-unique-id"
            )
            == canonical
        )
        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation.number}",
            )
            == f"alarm_control_panel.{broken}"
        )

    async def test_does_not_evict_another_installation_with_same_alias(self, hass):
        """Two combined panels sharing an alias must not clobber each other.

        Installation A registers first and takes the canonical slot;
        installation B (same alias) collides → HA assigns ``<canonical>_2``.
        Both are legitimately live. Heal for B must NOT treat ``_2`` as a
        broken upgrade artifact and evict A — that would silently delete A's
        combined panel on every restart.
        """
        from homeassistant.helpers import entity_registry as er
        from homeassistant.util import slugify

        from custom_components.securitas.alarm_control_panel import (
            _heal_combined_panel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation_a = Installation(
            number="100001",
            alias="Home",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        installation_b = Installation(
            number="100002",
            alias="Home",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        entry = MockConfigEntry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        ent_reg = er.async_get(hass)
        alias_slug = slugify(installation_a.alias)
        canonical = f"alarm_control_panel.{alias_slug}"
        # A is correctly registered at the canonical slot.
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation_a.number}",
            suggested_object_id=alias_slug,
            config_entry=entry,
        )
        # B collided and landed on `<canonical>_2`.
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation_b.number}",
            suggested_object_id=alias_slug,
            config_entry=entry,
        )

        await _heal_combined_panel_entity_id(hass, installation_b)

        # A must still be at canonical.
        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation_a.number}",
            )
            == canonical
        )
        # B stays where it landed.
        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation_b.number}",
            )
            == f"{canonical}_2"
        )

    async def test_preserves_user_customized_entity_id(self, hass):
        """A user-customized entity_id (renamed via HA UI) must survive the
        healer. The healer is only allowed to relocate entities that sit on
        the known-broken ``<alias>_main_<alias>`` upgrade slug — any other
        non-canonical slug is treated as user customization and left alone.
        """
        from homeassistant.helpers import entity_registry as er

        from custom_components.securitas.alarm_control_panel import (
            _heal_combined_panel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation = Installation(
            number="100001",
            alias="Corso Vittorio Emanuele 252 Roma",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        entry = MockConfigEntry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        ent_reg = er.async_get(hass)
        custom_slug = "chiesa_nuova_alarm_corso_vittorio_emanuele_252_roma"
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation.number}",
            suggested_object_id=custom_slug,
            config_entry=entry,
        )

        await _heal_combined_panel_entity_id(hass, installation)

        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation.number}",
            )
            == f"alarm_control_panel.{custom_slug}"
        )

    @pytest.mark.skipif(
        not _DELETED_REGISTRY_ENTRY_HAS_ALIASES,
        reason=(
            "DeletedRegistryEntry.aliases field was added after our "
            "minimum-supported HA (2025.2); the test seeds a tombstone via "
            "the dataclass constructor so its kwargs have to match the live "
            "HA's attr fields."
        ),
    )
    async def test_preserves_user_customized_tombstone(self, hass):
        """A tombstone holding a user-customized entity_id must NOT be
        rewritten to canonical. Otherwise a delete/re-add cycle would silently
        discard the user's chosen slug on re-add.
        """
        from datetime import datetime, timezone

        from homeassistant.helpers import entity_registry as er

        from custom_components.securitas.alarm_control_panel import (
            _heal_combined_panel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation = Installation(
            number="100001",
            alias="Corso Vittorio Emanuele 252 Roma",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        ent_reg = er.async_get(hass)
        unique_id = f"v4_securitas_direct.{installation.number}"
        custom_entity_id = (
            "alarm_control_panel.chiesa_nuova_alarm_corso_vittorio_emanuele_252_roma"
        )

        now = datetime.now(timezone.utc)
        ent_reg.deleted_entities[("alarm_control_panel", DOMAIN, unique_id)] = (
            DeletedRegistryEntry(
                entity_id=custom_entity_id,
                unique_id=unique_id,
                platform=DOMAIN,
                aliases=set(),
                area_id=None,
                categories={},
                config_entry_id=None,
                config_subentry_id=None,
                created_at=now,
                device_class=None,
                disabled_by=None,
                hidden_by=None,
                icon=None,
                id="some-id",
                labels=set(),
                modified_at=now,
                name=None,
                options={},
                orphaned_timestamp=None,
            )
        )

        await _heal_combined_panel_entity_id(hass, installation)

        tombstone = ent_reg.deleted_entities.get(
            ("alarm_control_panel", DOMAIN, unique_id)
        )
        assert tombstone is not None
        assert tombstone.entity_id == custom_entity_id


# ===========================================================================
# TestSubPanelEntityIdHealer
# ===========================================================================


class TestSubPanelEntityIdHealer:
    """Healer for upgrade-path-broken sub-panel entity_ids.

    Mirrors the combined-panel healer for the Interior/Perimeter/Annex axis
    panels. A broken sub-panel sits at ``<alias>_<circuit>_<alias>`` (the
    doubled-alias collision form); the healer relocates it to the canonical
    ``<alias>_<circuit>`` slot, evicting any verisure_owa squatter holding
    that slot.
    """

    @pytest.mark.parametrize(
        "suffix",
        ["_interior", "_perimeter", "_annex"],
    )
    async def test_renames_non_canonical_to_alias_suffix(self, hass, suffix):
        from homeassistant.helpers import entity_registry as er
        from homeassistant.util import slugify

        from custom_components.securitas.alarm_control_panel import (
            _heal_subpanel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation = Installation(
            number="100001",
            alias="Corso Vittorio Emanuele 252 Roma",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        entry = MockConfigEntry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        ent_reg = er.async_get(hass)
        alias_slug = slugify(installation.alias)
        broken = f"{alias_slug}{suffix}_{alias_slug}"
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation.number}{suffix}",
            suggested_object_id=broken,
            config_entry=entry,
        )

        await _heal_subpanel_entity_id(hass, installation, suffix)

        canonical = f"alarm_control_panel.{alias_slug}{suffix}"
        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation.number}{suffix}",
            )
            == canonical
        )

    async def test_no_op_when_already_canonical(self, hass):
        from homeassistant.helpers import entity_registry as er
        from homeassistant.util import slugify

        from custom_components.securitas.alarm_control_panel import (
            _heal_subpanel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation = Installation(
            number="100001",
            alias="Home",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        entry = MockConfigEntry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        ent_reg = er.async_get(hass)
        canonical = f"alarm_control_panel.{slugify(installation.alias)}_interior"
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation.number}_interior",
            suggested_object_id=f"{slugify(installation.alias)}_interior",
            config_entry=entry,
        )

        await _heal_subpanel_entity_id(hass, installation, "_interior")

        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation.number}_interior",
            )
            == canonical
        )

    async def test_does_not_evict_another_installation_with_same_alias(self, hass):
        """Two installations sharing the alias must not clobber each other.

        Installation A (broken at <alias>_interior_<alias>) and installation B
        (correctly at <alias>_interior) collide on the canonical slot. Heal
        for A must leave B's entity alone and skip the rename rather than
        evicting a valid sub-panel from another installation.
        """
        from homeassistant.helpers import entity_registry as er
        from homeassistant.util import slugify

        from custom_components.securitas.alarm_control_panel import (
            _heal_subpanel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation_a = Installation(
            number="100001",
            alias="Home",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        installation_b_number = "100002"
        entry = MockConfigEntry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        ent_reg = er.async_get(hass)
        alias_slug = slugify(installation_a.alias)
        canonical = f"alarm_control_panel.{alias_slug}_interior"
        # Installation B is correctly registered at the canonical slot.
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation_b_number}_interior",
            suggested_object_id=f"{alias_slug}_interior",
            config_entry=entry,
        )
        # Installation A landed on the broken doubled-alias slot.
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation_a.number}_interior",
            suggested_object_id=f"{alias_slug}_interior_{alias_slug}",
            config_entry=entry,
        )

        await _heal_subpanel_entity_id(hass, installation_a, "_interior")

        # Installation B's entity must still exist at the canonical slot.
        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation_b_number}_interior",
            )
            == canonical
        )
        # Installation A's entity stays at the broken slot — manual intervention
        # is required to disambiguate.
        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation_a.number}_interior",
            )
            == f"alarm_control_panel.{alias_slug}_interior_{alias_slug}"
        )

    @pytest.mark.skipif(
        not _DELETED_REGISTRY_ENTRY_HAS_ALIASES,
        reason=(
            "DeletedRegistryEntry.aliases field was added after our "
            "minimum-supported HA (2025.2); the test seeds a tombstone via "
            "the dataclass constructor so its kwargs have to match the live "
            "HA's attr fields. Production code reads tombstones the registry "
            "produced naturally (attr.evolve preserves whatever fields exist), "
            "so it's the test scaffolding that's HA-version-specific, not the "
            "healer."
        ),
    )
    @pytest.mark.parametrize(
        "suffix",
        ["_interior", "_perimeter", "_annex"],
    )
    async def test_heals_doubled_alias_in_deleted_entities_tombstone(
        self, hass, suffix
    ):
        """When a user removes the installation (or upgrades from a build that
        slugified to the doubled-alias form) and re-adds it later, HA pops the
        tombstone in ``async_get_or_create`` and restores its ``entity_id`` —
        bypassing the entity's ``suggested_object_id``. So a freshly-readded
        sub-panel lands back on ``<alias>_<circuit>_<alias>`` even though the
        canonical slug would otherwise be picked.

        The healer must rewrite the tombstone's ``entity_id`` to the canonical
        slot so the next async_get_or_create restores onto the correct slug.
        """
        from datetime import datetime, timezone

        from homeassistant.helpers import entity_registry as er
        from homeassistant.util import slugify

        from custom_components.securitas.alarm_control_panel import (
            _heal_subpanel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation = Installation(
            number="100001",
            alias="Corso Vittorio Emanuele 252 Roma",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        ent_reg = er.async_get(hass)
        alias_slug = slugify(installation.alias)
        unique_id = f"v4_securitas_direct.{installation.number}{suffix}"
        broken = f"alarm_control_panel.{alias_slug}{suffix}_{alias_slug}"
        canonical = f"alarm_control_panel.{alias_slug}{suffix}"

        # Seed the tombstone HA would have left behind after the user
        # deleted the config entry from the UI.
        now = datetime.now(timezone.utc)
        ent_reg.deleted_entities[("alarm_control_panel", DOMAIN, unique_id)] = (
            DeletedRegistryEntry(
                entity_id=broken,
                unique_id=unique_id,
                platform=DOMAIN,
                aliases=set(),
                area_id=None,
                categories={},
                config_entry_id=None,
                config_subentry_id=None,
                created_at=now,
                device_class=None,
                disabled_by=None,
                hidden_by=None,
                icon=None,
                id="some-id",
                labels=set(),
                modified_at=now,
                name=None,
                options={},
                orphaned_timestamp=None,
            )
        )

        await _heal_subpanel_entity_id(hass, installation, suffix)

        # The tombstone's entity_id should now be canonical so that when
        # async_get_or_create pops it on re-add, the restored entity_id is
        # canonical too.
        tombstone = ent_reg.deleted_entities.get(
            ("alarm_control_panel", DOMAIN, unique_id)
        )
        assert tombstone is not None, "tombstone unexpectedly removed"
        assert tombstone.entity_id == canonical, (
            f"tombstone still has broken entity_id {tombstone.entity_id!r}"
        )

    @pytest.mark.parametrize(
        "suffix",
        ["_interior", "_perimeter", "_annex"],
    )
    async def test_preserves_user_customized_entity_id(self, hass, suffix):
        """A user-customized sub-panel entity_id must survive the healer.
        Only known-broken patterns (``<alias>_<circuit>_<alias>`` or
        ``<alias>_<circuit>_<N>`` collision suffix) may be relocated.
        """
        from homeassistant.helpers import entity_registry as er

        from custom_components.securitas.alarm_control_panel import (
            _heal_subpanel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation = Installation(
            number="100001",
            alias="Corso Vittorio Emanuele 252 Roma",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        entry = MockConfigEntry(domain=DOMAIN, data={})
        entry.add_to_hass(hass)
        ent_reg = er.async_get(hass)
        circuit = suffix.lstrip("_")
        custom_slug = f"chiesa_nuova_{circuit}"
        ent_reg.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            f"v4_securitas_direct.{installation.number}{suffix}",
            suggested_object_id=custom_slug,
            config_entry=entry,
        )

        await _heal_subpanel_entity_id(hass, installation, suffix)

        assert (
            ent_reg.async_get_entity_id(
                "alarm_control_panel",
                DOMAIN,
                f"v4_securitas_direct.{installation.number}{suffix}",
            )
            == f"alarm_control_panel.{custom_slug}"
        )

    @pytest.mark.skipif(
        not _DELETED_REGISTRY_ENTRY_HAS_ALIASES,
        reason=(
            "DeletedRegistryEntry.aliases field was added after our "
            "minimum-supported HA (2025.2); see the doubled-alias tombstone "
            "test above for the rationale."
        ),
    )
    @pytest.mark.parametrize(
        "suffix",
        ["_interior", "_perimeter", "_annex"],
    )
    async def test_preserves_user_customized_tombstone(self, hass, suffix):
        """A sub-panel tombstone holding a user-customized entity_id must NOT
        be rewritten to canonical.
        """
        from datetime import datetime, timezone

        from homeassistant.helpers import entity_registry as er

        from custom_components.securitas.alarm_control_panel import (
            _heal_subpanel_entity_id,
        )
        from custom_components.securitas.const import DOMAIN
        from custom_components.securitas.verisure_owa_api.models import (
            Installation,
        )

        installation = Installation(
            number="100001",
            alias="Corso Vittorio Emanuele 252 Roma",
            panel="SDVFAST",
            type="PLUS",
            address="",
            city="",
        )
        ent_reg = er.async_get(hass)
        unique_id = f"v4_securitas_direct.{installation.number}{suffix}"
        circuit = suffix.lstrip("_")
        custom_entity_id = f"alarm_control_panel.chiesa_nuova_{circuit}"

        now = datetime.now(timezone.utc)
        ent_reg.deleted_entities[("alarm_control_panel", DOMAIN, unique_id)] = (
            DeletedRegistryEntry(
                entity_id=custom_entity_id,
                unique_id=unique_id,
                platform=DOMAIN,
                aliases=set(),
                area_id=None,
                categories={},
                config_entry_id=None,
                config_subentry_id=None,
                created_at=now,
                device_class=None,
                disabled_by=None,
                hidden_by=None,
                icon=None,
                id=f"some-id-{suffix}",
                labels=set(),
                modified_at=now,
                name=None,
                options={},
                orphaned_timestamp=None,
            )
        )

        await _heal_subpanel_entity_id(hass, installation, suffix)

        tombstone = ent_reg.deleted_entities.get(
            ("alarm_control_panel", DOMAIN, unique_id)
        )
        assert tombstone is not None
        assert tombstone.entity_id == custom_entity_id


# ===========================================================================
# TestCombinedPanelRegistration
# ===========================================================================


class TestCombinedPanelRegistration:
    """Tests that async_setup_entry stores combined panels in entry_data keyed by installation number."""

    def _make_client(self):
        from unittest.mock import MagicMock
        from custom_components.securitas.verisure_owa_api.const import STD_DEFAULTS

        client = MagicMock()
        client.config = {
            "map_home": STD_DEFAULTS["map_home"],
            "map_away": STD_DEFAULTS["map_away"],
            "map_night": STD_DEFAULTS["map_night"],
            "scan_interval": 120,
        }
        return client

    def _make_device(self, number, alias):
        from custom_components.securitas.hub import VerisureDevice
        from custom_components.securitas.verisure_owa_api.models import Installation

        installation = Installation(
            number=number,
            alias=alias,
            panel="SDVFAST",
            type="PLUS",
            address="1 Test St",
            city="Barcelona",
        )
        return VerisureDevice(installation)

    async def _run_setup(self, hass, entry, async_add_entities):
        from unittest.mock import MagicMock, patch
        from custom_components.securitas.alarm_control_panel import (
            CombinedVerisureOwaAlarmPanel,
            async_setup_entry,
        )

        with (
            patch.object(
                CombinedVerisureOwaAlarmPanel,
                "async_schedule_update_ha_state",
                MagicMock(),
            ),
            patch.object(
                CombinedVerisureOwaAlarmPanel,
                "async_write_ha_state",
                MagicMock(),
            ),
            patch(
                "custom_components.securitas.alarm_control_panel"
                ".async_get_current_platform",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.securitas.alarm_control_panel"
                "._heal_combined_panel_entity_id",
                AsyncMock(),
            ),
        ):
            await async_setup_entry(hass, entry, async_add_entities)

    async def test_combined_panels_keyed_by_installation_number_multi(self):
        """With two installations, combined_alarm_panels must be a dict with one entry per installation."""
        from unittest.mock import MagicMock
        from custom_components.securitas.alarm_control_panel import (
            CombinedVerisureOwaAlarmPanel,
        )
        from custom_components.securitas import DOMAIN
        from custom_components.securitas.coordinators import AlarmCoordinator

        device_a = self._make_device("111111", "Main Home")
        device_b = self._make_device("222222", "Annex")

        coordinator = MagicMock(spec=AlarmCoordinator)
        coordinator.has_peri = False
        coordinator.has_annex = False

        entry_data = {
            "hub": self._make_client(),
            "alarm_coordinator": coordinator,
            "devices": [device_a, device_b],
        }

        hass = MagicMock()
        hass.data = {DOMAIN: {"test-entry-id": entry_data}}

        entry = MagicMock()
        entry.entry_id = "test-entry-id"
        entry.options = {}

        async_add_entities = MagicMock()

        await self._run_setup(hass, entry, async_add_entities)

        assert "combined_alarm_panels" in entry_data, (
            "entry_data missing 'combined_alarm_panels' key after async_setup_entry"
        )
        panels = entry_data["combined_alarm_panels"]
        assert isinstance(panels, dict), "combined_alarm_panels must be a dict"
        assert set(panels.keys()) == {"111111", "222222"}, (
            f"Expected keys {{'111111', '222222'}}, got {set(panels.keys())}"
        )
        for inst_num, panel in panels.items():
            assert isinstance(panel, CombinedVerisureOwaAlarmPanel), (
                f"Panel for {inst_num} is not a CombinedVerisureOwaAlarmPanel"
            )
            assert panel.installation.number == inst_num, (
                f"Panel installation number {panel.installation.number!r} != key {inst_num!r}"
            )

    async def test_combined_panel_per_installation_with_single_install(self):
        """With one installation, combined_alarm_panels must be a dict with exactly one entry."""
        from unittest.mock import MagicMock
        from custom_components.securitas.alarm_control_panel import (
            CombinedVerisureOwaAlarmPanel,
        )
        from custom_components.securitas import DOMAIN
        from custom_components.securitas.coordinators import AlarmCoordinator

        device = self._make_device("654321", "Test Home")

        coordinator = MagicMock(spec=AlarmCoordinator)
        coordinator.has_peri = False
        coordinator.has_annex = False

        entry_data = {
            "hub": self._make_client(),
            "alarm_coordinator": coordinator,
            "devices": [device],
        }

        hass = MagicMock()
        hass.data = {DOMAIN: {"test-entry-id": entry_data}}

        entry = MagicMock()
        entry.entry_id = "test-entry-id"
        entry.options = {}

        async_add_entities = MagicMock()

        await self._run_setup(hass, entry, async_add_entities)

        assert "combined_alarm_panels" in entry_data, (
            "entry_data missing 'combined_alarm_panels' key after async_setup_entry"
        )
        panels = entry_data["combined_alarm_panels"]
        assert isinstance(panels, dict), "combined_alarm_panels must be a dict"
        assert len(panels) == 1, f"Expected exactly 1 entry, got {len(panels)}"
        assert "654321" in panels, f"Expected key '654321', got {set(panels.keys())}"
        panel = panels["654321"]
        assert isinstance(panel, CombinedVerisureOwaAlarmPanel)
        assert panel.installation.number == "654321"


class TestAsyncManualRefresh:
    """Tests for BaseVerisureOwaAlarmPanel.async_manual_refresh.

    This is the canonical implementation of "refresh this alarm panel"
    that backs both the deprecated VerisureRefreshButton and the new
    `verisure_owa.refresh_alarm` entity service.  The button delegates
    here; the card calls the service which calls here.
    """

    async def test_calls_refresh_alarm_status_on_client(self):
        from custom_components.securitas.verisure_owa_api.models import OperationStatus

        alarm = make_alarm()
        status = OperationStatus(operation_status="OK", protom_response="T", status="")
        alarm._client.refresh_alarm_status = AsyncMock(return_value=status)

        await alarm.async_manual_refresh()

        alarm._client.refresh_alarm_status.assert_awaited_once_with(alarm._installation)

    async def test_updates_protom_response_on_success(self):
        from custom_components.securitas.verisure_owa_api.models import OperationStatus

        alarm = make_alarm()
        status = OperationStatus(operation_status="OK", protom_response="T", status="")
        alarm._client.refresh_alarm_status = AsyncMock(return_value=status)

        await alarm.async_manual_refresh()

        assert alarm._client.client.protom_response == "T"

    async def test_clears_refresh_failed_on_success(self):
        from custom_components.securitas.verisure_owa_api.models import OperationStatus

        alarm = make_alarm()
        # Pre-populate the failed flag so we can see it cleared.
        alarm._attr_extra_state_attributes["refresh_failed"] = True
        status = OperationStatus(operation_status="OK", protom_response="T", status="")
        alarm._client.refresh_alarm_status = AsyncMock(return_value=status)

        await alarm.async_manual_refresh()

        assert "refresh_failed" not in alarm._attr_extra_state_attributes

    async def test_sets_refresh_failed_on_timeout(self):
        from custom_components.securitas.verisure_owa_api.exceptions import (
            OperationTimeoutError,
        )

        alarm = make_alarm()
        alarm._client.refresh_alarm_status = AsyncMock(
            side_effect=OperationTimeoutError("timed out")
        )

        await alarm.async_manual_refresh()

        assert alarm._attr_extra_state_attributes.get("refresh_failed") is True

    async def test_sets_waf_blocked_on_403(self):
        alarm = make_alarm()
        # _async_notify routes through hass.services.async_call which must
        # be awaitable in our test context.
        alarm.hass.services.async_call = AsyncMock()
        err = VerisureOwaError("blocked", http_status=403)
        alarm._client.refresh_alarm_status = AsyncMock(side_effect=err)

        await alarm.async_manual_refresh()

        assert alarm._attr_extra_state_attributes.get("waf_blocked") is True
