"""Tests for sensor and lock platform entities."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.securitas.securitas_direct_new_api.models import (
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
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
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
from custom_components.securitas.lock import SecuritasLock

pytestmark = pytest.mark.asyncio


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
    """Create a mock SecuritasHub client."""
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
    """Create a SecuritasLock with mocked dependencies.

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

    lock_entity = SecuritasLock(
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
    return lock_entity


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

    def test_name_contains_installation_alias(self):
        installation = make_installation()
        coordinator = _make_sentinel_coordinator()
        sensor = SentinelTemperature(coordinator, installation, 1)
        assert installation.alias in sensor._attr_name  # type: ignore[operator]
        assert "Temperature" in sensor._attr_name  # type: ignore[operator]


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


# ===========================================================================
# ActivityLogSensor tests
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
# SecuritasLock tests
# ===========================================================================


class TestSecuritasLockInit:
    """Tests for SecuritasLock initial state and properties."""

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


class TestSecuritasLockConfig:
    """Tests for SecuritasLock unique_id, device_info, and extra_state_attributes."""

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
        assert info["manufacturer"] == "Securitas Direct"

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
        assert info["manufacturer"] == "Securitas Direct"

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


class TestSecuritasLockActions:
    """Tests for SecuritasLock async_lock / async_unlock actions."""

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
        # get_lock_modes was called with FOREGROUND priority to fetch real status
        lock._client.get_lock_modes.assert_awaited_once_with(  # type: ignore[attr-defined]
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
            side_effect=SecuritasDirectError("API error")
        )

        await lock.async_lock()

        # On error, state is restored from _last_state (initial "2" = locked)
        assert lock._state == "2"

    async def test_async_unlock_error_restores_previous_state(self):
        lock = make_lock()
        lock._client.change_lock_mode = AsyncMock(
            side_effect=SecuritasDirectError("API error")
        )

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
            side_effect=SecuritasDirectError("API error")
        )

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
        """When API still returns pre-command state, we trust it."""
        # Lock starts open ("1"), we lock it, but the API still returns "1".
        # After the min wait the API should normally have the new state, but
        # if it doesn't, we trust what the API says rather than guess.
        lock = make_lock(initial_status="1", poll_status="1")
        lock._client.change_lock_mode = AsyncMock(return_value=None)

        await lock.async_lock()

        assert lock._state == "1"

    async def test_async_unlock_stale_poll_trusts_api(self):
        """When API still returns pre-command state, we trust it."""
        lock = make_lock(initial_status="2", poll_status="2")
        lock._client.change_lock_mode = AsyncMock(return_value=None)

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
        lock._client.change_lock_mode = AsyncMock(
            side_effect=SecuritasDirectError("fail")
        )

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


class TestSecuritasLockCoordinatorUpdate:
    """Tests for SecuritasLock coordinator-driven state updates."""

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


class TestSecuritasLockRemoval:
    """Tests for SecuritasLock async_will_remove_from_hass."""

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
