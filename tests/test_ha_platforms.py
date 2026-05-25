"""Tests for sensor and lock platform entities."""

import contextlib
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.securitas.verisure_owa_api.models import (
    ActivityEvent,
    AirQuality,
    Attribute,
    Installation,
    LockAutolock,
    LockFeatures,
    Sentinel,
    Service,
    SmartLock,
    SmartLockMode,
    SmartLockModeStatus,
)
from custom_components.securitas.verisure_owa_api.exceptions import (
    VerisureOwaError,
)
from custom_components.securitas.sensor import (
    ActivityLogSensor,
    SentinelAirQuality,
    SentinelAirQualityStatus,
    SentinelHumidity,
    SentinelTemperature,
)
from custom_components.securitas.coordinators import (
    ActivityData,
    LockData,
    SentinelData,
)
from custom_components.securitas.api_queue import ApiQueue
from custom_components.securitas.lock import VerisureLock


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def make_installation():
    """Create a test Installation."""
    return Installation(
        number="123456", alias="Home", panel="SDVFAST", type="PLUS", address="123 St"
    )


def make_service():
    """Create a mock Service for sensors."""
    return Service(
        id=1,
        id_service=100,
        active=True,
        visible=True,
        bde=False,
        is_premium=False,
        cod_oper=False,
        total_device=0,
        request="CONFORT",
        multiple_req=False,
        num_devices_mr=0,
        secret_word=False,
        min_wrapper_version=None,
        description="Sentinel",
        attributes=[Attribute(name="zone", value="1", active=True)],
        listdiy=[],
        listprompt=[],
        installation=make_installation(),
    )


def make_sentinel(temp=22, humidity=45):
    """Create a test Sentinel data object."""
    return Sentinel(
        alias="Living", air_quality="2", humidity=humidity, temperature=temp
    )


def make_client():
    """Create a mock VerisureHub client."""
    client = MagicMock()
    client.session = AsyncMock()
    client.config = {"scan_interval": 120}
    client.lang = "es"
    return client


def _make_lock_coordinator(data: LockData | None = None):
    """Create a mock LockCoordinator for lock tests."""
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def make_lock(
    device_id: str = "01",
    initial_status: str = "2",
    lock_config: SmartLock | None = None,
    poll_status: str | None = None,
):
    """Create a VerisureLock with mocked dependencies.

    Args:
        poll_status: If set, ``get_lock_modes`` returns a mode with this
            lockStatus for the device.  If *None*, ``get_lock_modes``
            returns an empty list (so ``_get_lock_state`` returns UNKNOWN
            and the optimistic fallback is used).
    """
    installation = make_installation()
    client = MagicMock()
    client.config = {"scan_interval": 120}
    client.session = AsyncMock()
    client.change_lock_mode = AsyncMock()
    if poll_status is not None:
        client.get_lock_modes = AsyncMock(
            return_value=[SmartLockMode(lock_status=poll_status, device_id=device_id)]
        )
    else:
        client.get_lock_modes = AsyncMock(return_value=[])
    hass = MagicMock()
    hass.async_create_task = MagicMock()
    hass.services = MagicMock()

    coordinator = _make_lock_coordinator()

    lock_entity = VerisureLock(
        coordinator=coordinator,
        installation=installation,
        client=client,
        device_id=device_id,
        initial_status=initial_status,
        lock_config=lock_config,
    )
    lock_entity.hass = hass
    lock_entity.entity_id = f"lock.securitas_{installation.number}_{device_id}"
    # Mock HA state-writing methods (no platform registered in unit tests)
    lock_entity.async_write_ha_state = MagicMock()
    lock_entity.async_schedule_update_ha_state = MagicMock()
    # Zero the inter-poll delay so the verification poll runs instantly in tests.
    lock_entity._verify_delay = 0
    return lock_entity


async def _drain_lock_tasks(lock):
    """Run all coroutines scheduled via the mocked ``hass.async_create_task``.

    The mocked hass collects scheduled coroutines as MagicMock call args;
    we await each one in turn so test assertions can observe the side effects.
    """
    calls = lock.hass.async_create_task.call_args_list
    for call in calls:
        coro = call.args[0]
        await coro
    lock.hass.async_create_task.reset_mock()


# ===========================================================================
# Sentinel sensor helper — mock coordinator
# ===========================================================================


def _make_sentinel_coordinator(data=None):
    """Create a mock SentinelCoordinator for sensor tests."""
    coordinator = MagicMock()
    coordinator.data = data
    return coordinator


# ===========================================================================
# SentinelTemperature tests
# ===========================================================================


class TestSentinelTemperature:
    """Tests for SentinelTemperature sensor entity."""

    def test_native_value_returns_none_when_no_data(self):
        coordinator = _make_sentinel_coordinator(data=None)
        sensor = SentinelTemperature(coordinator, make_installation(), 1)
        assert sensor.native_value is None

    def test_native_value_returns_none_when_sentinel_is_none(self):
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(sentinel=None, air_quality=None)
        )
        sensor = SentinelTemperature(coordinator, make_installation(), 1)
        assert sensor.native_value is None

    def test_native_value_returns_temperature(self):
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(sentinel=make_sentinel(temp=30), air_quality=None)
        )
        sensor = SentinelTemperature(coordinator, make_installation(), 1)
        assert sensor.native_value == 30

    def test_init_sets_device_class_to_temperature(self):
        from homeassistant.components.sensor import SensorDeviceClass

        coordinator = _make_sentinel_coordinator()
        sensor = SentinelTemperature(coordinator, make_installation(), 1)
        assert sensor._attr_device_class == SensorDeviceClass.TEMPERATURE

    def test_init_sets_unit_to_celsius(self):
        from homeassistant.const import UnitOfTemperature

        coordinator = _make_sentinel_coordinator()
        sensor = SentinelTemperature(coordinator, make_installation(), 1)
        assert sensor._attr_native_unit_of_measurement == UnitOfTemperature.CELSIUS

    def test_unique_id_contains_installation_number_and_service_id(self):
        service = make_service()
        installation = make_installation()
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelTemperature(coordinator, installation, service.id)
        assert installation.number in sensor._attr_unique_id  # type: ignore[operator]
        assert str(service.id) in sensor._attr_unique_id  # type: ignore[operator]
        assert "temperature" in sensor._attr_unique_id  # type: ignore[operator]

    def test_name_is_short_form_without_alias(self):
        """Modern pattern: entity name carries the suffix only; alias lives on the device."""
        installation = make_installation()
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelTemperature(coordinator, installation, 1)
        assert sensor._attr_name == "Temperature"
        assert installation.alias not in (sensor._attr_name or "")

    def test_has_entity_name_is_true(self):
        """has_entity_name = True so HA composes display as <device_name> <entity_name>."""
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelTemperature(coordinator, make_installation(), 1)
        assert sensor._attr_has_entity_name is True

    def test_unique_id_uses_v5_schema(self):
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelTemperature(coordinator, make_installation(), 5)
        assert sensor._attr_unique_id == "v4_securitas_direct.123456_temperature_5"


# ===========================================================================
# SentinelHumidity tests
# ===========================================================================


class TestSentinelHumidity:
    """Tests for SentinelHumidity sensor entity."""

    def test_native_value_returns_none_when_no_data(self):
        coordinator = _make_sentinel_coordinator(data=None)
        sensor = SentinelHumidity(coordinator, make_installation(), 1)
        assert sensor.native_value is None

    def test_native_value_returns_none_when_sentinel_is_none(self):
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(sentinel=None, air_quality=None)
        )
        sensor = SentinelHumidity(coordinator, make_installation(), 1)
        assert sensor.native_value is None

    def test_native_value_returns_humidity(self):
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(sentinel=make_sentinel(humidity=60), air_quality=None)
        )
        sensor = SentinelHumidity(coordinator, make_installation(), 1)
        assert sensor.native_value == 60

    def test_init_sets_device_class_to_humidity(self):
        from homeassistant.components.sensor import SensorDeviceClass

        coordinator = _make_sentinel_coordinator()
        sensor = SentinelHumidity(coordinator, make_installation(), 1)
        assert sensor._attr_device_class == SensorDeviceClass.HUMIDITY

    def test_init_sets_unit_to_percentage(self):
        from homeassistant.const import PERCENTAGE

        coordinator = _make_sentinel_coordinator()
        sensor = SentinelHumidity(coordinator, make_installation(), 1)
        assert sensor._attr_native_unit_of_measurement == PERCENTAGE

    def test_unique_id_contains_installation_number_and_service_id(self):
        service = make_service()
        installation = make_installation()
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelHumidity(coordinator, installation, service.id)
        assert installation.number in sensor._attr_unique_id  # type: ignore[operator]
        assert str(service.id) in sensor._attr_unique_id  # type: ignore[operator]
        assert "humidity" in sensor._attr_unique_id  # type: ignore[operator]

    def test_name_is_short_form_without_alias(self):
        installation = make_installation()
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelHumidity(coordinator, installation, 1)
        assert sensor._attr_name == "Humidity"
        assert installation.alias not in (sensor._attr_name or "")

    def test_has_entity_name_is_true(self):
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelHumidity(coordinator, make_installation(), 1)
        assert sensor._attr_has_entity_name is True

    def test_unique_id_uses_v5_schema(self):
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelHumidity(coordinator, make_installation(), 5)
        assert sensor._attr_unique_id == "v4_securitas_direct.123456_humidity_5"


# ===========================================================================
# SentinelAirQuality + SentinelAirQualityStatus tests
# ===========================================================================


class TestSentinelAirQuality:
    """Tests for SentinelAirQuality numeric sensor."""

    def test_native_value_returns_none_when_no_data(self):
        coordinator = _make_sentinel_coordinator(data=None)
        sensor = SentinelAirQuality(coordinator, make_installation(), 1)
        assert sensor.native_value is None

    def test_native_value_returns_none_when_air_quality_is_none(self):
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(sentinel=None, air_quality=None)
        )
        sensor = SentinelAirQuality(coordinator, make_installation(), 1)
        assert sensor.native_value is None

    def test_native_value_returns_air_quality_value(self):
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(
                sentinel=None,
                air_quality=AirQuality(value=122, status_current=1),
            )
        )
        sensor = SentinelAirQuality(coordinator, make_installation(), 1)
        assert sensor.native_value == 122

    def test_value_is_none_when_hours_null(self):
        """When hours is null, value should be None."""
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(
                sentinel=None,
                air_quality=AirQuality(value=None, status_current=1),
            )
        )
        sensor = SentinelAirQuality(coordinator, make_installation(), 1)

        assert sensor.native_value is None

    def test_unique_id_contains_airquality(self):
        service = make_service()
        installation = make_installation()
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelAirQuality(coordinator, installation, service.id)
        assert installation.number in sensor._attr_unique_id  # type: ignore[operator]
        assert "airquality" in sensor._attr_unique_id  # type: ignore[operator]

    def test_name_is_short_form_without_alias(self):
        installation = make_installation()
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelAirQuality(coordinator, installation, 1)
        assert sensor._attr_name == "Air Quality"
        assert installation.alias not in (sensor._attr_name or "")

    def test_has_entity_name_is_true(self):
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelAirQuality(coordinator, make_installation(), 1)
        assert sensor._attr_has_entity_name is True

    def test_unique_id_uses_v5_schema(self):
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelAirQuality(coordinator, make_installation(), 5)
        assert sensor._attr_unique_id == "v4_securitas_direct.123456_airquality_5"


class TestSentinelAirQualityStatus:
    """Tests for SentinelAirQualityStatus categorical sensor."""

    def test_native_value_returns_none_when_no_data(self):
        coordinator = _make_sentinel_coordinator(data=None)
        sensor = SentinelAirQualityStatus(coordinator, make_installation(), 1)
        assert sensor.native_value is None

    def test_native_value_returns_none_when_air_quality_is_none(self):
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(sentinel=None, air_quality=None)
        )
        sensor = SentinelAirQualityStatus(coordinator, make_installation(), 1)
        assert sensor.native_value is None

    def test_status_good(self):
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(
                sentinel=None,
                air_quality=AirQuality(value=122, status_current=1),
            )
        )
        sensor = SentinelAirQualityStatus(coordinator, make_installation(), 1)
        assert sensor.native_value == "Good"

    def test_status_fair(self):
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(
                sentinel=None,
                air_quality=AirQuality(value=200, status_current=2),
            )
        )
        sensor = SentinelAirQualityStatus(coordinator, make_installation(), 1)
        assert sensor.native_value == "Fair"

    def test_status_poor(self):
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(
                sentinel=None,
                air_quality=AirQuality(value=300, status_current=3),
            )
        )
        sensor = SentinelAirQualityStatus(coordinator, make_installation(), 1)
        assert sensor.native_value == "Poor"

    def test_status_works_when_value_is_none(self):
        """Issue #428: status should show 'Good' even when hours is null."""
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(
                sentinel=None,
                air_quality=AirQuality(value=None, status_current=1),
            )
        )
        sensor = SentinelAirQualityStatus(coordinator, make_installation(), 1)

        assert sensor.native_value == "Good"

    def test_unknown_status_code(self, caplog):
        """Unknown codes fall back to the raw code string and log a warning."""
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(
                sentinel=None,
                air_quality=AirQuality(value=200, status_current=99),
            )
        )
        sensor = SentinelAirQualityStatus(coordinator, make_installation(), 1)
        assert sensor.native_value == "99"
        assert "Unknown air quality status code '99'" in caplog.text

    def test_unique_id_contains_status(self):
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelAirQualityStatus(coordinator, make_installation(), 1)
        assert "airquality_status" in sensor._attr_unique_id  # type: ignore[operator]

    def test_both_entities_share_coordinator_data(self):
        """Both numeric and status entities read consistent data from coordinator."""
        coordinator = _make_sentinel_coordinator(
            data=SentinelData(
                sentinel=None,
                air_quality=AirQuality(value=92, status_current=1),
            )
        )
        numeric = SentinelAirQuality(coordinator, make_installation(), 1)
        status = SentinelAirQualityStatus(coordinator, make_installation(), 1)

        assert numeric.native_value == 92
        assert status.native_value == "Good"

    def test_name_is_short_form_without_alias(self):
        installation = make_installation()
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelAirQualityStatus(coordinator, installation, 1)
        assert sensor._attr_name == "Air Quality Status"
        assert installation.alias not in (sensor._attr_name or "")

    def test_has_entity_name_is_true(self):
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelAirQualityStatus(coordinator, make_installation(), 1)
        assert sensor._attr_has_entity_name is True

    def test_unique_id_uses_v5_schema(self):
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelAirQualityStatus(coordinator, make_installation(), 5)
        assert (
            sensor._attr_unique_id == "v4_securitas_direct.123456_airquality_status_5"
        )


# ===========================================================================


def _make_activity_event(
    id_signal: str, alias: str = "Armed", **overrides
) -> ActivityEvent:
    base = {
        "alias": alias,
        "type": 701,
        "signal_type": 701,
        "id_signal": id_signal,
        "time": "2026-05-05 15:00:00",
        "img": 0,
        "source": "Web",
        "device": "VV",
        "device_name": "Ingresso",
        "verisure_user": "Test User",
    }
    base.update(overrides)
    return ActivityEvent.model_validate(base)


def _make_activity_coordinator(data: ActivityData | None = None):
    coordinator = MagicMock()
    coordinator.data = data
    return coordinator


class TestActivityLogSensor:
    """Tests for ActivityLogSensor — surfaces the alarm-panel timeline as a sensor."""

    def test_state_is_none_when_coordinator_has_no_data(self):
        coordinator = _make_activity_coordinator(data=None)
        sensor = ActivityLogSensor(coordinator, make_installation())
        assert sensor.native_value is None

    def test_background_polling_attribute_reflects_update_interval(self):
        """The card reads this flag to decide whether to drive its own refreshes."""
        off = _make_activity_coordinator(data=ActivityData(events=[], new_events=[]))
        off.update_interval = None
        assert (
            ActivityLogSensor(off, make_installation()).extra_state_attributes[
                "background_polling"
            ]
            is False
        )

        on = _make_activity_coordinator(data=ActivityData(events=[], new_events=[]))
        on.update_interval = timedelta(seconds=60)
        assert (
            ActivityLogSensor(on, make_installation()).extra_state_attributes[
                "background_polling"
            ]
            is True
        )

    def test_state_is_none_when_no_events(self):
        coordinator = _make_activity_coordinator(
            data=ActivityData(events=[], new_events=[])
        )
        sensor = ActivityLogSensor(coordinator, make_installation())
        assert sensor.native_value is None

    def test_state_format_with_user_and_time(self):
        """Newest event determines state — alias + user + HH:MM."""
        latest = _make_activity_event(
            "999",
            alias="Armed",
            verisure_user="Luci",
            time="2026-05-05 15:00:00",
        )
        older = _make_activity_event("998", alias="Disarmed")
        coordinator = _make_activity_coordinator(
            data=ActivityData(events=[latest, older], new_events=[])
        )
        sensor = ActivityLogSensor(coordinator, make_installation())
        assert sensor.native_value == "Armed by Luci at 15:00"

    def test_state_format_with_device_name_when_no_user(self):
        """Sensor-triggered events (no user) include the device name instead."""
        latest = _make_activity_event(
            "999",
            alias="Image request",
            verisure_user=None,
            device_name="Cucina",
            time="2026-04-09 14:20:42",
        )
        coordinator = _make_activity_coordinator(
            data=ActivityData(events=[latest], new_events=[])
        )
        sensor = ActivityLogSensor(coordinator, make_installation())
        assert sensor.native_value == "Image request (Cucina) at 14:20"

    def test_state_format_no_user_no_device_name(self):
        """Bare events show just alias + time."""
        latest = _make_activity_event(
            "999",
            alias="Alarm addressed and solved",
            verisure_user=None,
            device_name=None,
            time="2026-05-01 11:00:43",
        )
        coordinator = _make_activity_coordinator(
            data=ActivityData(events=[latest], new_events=[])
        )
        sensor = ActivityLogSensor(coordinator, make_installation())
        assert sensor.native_value == "Alarm addressed and solved at 11:00"

    def test_state_format_user_takes_precedence_over_device_name(self):
        """When both user and device_name are present, user wins."""
        latest = _make_activity_event(
            "999",
            alias="Armed",
            verisure_user="Luci",
            device_name="Ingresso",
            time="2026-05-05 15:00:00",
        )
        coordinator = _make_activity_coordinator(
            data=ActivityData(events=[latest], new_events=[])
        )
        sensor = ActivityLogSensor(coordinator, make_installation())
        assert sensor.native_value == "Armed by Luci at 15:00"

    def test_state_omits_time_when_malformed(self):
        """Falls back to alias-only if the time field is unparseable."""
        latest = _make_activity_event(
            "999", alias="Armed", verisure_user=None, device_name=None, time=""
        )
        coordinator = _make_activity_coordinator(
            data=ActivityData(events=[latest], new_events=[])
        )
        sensor = ActivityLogSensor(coordinator, make_installation())
        assert sensor.native_value == "Armed"

    def test_attributes_empty_when_no_data(self):
        coordinator = _make_activity_coordinator(data=None)
        sensor = ActivityLogSensor(coordinator, make_installation())
        assert sensor.extra_state_attributes == {"events": []}

    def test_attributes_contain_latest_event_fields(self):
        latest = _make_activity_event(
            "16215212397",
            alias="Armed",
            type=701,
            time="2026-05-05 15:00:00",
            device="VV",
            device_name="Ingresso",
        )
        coordinator = _make_activity_coordinator(
            data=ActivityData(events=[latest], new_events=[])
        )
        sensor = ActivityLogSensor(coordinator, make_installation())
        attrs = sensor.extra_state_attributes
        assert attrs["latest"]["id_signal"] == "16215212397"
        assert attrs["latest"]["type"] == 701
        assert attrs["latest"]["alias"] == "Armed"
        assert attrs["latest"]["time"] == "2026-05-05 15:00:00"
        assert attrs["latest"]["device"] == "VV"
        assert attrs["latest"]["device_name"] == "Ingresso"

    def test_attributes_contain_event_log_list(self):
        events = [_make_activity_event(str(i)) for i in range(5, 0, -1)]
        coordinator = _make_activity_coordinator(
            data=ActivityData(events=events, new_events=[])
        )
        sensor = ActivityLogSensor(coordinator, make_installation())
        attrs = sensor.extra_state_attributes
        assert "events" in attrs
        assert len(attrs["events"]) == 5
        assert [e["id_signal"] for e in attrs["events"]] == ["5", "4", "3", "2", "1"]

    def test_attribute_events_carry_category(self):
        """Each row in the `events` attribute carries its category."""
        latest = _make_activity_event("999", type=13, alias="Alarm")
        coordinator = _make_activity_coordinator(
            data=ActivityData(events=[latest], new_events=[])
        )
        sensor = ActivityLogSensor(coordinator, make_installation())
        attrs = sensor.extra_state_attributes
        assert attrs["events"][0]["category"] == "alarm"
        assert attrs["latest"]["category"] == "alarm"

    def test_attribute_log_capped_at_recent_window(self):
        """Long histories are capped — we don't dump 1000 entries into HA state."""
        events = [_make_activity_event(str(i)) for i in range(100, 0, -1)]
        coordinator = _make_activity_coordinator(
            data=ActivityData(events=events, new_events=[])
        )
        sensor = ActivityLogSensor(coordinator, make_installation())
        attrs = sensor.extra_state_attributes
        # Cap is 30 — matches the default coordinator page size
        assert len(attrs["events"]) == 30
        # The cap keeps the most-recent (top of list)
        assert attrs["events"][0]["id_signal"] == "100"

    def test_unique_id_contains_installation_number(self):
        installation = make_installation()
        coordinator = _make_activity_coordinator()
        sensor = ActivityLogSensor(coordinator, installation)
        assert installation.number in sensor._attr_unique_id  # type: ignore[operator]
        assert "activity" in sensor._attr_unique_id  # type: ignore[operator]

    def test_name_contains_installation_alias(self):
        installation = make_installation()
        coordinator = _make_activity_coordinator()
        sensor = ActivityLogSensor(coordinator, installation)
        assert installation.alias in sensor._attr_name  # type: ignore[operator]


# ===========================================================================
# VerisureLock tests
# ===========================================================================


class TestVerisureLockInit:
    """Tests for VerisureLock initial state and properties."""

    def test_initial_state_is_locked(self):
        lock = make_lock()
        assert lock._state == "2"

    def test_is_locked_returns_true_when_state_is_2(self):
        lock = make_lock()
        lock._state = "2"
        assert lock.is_locked is True

    def test_is_locked_returns_false_when_state_is_not_2(self):
        lock = make_lock()
        for state in ("1", "3", "4", "0"):
            lock._state = state
            assert lock.is_locked is False, (
                f"Expected is_locked=False for state={state}"
            )

    def test_is_open_always_returns_false(self):
        """is_open is always False — the API has no distinct 'open' state."""
        lock = make_lock()
        for state in ("1", "2", "3", "4", "0"):
            lock._state = state
            assert lock.is_open is False, f"Expected is_open=False for state={state}"

    def test_is_locking_returns_true_when_state_is_4(self):
        lock = make_lock()
        lock._state = "4"
        assert lock.is_locking is True

    def test_is_locking_returns_false_when_state_is_not_4(self):
        lock = make_lock()
        for state in ("1", "2", "3", "0"):
            lock._state = state
            assert lock.is_locking is False, (
                f"Expected is_locking=False for state={state}"
            )

    def test_is_opening_always_returns_false(self):
        lock = make_lock()
        for state in ("1", "2", "3", "4", "0"):
            lock._state = state
            assert lock.is_opening is False

    def test_is_jammed_always_returns_false(self):
        lock = make_lock()
        for state in ("1", "2", "3", "4", "0"):
            lock._state = state
            assert lock.is_jammed is False

    def test_is_unlocking_returns_true_when_state_is_3(self):
        lock = make_lock()
        lock._state = "3"
        assert lock.is_unlocking is True

    def test_is_unlocking_returns_false_when_state_is_not_3(self):
        lock = make_lock()
        for state in ("1", "2", "4", "0"):
            lock._state = state
            assert lock.is_unlocking is False, (
                f"Expected is_unlocking=False for state={state}"
            )

    def test_name_returns_installation_alias_with_device_id(self):
        lock = make_lock()
        assert lock.name == "Home Lock 01"

    def test_name_includes_custom_device_id(self):
        lock = make_lock(device_id="02")
        assert lock.name == "Home Lock 02"


class TestVerisureLockConfig:
    """Tests for VerisureLock unique_id, device_info, and extra_state_attributes."""

    def test_unique_id_includes_device_id(self):
        lock = make_lock(device_id="01")
        assert lock._attr_unique_id == "v4_securitas_direct.123456_lock_01"

    def test_unique_id_different_device(self):
        lock = make_lock(device_id="02")
        assert lock._attr_unique_id == "v4_securitas_direct.123456_lock_02"

    def test_device_info_creates_separate_lock_device_with_config(self):
        """Lock with config gets its own device with metadata."""
        config = SmartLock(
            res="OK",
            location="Front Door",
            family="DR",
            serial_number="SN001",
        )
        lock = make_lock(device_id="01", lock_config=config)
        info = lock._attr_device_info
        assert info is not None
        assert info["identifiers"] == {
            ("securitas", "v4_securitas_direct.123456_lock_01")
        }
        assert info["via_device"] == ("securitas", "v4_securitas_direct.123456")
        assert info["name"] == "Front Door"
        assert info["model"] == "DR"
        assert info["serial_number"] == "SN001"
        assert info["manufacturer"] == "Verisure"

    def test_device_info_fallback_without_config(self):
        """Lock without config falls back to installation-based device."""
        lock = make_lock(device_id="01")
        info = lock._attr_device_info
        assert info is not None
        assert info["identifiers"] == {
            ("securitas", "v4_securitas_direct.123456_lock_01")
        }
        assert info["via_device"] == ("securitas", "v4_securitas_direct.123456")
        assert info["name"] == "Home Lock 01"
        assert info["manufacturer"] == "Verisure"

    def test_device_info_fallback_empty_location(self):
        """Lock with config but empty location uses installation alias."""
        config = SmartLock(res="OK", location="", family="DR")
        lock = make_lock(device_id="02", lock_config=config)
        info = lock._attr_device_info
        assert info["name"] == "Home Lock 02"
        assert info["model"] == "DR"

    def test_device_info_different_devices_have_different_identifiers(self):
        """Each lock gets its own device identifier."""
        lock01 = make_lock(device_id="01")
        lock02 = make_lock(device_id="02")
        assert (
            lock01._attr_device_info["identifiers"]
            != lock02._attr_device_info["identifiers"]
        )
        # But both link to the same parent
        assert (
            lock01._attr_device_info["via_device"]
            == lock02._attr_device_info["via_device"]
        )

    def test_initial_status_unknown_defaults_to_locked(self):
        lock = make_lock(initial_status="0")
        assert lock._state == "2"

    def test_initial_status_preserved_when_not_unknown(self):
        lock = make_lock(initial_status="1")
        assert lock._state == "1"

    def test_extra_state_attributes_empty_without_lock_features(self):
        lock = make_lock()
        assert lock.extra_state_attributes == {}

    def test_extra_state_attributes_with_lock_config(self):
        lock_config = SmartLock(
            res="OK",
            location="Front Door",
            features=LockFeatures(
                hold_back_latch_time=3,
                calibration_type=0,
                autolock=LockAutolock(active=True, timeout=30),
            ),
        )
        lock = make_lock(lock_config=lock_config)
        attrs = lock.extra_state_attributes
        assert attrs is not None
        assert attrs["hold_back_latch_time"] == 3
        assert attrs["autolock_active"] is True
        assert attrs["autolock_timeout"] == 30

    def test_extra_state_attributes_with_no_features(self):
        lock_config = SmartLock(res="OK", location="Front Door")
        lock = make_lock(lock_config=lock_config)
        attrs = lock.extra_state_attributes
        assert attrs == {}

    def test_supported_features_no_config_returns_zero(self):
        import homeassistant.components.lock as lock_mod

        lock = make_lock()
        assert lock.supported_features == lock_mod.LockEntityFeature(0)

    def test_supported_features_with_holdback_returns_open(self):
        import homeassistant.components.lock as lock_mod

        lock_config = SmartLock(
            res="OK",
            features=LockFeatures(hold_back_latch_time=3, calibration_type=0),
        )
        lock = make_lock(lock_config=lock_config)
        assert lock.supported_features == lock_mod.LockEntityFeature.OPEN

    def test_supported_features_holdback_zero_returns_zero(self):
        import homeassistant.components.lock as lock_mod

        lock_config = SmartLock(
            res="OK",
            features=LockFeatures(hold_back_latch_time=0, calibration_type=0),
        )
        lock = make_lock(lock_config=lock_config)
        assert lock.supported_features == lock_mod.LockEntityFeature(0)

    def test_supported_features_no_features_returns_zero(self):
        import homeassistant.components.lock as lock_mod

        lock_config = SmartLock(res="OK", features=None)
        lock = make_lock(lock_config=lock_config)
        assert lock.supported_features == lock_mod.LockEntityFeature(0)


class TestVerisureLockV5Schema:
    """Lock identifiers use the v5 schema and stay in sync."""

    def test_unique_id_uses_v5_schema(self):
        lk = make_lock(device_id="01")
        assert lk._attr_unique_id == "v4_securitas_direct.123456_lock_01"

    def test_device_identifier_uses_v5_schema(self):
        lk = make_lock(device_id="01")
        from custom_components.securitas import DOMAIN

        info = lk._attr_device_info
        assert (DOMAIN, "v4_securitas_direct.123456_lock_01") in info["identifiers"]

    def test_via_device_uses_v5_schema(self):
        lk = make_lock(device_id="01")
        from custom_components.securitas import DOMAIN

        info = lk._attr_device_info
        assert info["via_device"] == (DOMAIN, "v4_securitas_direct.123456")

    def test_update_lock_config_keeps_v5_schema(self):
        from custom_components.securitas.verisure_owa_api.models import (
            SmartLock,
        )

        lk = make_lock(device_id="02")
        new_cfg = SmartLock(location="Front", family="DANALOCK", serial_number="sn")
        lk.update_lock_config(new_cfg)
        from custom_components.securitas import DOMAIN

        info = lk._attr_device_info
        assert (DOMAIN, "v4_securitas_direct.123456_lock_02") in info["identifiers"]
        assert info["via_device"] == (DOMAIN, "v4_securitas_direct.123456")


class TestVerisureLockActions:
    """Tests for VerisureLock async_lock / async_unlock actions."""

    async def test_async_lock_sets_state_to_locking_then_locked_on_success(self):
        lock = make_lock(poll_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_lock()

        # After successful lock, state comes from the fresh API poll ("2")
        assert lock._state == "2"
        # async_schedule_update_ha_state was called during _force_state("4")
        lock.async_schedule_update_ha_state.assert_called()  # type: ignore[attr-defined]
        # async_write_ha_state is called after successful state change
        lock.async_write_ha_state.assert_called()  # type: ignore[attr-defined]
        # get_lock_modes was called with FOREGROUND priority (baseline + verify)
        lock._client.get_lock_modes.assert_awaited_with(  # type: ignore[attr-defined]
            lock.installation, priority=ApiQueue.FOREGROUND
        )
        # Coordinator refresh was requested after the operation
        lock.coordinator.async_request_refresh.assert_awaited_once()

    async def test_async_lock_uses_optimistic_state_when_poll_returns_unknown(self):
        lock = make_lock()  # no poll_status → get_lock_modes returns []
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_lock()

        # Falls back to optimistic "2" (locked) when poll returns UNKNOWN
        assert lock._state == "2"

    async def test_async_unlock_sets_state_to_opening_then_open_on_success(self):
        lock = make_lock(poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_unlock()

        # After successful unlock, state comes from fresh API poll ("1")
        assert lock._state == "1"
        lock.async_schedule_update_ha_state.assert_called()  # type: ignore[attr-defined]
        lock.async_write_ha_state.assert_called()  # type: ignore[attr-defined]

    async def test_async_lock_error_restores_previous_state(self):
        lock = make_lock()
        lock._client.change_lock_mode = AsyncMock(
            side_effect=VerisureOwaError("API error")
        )
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError):
            await lock.async_lock()

        # On error, state is restored from _last_state (initial "2" = locked)
        assert lock._state == "2"

    async def test_async_unlock_error_restores_previous_state(self):
        lock = make_lock()
        lock._client.change_lock_mode = AsyncMock(
            side_effect=VerisureOwaError("API error")
        )
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError):
            await lock.async_unlock()

        # On error, state is restored from _last_state (initial "2" = locked)
        assert lock._state == "2"

    async def test_async_lock_intermediate_state_is_locking(self):
        """Verify _force_state is called with '4' (locking) before the API call."""
        lock = make_lock(poll_status="2")
        observed_states = []

        async def capture_state(installation, lock_mode, device_id=None):
            """Capture state at the moment the API call is made."""
            observed_states.append(lock._state)
            return SmartLockModeStatus()

        lock._client.change_lock_mode = AsyncMock(side_effect=capture_state)

        await lock.async_lock()

        # At the time of the API call, state should have been "4" (locking)
        assert observed_states == ["4"]
        # After completion, state should be "2" (locked) from fresh poll
        assert lock._state == "2"

    async def test_async_unlock_intermediate_state_is_opening(self):
        """Verify _force_state is called with '3' (opening) before the API call."""
        lock = make_lock(poll_status="1")
        observed_states = []

        async def capture_state(installation, lock_mode, device_id=None):
            observed_states.append(lock._state)
            return SmartLockModeStatus()

        lock._client.change_lock_mode = AsyncMock(side_effect=capture_state)

        await lock.async_unlock()

        assert observed_states == ["3"]
        assert lock._state == "1"

    async def test_async_open_sets_state_to_opening_then_open_on_success(self):
        lock = make_lock(poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_open()

        assert lock._state == "1"
        lock.async_schedule_update_ha_state.assert_called()  # type: ignore[attr-defined]
        lock.async_write_ha_state.assert_called()  # type: ignore[attr-defined]

    async def test_async_open_error_restores_previous_state(self):
        lock = make_lock()
        lock._client.change_lock_mode = AsyncMock(
            side_effect=VerisureOwaError("API error")
        )
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError):
            await lock.async_open()

        assert lock._state == "2"

    async def test_async_open_calls_change_lock_mode_with_false(self):
        lock = make_lock(poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_open()

        lock._client.change_lock_mode.assert_awaited_once_with(
            lock.installation, False, "01"
        )

    async def test_async_open_intermediate_state_is_opening(self):
        """Verify _force_state is called with '3' (opening) before the API call."""
        lock = make_lock(poll_status="1")
        observed_states = []

        async def capture_state(installation, lock_mode, device_id=None):
            observed_states.append(lock._state)
            return SmartLockModeStatus()

        lock._client.change_lock_mode = AsyncMock(side_effect=capture_state)

        await lock.async_open()

        assert observed_states == ["3"]
        assert lock._state == "1"

    async def test_async_lock_stale_poll_trusts_api(self):
        """When API still returns pre-command state, we trust it and report failure."""
        # Lock starts open ("1"), we lock it, but the API still returns "1".
        # After the min wait the API should normally have the new state, but
        # if it doesn't, we trust what the API says rather than guess — and
        # surface that as a failure to the service caller (raise + notify).
        lock = make_lock(initial_status="1", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=None)
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError):
            await lock.async_lock()

        assert lock._state == "1"

    async def test_async_unlock_stale_poll_trusts_api(self):
        """When API still returns pre-command state, we trust it and report failure."""
        lock = make_lock(initial_status="2", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=None)
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError):
            await lock.async_unlock()

        assert lock._state == "2"

    async def test_async_lock_confirmed_state_used_when_api_agrees(self):
        """When API returns the expected new state, it is used directly."""
        # Lock starts open ("1"), we lock it, API confirms "2"
        lock = make_lock(initial_status="1", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=None)

        await lock.async_lock()

        # API returned "2" which differs from pre-command "1" → use it
        assert lock._state == "2"

    async def test_async_unlock_confirmed_state_used_when_api_agrees(self):
        """When API returns the expected new state, it is used directly."""
        # Lock starts locked ("2"), we unlock it, API confirms "1"
        lock = make_lock(initial_status="2", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=None)

        await lock.async_unlock()

        # API returned "1" which differs from pre-command "2" → use it
        assert lock._state == "1"

    async def test_async_lock_poll_exception_uses_optimistic_state(self):
        """When _get_lock_state raises, optimistic state is used."""
        lock = make_lock()
        lock._client.change_lock_mode = AsyncMock(return_value=None)
        lock._client.get_lock_modes = AsyncMock(side_effect=Exception("network error"))

        await lock.async_lock()

        # Exception → UNKNOWN → optimistic "2" (locked)
        assert lock._state == "2"

    async def test_operation_in_progress_set_during_lock(self):
        """_operation_in_progress is True while change_lock_mode runs."""
        lock = make_lock(poll_status="2")
        observed = []

        async def capture_flag(installation, lock_mode, device_id=None):
            observed.append(lock._operation_in_progress)

        lock._client.change_lock_mode = AsyncMock(side_effect=capture_flag)

        await lock.async_lock()

        assert observed == [True]
        assert lock._operation_in_progress is False

    async def test_operation_in_progress_cleared_on_error(self):
        """_operation_in_progress is cleared even when the command fails."""
        lock = make_lock()
        lock._client.change_lock_mode = AsyncMock(side_effect=VerisureOwaError("fail"))
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError):
            await lock.async_lock()

        assert lock._operation_in_progress is False

    async def test_operation_in_progress_cleared_on_poll_exception(self):
        """_operation_in_progress is cleared when the post-command poll raises."""
        lock = make_lock()
        lock._client.change_lock_mode = AsyncMock(return_value=None)
        lock._client.get_lock_modes = AsyncMock(side_effect=Exception("boom"))

        await lock.async_lock()

        assert lock._operation_in_progress is False

    async def test_coordinator_update_skipped_during_lock_operation(self):
        """_handle_coordinator_update is a no-op while a lock command is in flight."""
        lock = make_lock()
        lock._operation_in_progress = True
        lock.coordinator.data = LockData(
            modes=[SmartLockMode(res="OK", lock_status="1", device_id="01")]
        )

        lock._handle_coordinator_update()

        # Update was skipped — state unchanged
        assert lock._state == "2"
        lock.async_write_ha_state.assert_not_called()  # type: ignore[attr-defined]


class TestVerisureLockCoordinatorUpdate:
    """Tests for VerisureLock coordinator-driven state updates."""

    def test_coordinator_update_syncs_state_from_data(self):
        lock = make_lock()
        lock.coordinator.data = LockData(
            modes=[SmartLockMode(res="OK", lock_status="1", device_id="01")]
        )

        lock._handle_coordinator_update()

        assert lock._state == "1"
        lock.async_write_ha_state.assert_called_once()  # type: ignore[attr-defined]

    def test_coordinator_update_ignores_zero_status(self):
        lock = make_lock()
        # Initial state is "2" (locked)
        assert lock._state == "2"

        lock.coordinator.data = LockData(
            modes=[SmartLockMode(res="OK", lock_status="0", device_id="01")]
        )

        lock._handle_coordinator_update()

        # State should remain "2" because "0" is ignored
        assert lock._state == "2"
        # async_write_ha_state is still called (to refresh entity)
        lock.async_write_ha_state.assert_called_once()  # type: ignore[attr-defined]

    def test_coordinator_update_syncs_on_non_zero(self):
        lock = make_lock()
        lock.coordinator.data = LockData(
            modes=[SmartLockMode(res="OK", lock_status="3", device_id="01")]
        )

        lock._handle_coordinator_update()

        assert lock._state == "3"

    def test_coordinator_update_ignores_other_device_ids(self):
        """Only status for the lock's own device_id is used."""
        lock = make_lock(device_id="01")
        lock.coordinator.data = LockData(
            modes=[SmartLockMode(res="OK", lock_status="1", device_id="02")]
        )

        lock._handle_coordinator_update()

        # No matching device_id → _current_mode returns None → state unchanged
        assert lock._state == "2"

    def test_coordinator_update_with_none_data(self):
        """When coordinator data is None, state is unchanged."""
        lock = make_lock()
        lock.coordinator.data = None

        lock._handle_coordinator_update()

        assert lock._state == "2"
        lock.async_write_ha_state.assert_called_once()  # type: ignore[attr-defined]

    def test_lock_config_with_holdback_gives_open_feature(self):
        """Lock created with holdBackLatchTime exposes OPEN feature."""
        import homeassistant.components.lock as lock_mod

        lock_config = SmartLock(
            res="OK",
            features=LockFeatures(hold_back_latch_time=3, calibration_type=0),
        )
        lock = make_lock(lock_config=lock_config)

        assert lock.supported_features == lock_mod.LockEntityFeature.OPEN


class TestVerisureLockRemoval:
    """Tests for VerisureLock async_will_remove_from_hass."""

    async def test_async_will_remove_from_hass_cleans_up_config_retries(self):
        lock = make_lock()
        unsub_mock = MagicMock()
        lock.add_config_retry_unsub(unsub_mock)

        await lock.async_will_remove_from_hass()

        unsub_mock.assert_called_once()
        assert lock._config_retry_unsubs == []

    async def test_async_will_remove_from_hass_no_config_retries(self):
        lock = make_lock()

        # Should not raise
        await lock.async_will_remove_from_hass()


# ===========================================================================
# hass-is-None guard tests (issue #323)
# ===========================================================================


class TestHassNoneGuards:
    """Verify entities bail out when hass is None (after removal)."""

    def test_lock_force_state_skips_schedule_when_hass_is_none(self):
        lock = make_lock()
        lock.hass = None  # type: ignore[attr-defined]

        lock._force_state("1")

        assert lock._state == "1"
        lock.async_schedule_update_ha_state.assert_not_called()  # type: ignore[attr-defined]


class TestVerisureLockAlarmListener:
    """Tests for the alarm-coordinator transition listener."""

    def _make_alarm_coord(self, state):
        coord = MagicMock()
        coord.alarm_state = state
        coord.async_add_listener = MagicMock(return_value=lambda: None)
        return coord

    def _state(self, *, i="OFF", p="OFF", a="OFF"):
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )

        return AlarmState(
            interior=getattr(InteriorMode, i),
            perimeter=getattr(PerimeterMode, p),
            annex=getattr(AnnexMode, a),
        )

    async def test_baseline_recorded_on_first_update_and_no_action_taken(self):
        # Lock starts up with alarm already armed; no auto-lock should fire.
        lock = make_lock(initial_status="1")  # currently unlocked
        alarm_coord = self._make_alarm_coord(self._state(i="TOTAL"))
        lock._alarm_coordinator = alarm_coord
        lock._alarm_baseline = None  # explicit
        lock._lock_on_arm_circuits = ["interior"]

        # Trigger first update.
        lock._handle_alarm_coordinator_update()

        # Baseline must be recorded as currently TOTAL.
        from custom_components.securitas.const import CIRCUIT_INTERIOR

        assert CIRCUIT_INTERIOR in (lock._alarm_baseline or set())
        # And no lock action was attempted.
        # (verified more thoroughly in Task 6; here we just check no crash and
        # state unchanged.)
        assert lock._state == "1"

    def test_armed_circuits_helper_excludes_off_modes(self):
        from custom_components.securitas.lock import _armed_circuits
        from custom_components.securitas.const import (
            CIRCUIT_INTERIOR,
            CIRCUIT_PERIMETER,
            CIRCUIT_ANNEX,
        )

        s = self._state(i="OFF", p="ON", a="OFF")
        assert _armed_circuits(s) == {CIRCUIT_PERIMETER}
        s = self._state(i="DAY", p="OFF", a="ON")
        assert _armed_circuits(s) == {CIRCUIT_INTERIOR, CIRCUIT_ANNEX}
        s = self._state(i="TOTAL", p="ON", a="ON")
        assert _armed_circuits(s) == {
            CIRCUIT_INTERIOR,
            CIRCUIT_PERIMETER,
            CIRCUIT_ANNEX,
        }
        s = self._state()  # all OFF
        assert _armed_circuits(s) == set()


# ===========================================================================
# Auto-lock-on-arm tests (Task 6)
# ===========================================================================


class TestVerisureLockAutoLockOnArm:
    """Tests for auto-lock-on-arm behavior."""

    def _make_alarm_coord(self, state):
        coord = MagicMock()
        coord.alarm_state = state
        coord.async_add_listener = MagicMock(return_value=lambda: None)
        return coord

    def _state(self, *, i="OFF", p="OFF", a="OFF"):
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )

        return AlarmState(
            interior=getattr(InteriorMode, i),
            perimeter=getattr(PerimeterMode, p),
            annex=getattr(AnnexMode, a),
        )

    async def test_locks_when_configured_circuit_transitions_to_armed(self):
        # Lock currently unlocked. Auto-lock configured for [interior].
        lock = make_lock(initial_status="1", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._lock_on_arm_circuits = ["interior"]
        # Establish baseline = all OFF.
        coord = self._make_alarm_coord(self._state())
        lock._alarm_coordinator = coord
        lock._handle_alarm_coordinator_update()  # baseline
        # Now interior arms.
        coord.alarm_state = self._state(i="TOTAL")
        lock._handle_alarm_coordinator_update()
        # Drain pending tasks.
        await _drain_lock_tasks(lock)
        lock._client.change_lock_mode.assert_awaited_once()
        # Was a lock command (state=True).
        call = lock._client.change_lock_mode.await_args
        assert call.args[1] is True

    async def test_locks_even_when_cached_state_says_locked(self):
        # Lever A: the cached lock status can be stale (e.g. the user
        # physically unlocked and the backend hasn't propagated it yet), so a
        # cached "locked" must NOT suppress the auto-lock command.
        lock = make_lock(initial_status="2", poll_status="2")  # cached: locked
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._lock_on_arm_circuits = ["interior"]
        coord = self._make_alarm_coord(self._state())
        lock._alarm_coordinator = coord
        lock._handle_alarm_coordinator_update()
        coord.alarm_state = self._state(i="TOTAL")
        lock._handle_alarm_coordinator_update()
        await _drain_lock_tasks(lock)
        lock._client.change_lock_mode.assert_awaited_once()
        assert lock._client.change_lock_mode.await_args.args[1] is True

    async def test_does_not_lock_when_already_locking(self):
        # Lock currently mid-lock-operation (status=4); a new arm transition
        # should not enqueue another auto-lock.
        lock = make_lock(initial_status="4", poll_status="2")
        lock._client.change_lock_mode = AsyncMock()
        lock._lock_on_arm_circuits = ["interior"]
        coord = self._make_alarm_coord(self._state())
        lock._alarm_coordinator = coord
        lock._handle_alarm_coordinator_update()  # baseline = OFF
        coord.alarm_state = self._state(i="TOTAL")
        lock._handle_alarm_coordinator_update()
        await _drain_lock_tasks(lock)
        lock._client.change_lock_mode.assert_not_awaited()

    async def test_does_not_lock_when_unconfigured_circuit_arms(self):
        lock = make_lock(initial_status="1", poll_status="2")
        lock._client.change_lock_mode = AsyncMock()
        lock._lock_on_arm_circuits = ["interior"]  # only interior
        coord = self._make_alarm_coord(self._state())
        lock._alarm_coordinator = coord
        lock._handle_alarm_coordinator_update()
        coord.alarm_state = self._state(p="ON")  # perimeter, not interior
        lock._handle_alarm_coordinator_update()
        await _drain_lock_tasks(lock)
        lock._client.change_lock_mode.assert_not_awaited()

    async def test_or_semantics_any_configured_circuit_fires(self):
        # Configured for [interior, perimeter]; only perimeter arms.
        lock = make_lock(initial_status="1", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._lock_on_arm_circuits = ["interior", "perimeter"]
        coord = self._make_alarm_coord(self._state())
        lock._alarm_coordinator = coord
        lock._handle_alarm_coordinator_update()
        coord.alarm_state = self._state(p="ON")
        lock._handle_alarm_coordinator_update()
        await _drain_lock_tasks(lock)
        lock._client.change_lock_mode.assert_awaited_once()

    async def test_dedupe_when_multiple_circuits_arm_simultaneously(self):
        # Combined-panel arm flips interior + perimeter together.
        lock = make_lock(initial_status="1", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._lock_on_arm_circuits = ["interior", "perimeter"]
        coord = self._make_alarm_coord(self._state())
        lock._alarm_coordinator = coord
        lock._handle_alarm_coordinator_update()
        coord.alarm_state = self._state(i="TOTAL", p="ON")
        lock._handle_alarm_coordinator_update()
        await _drain_lock_tasks(lock)
        # Only one lock command, not two.
        assert lock._client.change_lock_mode.await_count == 1

    async def test_no_lock_on_disarm_transition(self):
        # Going armed→disarmed should NEVER trigger a lock.
        lock = make_lock(initial_status="1", poll_status="2")
        lock._client.change_lock_mode = AsyncMock()
        lock._lock_on_arm_circuits = ["interior"]
        coord = self._make_alarm_coord(self._state(i="TOTAL"))
        lock._alarm_coordinator = coord
        lock._handle_alarm_coordinator_update()  # baseline = armed
        coord.alarm_state = self._state()
        lock._handle_alarm_coordinator_update()  # now disarmed
        await _drain_lock_tasks(lock)
        lock._client.change_lock_mode.assert_not_awaited()

    async def test_no_lock_when_operation_in_progress(self):
        lock = make_lock(initial_status="1", poll_status="2")
        lock._client.change_lock_mode = AsyncMock()
        lock._lock_on_arm_circuits = ["interior"]
        lock._operation_in_progress = True  # simulate ongoing manual lock
        coord = self._make_alarm_coord(self._state())
        lock._alarm_coordinator = coord
        lock._handle_alarm_coordinator_update()
        coord.alarm_state = self._state(i="TOTAL")
        lock._handle_alarm_coordinator_update()
        await _drain_lock_tasks(lock)
        lock._client.change_lock_mode.assert_not_awaited()


# ===========================================================================
# Auto-lock failure notification tests (Task 7)
# ===========================================================================


class TestVerisureLockAutoLockFailure:
    """Tests for the persistent-notification surface on auto-lock failure."""

    async def test_persistent_notification_created_on_lock_failure(self):
        from custom_components.securitas.verisure_owa_api import VerisureOwaError

        lock = make_lock(initial_status="1", poll_status="1")  # stays unlocked
        lock._client.change_lock_mode = AsyncMock(
            side_effect=VerisureOwaError("network down")
        )
        # Patch services so we can capture persistent_notification.create.
        lock.hass.services.async_call = AsyncMock()

        await lock._auto_lock()

        # Look for a persistent_notification.create call.
        calls = lock.hass.services.async_call.await_args_list
        notification_calls = [
            c for c in calls if c.args[:2] == ("persistent_notification", "create")
        ]
        assert len(notification_calls) == 1
        payload = notification_calls[0].args[2]
        assert payload["notification_id"].startswith("verisure_owa_lock_")
        assert "Auto-lock failed" in payload["title"]

    async def test_no_notification_on_successful_auto_lock(self):
        lock = make_lock(initial_status="1", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock.hass.services.async_call = AsyncMock()
        await lock._auto_lock()
        notification_calls = [
            c
            for c in lock.hass.services.async_call.await_args_list
            if c.args[:2] == ("persistent_notification", "create")
        ]
        assert notification_calls == []

    async def test_no_notification_when_lock_actuates_after_delay(self):
        # Reproduces the real log: the device acks the command but actuates a
        # few seconds later. Early reads are stale (same ts as baseline); the
        # real actuation produces a fresh timestamp. The poll must catch the
        # LOCKED state and NOT fire a false "Auto-lock failed" notification.
        lock = make_lock(initial_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],  # baseline
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],  # stale, too early
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],  # stale, still early
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="200"
                    )
                ],  # fresh: actuated
            ]
        )
        lock.hass.services.async_call = AsyncMock()

        await lock._auto_lock()

        assert lock._state == "2"  # ends LOCKED
        notification_calls = [
            c
            for c in lock.hass.services.async_call.await_args_list
            if c.args[:2] == ("persistent_notification", "create")
        ]
        assert notification_calls == []

    async def test_notification_when_lock_stays_unlocked(self):
        # Genuine failure: the lock never reaches LOCKED across the whole
        # verification window → the notification must still fire.
        lock = make_lock(initial_status="1", poll_status="1")  # always unlocked
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock.hass.services.async_call = AsyncMock()

        await lock._auto_lock()

        assert lock._state == "1"  # definitively unlocked
        notification_calls = [
            c
            for c in lock.hass.services.async_call.await_args_list
            if c.args[:2] == ("persistent_notification", "create")
        ]
        assert len(notification_calls) == 1
        assert "Auto-lock failed" in notification_calls[0].args[2]["title"]

    async def test_no_notification_when_post_state_unknown(self):
        # Bias to false-negative: if the status is never readable (UNKNOWN),
        # fall back to optimistic LOCKED and do NOT cry wolf.
        lock = make_lock(initial_status="1")  # poll returns [] → UNKNOWN
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock.hass.services.async_call = AsyncMock()

        await lock._auto_lock()

        notification_calls = [
            c
            for c in lock.hass.services.async_call.await_args_list
            if c.args[:2] == ("persistent_notification", "create")
        ]
        assert notification_calls == []


# ===========================================================================
# Manual lock/unlock/open failure notification tests
# ===========================================================================


def _persistent_notification_calls(lock):
    return [
        c
        for c in lock.hass.services.async_call.await_args_list
        if c.args[:2] == ("persistent_notification", "create")
    ]


class TestVerisureLockManualFailureNotification:
    """async_lock / async_unlock / async_open must surface failure.

    Both via a persistent notification (for UI users) AND by raising
    HomeAssistantError (for scripts/automations / HA service callers).
    Auto-lock-on-arm's behaviour is intentionally separate — see
    TestVerisureLockAutoLockFailure — because its bias-to-false-negative
    must be preserved.
    """

    # --- VerisureOwaError (command-status step) ---------------------------

    async def test_async_lock_raises_HomeAssistantError_on_api_error(self):
        lock = make_lock(initial_status="1", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(
            side_effect=VerisureOwaError("network down")
        )
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError, match="network down"):
            await lock.async_lock()

    async def test_async_lock_fires_notification_on_api_error(self):
        lock = make_lock(initial_status="1", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(
            side_effect=VerisureOwaError("network down")
        )
        lock.hass.services.async_call = AsyncMock()

        with contextlib.suppress(HomeAssistantError):
            await lock.async_lock()

        calls = _persistent_notification_calls(lock)
        assert len(calls) == 1
        payload = calls[0].args[2]
        assert "Lock failed" in payload["title"]
        assert "network down" in payload["message"]

    async def test_async_unlock_raises_HomeAssistantError_on_api_error(self):
        lock = make_lock(initial_status="2", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(
            side_effect=VerisureOwaError("network down")
        )
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError, match="network down"):
            await lock.async_unlock()

    async def test_async_unlock_fires_notification_on_api_error(self):
        lock = make_lock(initial_status="2", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(
            side_effect=VerisureOwaError("network down")
        )
        lock.hass.services.async_call = AsyncMock()

        with contextlib.suppress(HomeAssistantError):
            await lock.async_unlock()

        calls = _persistent_notification_calls(lock)
        assert len(calls) == 1
        assert "Unlock failed" in calls[0].args[2]["title"]

    async def test_async_open_raises_HomeAssistantError_on_api_error(self):
        lock = make_lock(initial_status="2", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(
            side_effect=VerisureOwaError("network down")
        )
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError, match="network down"):
            await lock.async_open()

    async def test_async_open_fires_notification_on_api_error(self):
        lock = make_lock(initial_status="2", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(
            side_effect=VerisureOwaError("network down")
        )
        lock.hass.services.async_call = AsyncMock()

        with contextlib.suppress(HomeAssistantError):
            await lock.async_open()

        calls = _persistent_notification_calls(lock)
        assert len(calls) == 1
        assert "Unlock failed" in calls[0].args[2]["title"]

    # --- Verify-confirmed wrong state (post-command poll) -----------------

    async def test_async_lock_raises_when_verify_confirms_unlocked(self):
        """Fresh verify read of UNLOCKED after a LOCK command = definite failure."""
        lock = make_lock(initial_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],  # baseline
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="200"
                    )
                ],  # fresh, wrong state
            ]
        )
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError):
            await lock.async_lock()

        calls = _persistent_notification_calls(lock)
        assert len(calls) == 1
        assert "Lock failed" in calls[0].args[2]["title"]

    async def test_async_unlock_raises_when_verify_confirms_locked(self):
        """Fresh verify read of LOCKED after an UNLOCK command = definite failure."""
        lock = make_lock(initial_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="100"
                    )
                ],  # baseline
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="200"
                    )
                ],  # fresh, wrong state
            ]
        )
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError):
            await lock.async_unlock()

        calls = _persistent_notification_calls(lock)
        assert len(calls) == 1
        assert "Unlock failed" in calls[0].args[2]["title"]

    async def test_failure_message_uses_readable_state_names_not_raw_codes(self):
        """The notification + raised exception are read by a non-technical user.

        The verify-confirmed-wrong-state failure path must not leak the
        backend's numeric ``lockStatus`` codes (``"1"``, ``"2"``) into the
        user-facing message — that's an internal protocol detail.  Render
        them as human-readable state names instead.
        """
        lock = make_lock(initial_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],  # baseline
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="200"
                    )
                ],  # fresh, still unlocked → confirmed failure
            ]
        )
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError) as exc_info:
            await lock.async_lock()

        # Message goes into both the raised exception AND the persistent
        # notification — neither must contain the raw API codes.
        raised = str(exc_info.value)
        notif_message = _persistent_notification_calls(lock)[0].args[2]["message"]
        for text in (raised, notif_message):
            assert "unlocked" in text.lower()
            assert "locked" in text.lower()
            # The raw codes are protocol noise — must not surface.
            assert "lockStatus=1" not in text
            assert "lockStatus=2" not in text
            assert "(expected 2)" not in text

    # --- Bias-to-false-negative (UNKNOWN → optimistic) --------------------

    async def test_async_lock_no_raise_when_window_exhausts_with_unknown(self):
        """All verify reads return no readable status → optimistic fallback, no raise."""
        lock = make_lock(initial_status="1")  # poll_status=None → empty list
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock.hass.services.async_call = AsyncMock()

        # Must not raise.
        await lock.async_lock()

        assert lock._state == "2"  # optimistic LOCKED
        assert _persistent_notification_calls(lock) == []

    async def test_async_unlock_no_raise_when_window_exhausts_with_unknown(self):
        lock = make_lock(initial_status="2")  # poll_status=None → empty list
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock.hass.services.async_call = AsyncMock()

        await lock.async_unlock()

        assert lock._state == "1"  # optimistic UNLOCKED
        assert _persistent_notification_calls(lock) == []

    # --- Success path -----------------------------------------------------

    async def test_async_lock_no_raise_no_notification_on_success(self):
        lock = make_lock(initial_status="1", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock.hass.services.async_call = AsyncMock()

        await lock.async_lock()

        assert lock._state == "2"
        assert _persistent_notification_calls(lock) == []

    async def test_async_unlock_no_raise_no_notification_on_success(self):
        lock = make_lock(initial_status="2", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock.hass.services.async_call = AsyncMock()

        await lock.async_unlock()

        assert lock._state == "1"
        assert _persistent_notification_calls(lock) == []


# ===========================================================================
# Lock verification poll (poll-until-target) tests
# ===========================================================================


class TestVerisureLockVerifyPoll:
    """The post-command read-back re-polls until the lock reaches the target."""

    async def test_polls_until_target_reached_then_stops(self):
        # Timestamps are required: stale reads (same ts as baseline) keep
        # polling; a fresh read with the target state confirms and stops.
        lock = make_lock(initial_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],  # baseline
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],  # stale, keep polling
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],  # stale, keep polling
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="200"
                    )
                ],  # fresh target, stop
            ]
        )

        await lock.async_lock()

        assert lock._state == "2"
        # Stops as soon as a fresh read lands — 1 baseline + 3 verify reads.
        assert lock._client.get_lock_modes.await_count == 4

    async def test_single_poll_when_target_immediate(self):
        # Baseline at ts=100, verify at ts=200 → first verify is fresh and
        # matches target → loop exits after one verify read.
        lock = make_lock()
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="200"
                    )
                ],
            ]
        )

        await lock.async_lock()

        assert lock._state == "2"
        # 1 baseline read + 1 verify read (target confirmed immediately).
        assert lock._client.get_lock_modes.await_count == 2
        lock._client.get_lock_modes.assert_awaited_with(
            lock.installation, priority=ApiQueue.FOREGROUND
        )

    async def test_gives_up_after_max_attempts_when_target_never_reached(self):
        # A lock attempt whose status never flips: all reads return the same
        # stale timestamp so no read is ever "fresh" — the window exhausts.
        # The exhausted-stale-wrong-state case is a definitive failure and
        # raises (caller wanted LOCKED, last read says UNLOCKED).
        lock = make_lock(initial_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())
        # All reads return ts="100" — identical to baseline, never fresh.
        lock._client.get_lock_modes = AsyncMock(
            return_value=[
                SmartLockMode(lock_status="1", device_id="01", status_timestamp="100")
            ]
        )
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError):
            await lock.async_lock()

        assert lock._state == "1"
        # 1 baseline read + _verify_attempts verify reads (never fresh → exhausts).
        assert lock._client.get_lock_modes.await_count == lock._verify_attempts + 1


# ===========================================================================
# Timestamp-aware confirmation tests
# ===========================================================================


class TestVerisureLockTimestampConfirmation:
    """A fresh read (any status) is authoritative; stale reads keep polling.

    The pre-command timestamp is captured by a live API read at the moment
    the command is sent (see Task 2).  Each subsequent read whose
    ``statusTimestamp`` advances past that baseline is treated as
    authoritative — success or failure — and ends the poll loop.  Reads
    whose timestamp has not advanced are pre-command propagation and
    keep polling until the window exhausts.
    """

    @staticmethod
    def _seed_pre_ts(lock, status, ts):
        lock.coordinator.data = LockData(
            modes=[
                SmartLockMode(lock_status=status, device_id="01", status_timestamp=ts)
            ]
        )

    async def test_fresh_timestamp_confirms_on_first_read(self):
        lock = make_lock(initial_status="1")
        self._seed_pre_ts(lock, "2", "100")  # pre-command ts = 100 (stale coordinator)
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                # Baseline read: pre-command state.
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],
                # Verify read: fresh actuation to target.
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="200"
                    )
                ],
            ]
        )

        await lock.async_lock()

        assert lock._state == "2"
        assert lock._client.get_lock_modes.await_count == 2  # 1 baseline + 1 verify

    async def test_stale_target_read_keeps_polling_until_timestamp_advances(self):
        lock = make_lock(initial_status="2")
        self._seed_pre_ts(lock, "2", "100")
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="100"
                    )
                ],  # baseline read (pre-command state, matches seed)
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="100"
                    )
                ],
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="100"
                    )
                ],
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="300"
                    )
                ],
            ]
        )

        await lock.async_lock()

        assert lock._state == "2"
        # 1 baseline + two stale (ts==100) reads + fresh ts=300 confirmation.
        assert lock._client.get_lock_modes.await_count == 4

    async def test_stale_locked_then_true_unlocked_fires_notification(self):
        # The dangerous case: backend first reports a STALE locked (matching the
        # pre-command ts), then the true UNLOCKED state propagates. ts-gating
        # must not be fooled into confirming the stale locked — it must surface
        # the genuine "armed + unlocked" failure.
        lock = make_lock(initial_status="2")
        self._seed_pre_ts(lock, "2", "100")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="100"
                    )
                ],  # baseline read (pre-command state)
                [
                    SmartLockMode(
                        lock_status="2", device_id="01", status_timestamp="100"
                    )
                ],
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="200"
                    )
                ],
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="200"
                    )
                ],
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="200"
                    )
                ],
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="200"
                    )
                ],
            ]
        )
        lock.hass.services.async_call = AsyncMock()

        await lock._auto_lock()

        assert lock._state == "1"  # settled truth: unlocked
        notification_calls = [
            c
            for c in lock.hass.services.async_call.await_args_list
            if c.args[:2] == ("persistent_notification", "create")
        ]
        assert len(notification_calls) == 1
        assert "Auto-lock failed" in notification_calls[0].args[2]["title"]

    async def test_no_false_failure_when_lock_actuates_late(self):
        # Note: a prior version of this test covered "stale coordinator baseline
        # + pre-command-fresh read" — that scenario became impossible once
        # _change_lock_mode started reading a live baseline (Task 2), so any
        # ts > pre_ts is guaranteed post-command.  The remaining concern this
        # test still locks in is that LATE actuation (slow backend propagation)
        # does not produce a false-failure notification.
        # Lock actuates after a delay: baseline captures pre-command ts=100.
        # Early verify reads return the same ts=100 (stale — backend hasn't
        # propagated the actuation yet) so polling continues.  Eventually the
        # backend stamps ts=200 confirming LOCKED.  Must confirm success and
        # fire NO "Auto-lock failed" notification.
        lock = make_lock(initial_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())

        def mode(status, ts):
            return [
                SmartLockMode(lock_status=status, device_id="01", status_timestamp=ts)
            ]

        # Baseline read: pre-command state (locked, ts=100).
        # Stale reads while waiting for actuation, then fresh LOCKED confirmation.
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[mode("2", "100")] + [mode("2", "100")] * 3 + [mode("2", "200")]
        )
        lock.hass.services.async_call = AsyncMock()

        await lock._auto_lock()

        assert lock._state == "2"  # confirmed locked
        notification_calls = [
            c
            for c in lock.hass.services.async_call.await_args_list
            if c.args[:2] == ("persistent_notification", "create")
        ]
        assert notification_calls == []

    async def test_baseline_is_fresh_api_read_not_coordinator_data(self):
        """The pre-command baseline timestamp must come from a fresh API read.

        Coordinator data can be older than the actual current backend
        timestamp — e.g. when the user physically moved the lock since the
        last coordinator update. The first verify read then looks 'fresh'
        relative to the stale baseline while still reflecting pre-command
        physical state — a false confirmation.

        Scenario: door physically toggled to target state already.
        Coordinator data shows OLD: ts=100, status="2". User physically
        UNLOCKED at ts=500 (status="1"). HA still thinks status="2". User
        asks HA to unlock. Send command. First verify read: ts=500,
        status="1" (the physical-unlock event).
        - Without fresh baseline: 500 > 100 → fresh, status==target →
          confirm. But the actual unlock command hasn't actuated yet!
          False confirmation.
        - With fresh baseline: pre_ts=500 (read RIGHT BEFORE the command).
          First verify read: ts=500, status="1" → not fresh (500 == 500)
          → keep polling. Eventually ts=700, status="1" (real actuation)
          → fresh, confirm.
        """
        lock = make_lock(initial_status="1")
        # Coordinator data shows an OLD timestamp (e.g. last update was ages ago).
        self._seed_pre_ts(lock, "1", "100")
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                # Baseline read: current backend reality (door already unlocked
                # via physical interaction; coordinator hadn't seen it yet).
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="500"
                    )
                ],
                # Verify read 1: still pre-command (lock command not actuated yet).
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="500"
                    )
                ],
                # Verify read 2: real actuation lands.
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="700"
                    )
                ],
            ]
        )

        await lock.async_unlock()

        # We expect THREE get_lock_modes calls: one baseline + two verifies.
        # The bug (using coordinator baseline=100) would confirm on the first
        # verify read and use only TWO calls (no baseline, one verify).
        assert lock._client.get_lock_modes.await_count == 3
        assert lock._state == "1"

    async def test_fresh_wrong_state_returns_early_for_fast_failure(self):
        """A fresh read to a non-target state confirms FAILURE — no further polling.

        When the device reports a fresh status that doesn't match the requested
        target (e.g. lock blocked, device snapped back to unlocked), we have
        definitive evidence of failure. There's no point polling further.
        """
        lock = make_lock(initial_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                # Baseline: ts=100, pre-command unlocked.
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],
                # Verify 1: stale (same ts as baseline) — keep polling.
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],
                # Verify 2: FRESH but status=1 (unlocked) when we wanted target=2.
                # Device snapped back — confirmed failure. Should early-return.
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="200"
                    )
                ],
                # If the test sees these, we're still polling — bug.
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="300"
                    )
                ],
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="400"
                    )
                ],
            ]
        )
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError):
            await lock.async_lock()

        # 1 baseline + 2 verify reads (stale, then fresh-wrong-state) = 3 total.
        assert lock._client.get_lock_modes.await_count == 3
        assert lock._state == "1"  # The confirmed wrong state.

    async def test_quiet_success_when_exhaust_with_status_at_target(self):
        """No-op on already-target lock: stale reads at target → quiet success.

        Some Verisure devices may not re-stamp ``statusTimestamp`` on a no-op
        command (locking an already-locked door).  Every read shows the
        pre-command status equal to target but with the pre-command timestamp,
        so every read is stale.  The window exhausts — but because the final
        state IS the target, we treat it as a quiet success (state = target,
        no notification).
        """
        lock = make_lock(initial_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())
        # Baseline plus every verify attempt: status="2" (already locked), ts="100".
        # Same ts means never fresh → polling exhausts.
        mode = SmartLockMode(lock_status="2", device_id="01", status_timestamp="100")
        lock._client.get_lock_modes = AsyncMock(return_value=[mode])

        await lock.async_lock()

        # All baseline + verify attempts hit the API.
        assert lock._client.get_lock_modes.await_count == 1 + lock._verify_attempts
        # Quiet success: state ends at target, no error path taken.
        assert lock._state == "2"

    async def test_empty_status_timestamp_keeps_polling_not_short_circuit(self):
        """A response with empty/missing statusTimestamp must not be treated as fresh.

        Under v5.0.5's "any fresh read is authoritative" semantics, a fallback that
        treats unparseable timestamps as fresh would short-circuit the verify loop
        on the very first read — returning whatever pre-command status the backend
        echoed back even though the device hasn't actuated yet. The verify loop
        should instead keep polling until either a real (newer) timestamp lands
        or the window exhausts (in which case the quiet-success-on-target branch
        covers a no-op command).
        """
        lock = make_lock(initial_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())
        # Baseline read returns a normal ts. Verify reads all come back with an
        # EMPTY statusTimestamp — the field is just missing from the backend
        # response and SmartLockMode defaults it to "". The lock_status on those
        # reads is still pre-command ("1" unlocked), so a short-circuit here
        # would falsely report failure for a lock command that's actually
        # in-flight.
        lock._client.get_lock_modes = AsyncMock(
            side_effect=[
                # Baseline
                [
                    SmartLockMode(
                        lock_status="1", device_id="01", status_timestamp="100"
                    )
                ],
                # Verify reads (all empty ts, pre-command state)
                *[
                    [
                        SmartLockMode(
                            lock_status="1", device_id="01", status_timestamp=""
                        )
                    ]
                    for _ in range(lock._verify_attempts)
                ],
            ]
        )
        lock.hass.services.async_call = AsyncMock()

        # Window exhausts with the last read being stale-wrong-state ("1" when
        # target was "2") — a definitive failure that raises to the caller.
        with pytest.raises(HomeAssistantError):
            await lock.async_lock()

        # Every verify attempt must run — empty ts is not authoritative.
        assert lock._client.get_lock_modes.await_count == 1 + lock._verify_attempts


class TestTsIsNewer:
    """Unit tests for the verify-loop's freshness comparator."""

    def test_strictly_newer_returns_true(self):
        from custom_components.securitas.lock import _ts_is_newer

        assert _ts_is_newer("200", "100") is True

    def test_equal_returns_false(self):
        from custom_components.securitas.lock import _ts_is_newer

        assert _ts_is_newer("100", "100") is False

    def test_older_returns_false(self):
        from custom_components.securitas.lock import _ts_is_newer

        assert _ts_is_newer("100", "200") is False

    def test_empty_read_ts_returns_false(self):
        """Missing read timestamp → can't compare → treat as stale."""
        from custom_components.securitas.lock import _ts_is_newer

        assert _ts_is_newer("", "100") is False

    def test_empty_base_ts_returns_false(self):
        """Missing baseline → can't compare → treat as stale."""
        from custom_components.securitas.lock import _ts_is_newer

        assert _ts_is_newer("200", "") is False

    def test_both_empty_returns_false(self):
        from custom_components.securitas.lock import _ts_is_newer

        assert _ts_is_newer("", "") is False

    def test_non_numeric_returns_false(self):
        from custom_components.securitas.lock import _ts_is_newer

        assert _ts_is_newer("abc", "100") is False


# ===========================================================================
# Unlock→disarm flow tests (Task 8)
# ===========================================================================


class TestVerisureLockUnlockDisarm:
    """Tests for unlock→disarm flow (success paths)."""

    def _state(self, *, i="OFF", p="OFF", a="OFF"):
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )

        return AlarmState(
            interior=getattr(InteriorMode, i),
            perimeter=getattr(PerimeterMode, p),
            annex=getattr(AnnexMode, a),
        )

    def _make_alarm_panel(self, *, success=True):
        panel = MagicMock()
        panel.execute_partial_disarm = AsyncMock(return_value=success)
        return panel

    def _make_alarm_coord(self, state):
        coord = MagicMock()
        coord.alarm_state = state
        return coord

    async def test_disarm_and_unlock_run_in_parallel(self):
        """Disarm and unlock dispatch concurrently — neither blocks on the other.

        Verified via cross-coupled events: each fake awaits the other's "started"
        event before completing. Sequential execution (in either order) would
        deadlock; parallel execution lets both progress and the test completes.
        """
        import asyncio

        lock = make_lock(initial_status="2", poll_status="1")
        lock._unlock_disarms_circuits = ["interior"]
        lock._combined_alarm_panel = self._make_alarm_panel(success=True)
        lock._alarm_coordinator = self._make_alarm_coord(self._state(i="TOTAL"))

        disarm_started = asyncio.Event()
        unlock_started = asyncio.Event()

        async def fake_disarm(_circuits):
            disarm_started.set()
            await asyncio.wait_for(unlock_started.wait(), timeout=1.0)
            return True

        async def fake_change(_installation, _lock_state, _device_id=None):
            unlock_started.set()
            await asyncio.wait_for(disarm_started.wait(), timeout=1.0)
            return MagicMock()

        lock._combined_alarm_panel.execute_partial_disarm = AsyncMock(
            side_effect=fake_disarm
        )
        lock._client.change_lock_mode = AsyncMock(side_effect=fake_change)

        await lock.async_unlock()

        assert disarm_started.is_set()
        assert unlock_started.is_set()
        lock._combined_alarm_panel.execute_partial_disarm.assert_awaited_once_with(
            ["interior"]
        )
        lock._client.change_lock_mode.assert_awaited_once()

    async def test_disarm_skipped_when_alarm_already_disarmed(self):
        lock = make_lock(initial_status="2", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._unlock_disarms_circuits = ["interior"]
        lock._combined_alarm_panel = self._make_alarm_panel(success=True)
        # Alarm already fully disarmed.
        lock._alarm_coordinator = self._make_alarm_coord(self._state())

        await lock.async_unlock()

        lock._combined_alarm_panel.execute_partial_disarm.assert_not_awaited()
        # Unlock still proceeds.
        lock._client.change_lock_mode.assert_awaited_once()

    async def test_disarm_skipped_when_no_circuits_configured(self):
        lock = make_lock(initial_status="2", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._unlock_disarms_circuits = []  # no automation
        lock._combined_alarm_panel = self._make_alarm_panel(success=True)
        lock._alarm_coordinator = self._make_alarm_coord(self._state(i="TOTAL"))

        await lock.async_unlock()

        lock._combined_alarm_panel.execute_partial_disarm.assert_not_awaited()
        lock._client.change_lock_mode.assert_awaited_once()

    async def test_async_open_follows_same_disarm_first_flow(self):
        lock = make_lock(initial_status="2", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._unlock_disarms_circuits = ["interior"]
        lock._combined_alarm_panel = self._make_alarm_panel(success=True)
        lock._alarm_coordinator = self._make_alarm_coord(self._state(i="TOTAL"))

        await lock.async_open()

        lock._combined_alarm_panel.execute_partial_disarm.assert_awaited_once_with(
            ["interior"]
        )
        lock._client.change_lock_mode.assert_awaited_once()

    async def test_no_disarm_dispatched_when_panel_unavailable(self):
        # Defensive: missing panel reference (e.g., setup race) → skip disarm.
        lock = make_lock(initial_status="2", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._unlock_disarms_circuits = ["interior"]
        lock._combined_alarm_panel = None
        lock._alarm_coordinator = self._make_alarm_coord(self._state(i="TOTAL"))
        await lock.async_unlock()  # must not raise
        lock._client.change_lock_mode.assert_awaited_once()


# ===========================================================================
# Unlock-disarm failure notification tests (Task 9)
# ===========================================================================


class TestVerisureLockUnlockDisarmFailure:
    """Tests for unlock-disarm failure surfaces."""

    def _state(self, *, i="OFF", p="OFF", a="OFF"):
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
            AnnexMode,
        )

        return AlarmState(
            interior=getattr(InteriorMode, i),
            perimeter=getattr(PerimeterMode, p),
            annex=getattr(AnnexMode, a),
        )

    def _make_alarm_coord(self, state):
        coord = MagicMock()
        coord.alarm_state = state
        return coord

    async def test_pre_unlock_disarm_failure_notifies_and_proceeds(self):
        lock = make_lock(initial_status="2", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._unlock_disarms_circuits = ["interior"]
        lock._alarm_coordinator = self._make_alarm_coord(self._state(i="TOTAL"))
        panel = MagicMock()
        panel.execute_partial_disarm = AsyncMock(return_value=False)
        lock._combined_alarm_panel = panel
        lock.hass.services.async_call = AsyncMock()

        await lock.async_unlock()

        # Notification fired with "Auto-disarm failed" wording.
        notif_calls = [
            c
            for c in lock.hass.services.async_call.await_args_list
            if c.args[:2] == ("persistent_notification", "create")
        ]
        assert len(notif_calls) == 1
        assert "Auto-disarm failed" in notif_calls[0].args[2]["title"]
        # Unlock still happened.
        lock._client.change_lock_mode.assert_awaited_once()

    async def test_unlock_failure_after_successful_disarm_notifies(self):
        from custom_components.securitas.verisure_owa_api import VerisureOwaError

        lock = make_lock(initial_status="2", poll_status="2")  # stays locked
        lock._client.change_lock_mode = AsyncMock(side_effect=VerisureOwaError("nope"))
        lock._unlock_disarms_circuits = ["interior"]
        lock._alarm_coordinator = self._make_alarm_coord(self._state(i="TOTAL"))
        panel = MagicMock()
        panel.execute_partial_disarm = AsyncMock(return_value=True)
        lock._combined_alarm_panel = panel
        lock.hass.services.async_call = AsyncMock()

        with pytest.raises(HomeAssistantError):
            await lock.async_unlock()

        # The unlock failed — notification with "Unlock failed" wording.
        notif_calls = [
            c
            for c in lock.hass.services.async_call.await_args_list
            if c.args[:2] == ("persistent_notification", "create")
        ]
        assert len(notif_calls) == 1
        assert "Unlock failed" in notif_calls[0].args[2]["title"]

    async def test_no_notification_on_full_success(self):
        lock = make_lock(initial_status="2", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=MagicMock())
        lock._unlock_disarms_circuits = ["interior"]
        lock._alarm_coordinator = self._make_alarm_coord(self._state(i="TOTAL"))
        panel = MagicMock()
        panel.execute_partial_disarm = AsyncMock(return_value=True)
        lock._combined_alarm_panel = panel
        lock.hass.services.async_call = AsyncMock()

        await lock.async_unlock()

        notif_calls = [
            c
            for c in lock.hass.services.async_call.await_args_list
            if c.args[:2] == ("persistent_notification", "create")
        ]
        assert notif_calls == []


# ===========================================================================
# TestVerisureLockSetupAndTeardown
# ===========================================================================


class TestVerisureLockSetupAndTeardown:
    """Tests for async_added_to_hass / async_will_remove_from_hass wiring."""

    async def test_loads_per_lock_options_and_subscribes(self):
        from custom_components.securitas.const import (
            CONF_LOCK_AUTOMATIONS,
        )

        lock = make_lock(initial_status="2")
        # Stand in for hass-managed plumbing.
        unsub = MagicMock()
        alarm_coord = MagicMock()
        alarm_coord.async_add_listener = MagicMock(return_value=unsub)
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
        )

        alarm_coord.alarm_state = AlarmState(
            interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF
        )
        panel = MagicMock()
        entry = MagicMock()
        entry.entry_id = "entry-1"
        entry.options = {
            CONF_LOCK_AUTOMATIONS: {
                lock._device_id: {
                    "lock_on_arm": ["interior", "perimeter"],
                    "unlock_disarms": ["interior"],
                }
            }
        }
        from custom_components.securitas import DOMAIN

        lock.hass.data = {
            DOMAIN: {
                "entry-1": {
                    "alarm_coordinator": alarm_coord,
                    "combined_alarm_panels": {
                        lock.installation.number: panel,
                    },
                    "config_entry": entry,
                }
            }
        }
        lock._entry_id = "entry-1"  # set by setup helper

        await lock.async_added_to_hass()

        assert lock._lock_on_arm_circuits == ["interior", "perimeter"]
        assert lock._unlock_disarms_circuits == ["interior"]
        assert lock._alarm_coordinator is alarm_coord
        assert lock._combined_alarm_panel is panel
        alarm_coord.async_add_listener.assert_called_once()
        # Baseline established (no firing on first call).
        assert lock._alarm_baseline is not None

    async def test_defaults_to_empty_when_no_options(self):
        lock = make_lock()
        alarm_coord = MagicMock()
        alarm_coord.async_add_listener = MagicMock(return_value=lambda: None)
        from custom_components.securitas.verisure_owa_api.models import (
            AlarmState,
            InteriorMode,
            PerimeterMode,
        )

        alarm_coord.alarm_state = AlarmState(
            interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF
        )
        entry = MagicMock()
        entry.entry_id = "entry-1"
        entry.options = {}
        from custom_components.securitas import DOMAIN

        lock.hass.data = {
            DOMAIN: {
                "entry-1": {
                    "alarm_coordinator": alarm_coord,
                    "combined_alarm_panels": {
                        lock.installation.number: MagicMock(),
                    },
                    "config_entry": entry,
                }
            }
        }
        lock._entry_id = "entry-1"

        await lock.async_added_to_hass()

        assert lock._lock_on_arm_circuits == []
        assert lock._unlock_disarms_circuits == []

    async def test_unsubscribe_called_on_removal(self):
        lock = make_lock()
        unsub = MagicMock()
        lock._alarm_listener_unsub = unsub
        await lock.async_will_remove_from_hass()
        unsub.assert_called_once()
