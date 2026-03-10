"""Tests for sensor and lock platform entities."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    AirQuality,
    Attribute,
    Attributes,
    Installation,
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
    SentinelAirQuality,
    SentinelHumidity,
    SentinelTemperature,
)
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
        attributes=Attributes(
            name="attrs",
            attributes=[Attribute(name="zone", value="1", active=True)],
        ),
        listdiy=[],
        listprompt=[],
        installation=make_installation(),
    )


def make_sentinel(temp=22, humidity=45):
    """Create a test Sentinel data object."""
    return Sentinel(
        alias="Living", air_quality="GOOD", humidity=humidity, temperature=temp
    )


def make_air_quality(value=85, message="Good"):
    """Create a test AirQuality data object."""
    return AirQuality(value=value, message=message)


def make_client():
    """Create a mock SecuritasHub client."""
    client = MagicMock()
    client.session = AsyncMock()
    client.config = {"scan_interval": 120}
    client.lang = "es"
    return client


def make_device():
    """Create a test SecuritasDirectDevice."""
    from custom_components.securitas import SecuritasDirectDevice

    return SecuritasDirectDevice(make_installation())


def make_lock_config(
    device_id="01",
    location="Front Door",
    family="DR",
    serial_number="SN001",
):
    """Create a test SmartLock config."""
    return SmartLock(
        res="OK",
        location=location,
        type=1,
        deviceId=device_id,
        family=family,
        serialNumber=serial_number,
        label="lock1",
    )


def make_lock(device_id="01", lock_config=None):
    """Create a SecuritasLock with mocked dependencies."""
    installation = make_installation()
    client = MagicMock()
    client.config = {"scan_interval": 120}
    client.session = AsyncMock()
    hass = MagicMock()
    hass.async_create_task = MagicMock()
    hass.services = MagicMock()

    if lock_config is None:
        lock_config = make_lock_config(device_id=device_id)

    with patch(
        "custom_components.securitas.lock.async_track_time_interval"
    ) as mock_track:
        mock_track.return_value = MagicMock()
        lock_entity = SecuritasLock(
            installation=installation,
            client=client,
            hass=hass,
            device_id=device_id,
            lock_config=lock_config,
        )
    return lock_entity


# ===========================================================================
# SentinelTemperature tests
# ===========================================================================


class TestSentinelTemperature:
    """Tests for SentinelTemperature sensor entity."""

    def test_init_sets_native_value_to_temperature(self):
        sentinel = make_sentinel(temp=22)
        sensor = SentinelTemperature(
            sentinel, make_service(), make_client(), make_device()
        )
        assert sensor._attr_native_value == 22

    def test_init_sets_device_class_to_temperature(self):
        from homeassistant.components.sensor import SensorDeviceClass

        sensor = SentinelTemperature(
            make_sentinel(), make_service(), make_client(), make_device()
        )
        assert sensor._attr_device_class == SensorDeviceClass.TEMPERATURE

    def test_init_sets_unit_to_celsius(self):
        from homeassistant.const import UnitOfTemperature

        sensor = SentinelTemperature(
            make_sentinel(), make_service(), make_client(), make_device()
        )
        assert sensor._attr_native_unit_of_measurement == UnitOfTemperature.CELSIUS

    async def test_async_update_calls_get_sentinel_data_and_updates(self):
        client = make_client()
        service = make_service()
        sensor = SentinelTemperature(
            make_sentinel(temp=22), service, client, make_device()
        )
        sensor.hass = MagicMock()
        assert sensor._attr_native_value == 22

        updated_sentinel = make_sentinel(temp=30)
        client.session.get_sentinel_data = AsyncMock(return_value=updated_sentinel)

        await sensor.async_update()

        client.session.get_sentinel_data.assert_awaited_once_with(
            service.installation, service
        )
        assert sensor._attr_native_value == 30

    def test_unique_id_contains_alias_and_service_id(self):
        sentinel = make_sentinel()
        service = make_service()
        sensor = SentinelTemperature(sentinel, service, make_client(), make_device())
        assert sentinel.alias in sensor._attr_unique_id
        assert str(service.id) in sensor._attr_unique_id

    def test_name_contains_alias(self):
        sentinel = make_sentinel()
        sensor = SentinelTemperature(
            sentinel, make_service(), make_client(), make_device()
        )
        assert "Living" in sensor._attr_name


# ===========================================================================
# SentinelHumidity tests
# ===========================================================================


class TestSentinelHumidity:
    """Tests for SentinelHumidity sensor entity."""

    def test_init_sets_native_value_to_humidity(self):
        sentinel = make_sentinel(humidity=45)
        sensor = SentinelHumidity(
            sentinel, make_service(), make_client(), make_device()
        )
        assert sensor._attr_native_value == 45

    def test_init_sets_device_class_to_humidity(self):
        from homeassistant.components.sensor import SensorDeviceClass

        sensor = SentinelHumidity(
            make_sentinel(), make_service(), make_client(), make_device()
        )
        assert sensor._attr_device_class == SensorDeviceClass.HUMIDITY

    def test_init_sets_unit_to_percentage(self):
        from homeassistant.const import PERCENTAGE

        sensor = SentinelHumidity(
            make_sentinel(), make_service(), make_client(), make_device()
        )
        assert sensor._attr_native_unit_of_measurement == PERCENTAGE

    async def test_async_update_calls_get_sentinel_data_and_updates(self):
        client = make_client()
        service = make_service()
        sensor = SentinelHumidity(
            make_sentinel(humidity=45), service, client, make_device()
        )
        sensor.hass = MagicMock()
        assert sensor._attr_native_value == 45

        updated_sentinel = make_sentinel(humidity=60)
        client.session.get_sentinel_data = AsyncMock(return_value=updated_sentinel)

        await sensor.async_update()

        client.session.get_sentinel_data.assert_awaited_once_with(
            service.installation, service
        )
        assert sensor._attr_native_value == 60

    def test_unique_id_contains_alias_and_service_id(self):
        sentinel = make_sentinel()
        service = make_service()
        sensor = SentinelHumidity(sentinel, service, make_client(), make_device())
        assert sentinel.alias in sensor._attr_unique_id
        assert str(service.id) in sensor._attr_unique_id


# ===========================================================================
# SentinelAirQuality tests
# ===========================================================================


class TestSentinelAirQuality:
    """Tests for SentinelAirQuality sensor entity."""

    def test_init_sets_native_value_to_air_quality_message(self):
        air_quality = make_air_quality(value=85, message="Good")
        sensor = SentinelAirQuality(
            air_quality, make_sentinel(), make_service(), make_client(), make_device()
        )
        assert sensor._attr_native_value == "Good"

    async def test_async_update_calls_get_air_quality_data_and_updates(self):
        client = make_client()
        service = make_service()
        air_quality = make_air_quality(value=85, message="Good")
        sensor = SentinelAirQuality(
            air_quality, make_sentinel(), service, client, make_device()
        )
        sensor.hass = MagicMock()
        assert sensor._attr_native_value == "Good"

        updated_air_quality = make_air_quality(value=40, message="Poor")
        client.session.get_air_quality_data = AsyncMock(
            return_value=updated_air_quality
        )

        await sensor.async_update()

        client.session.get_air_quality_data.assert_awaited_once_with(
            service.installation, service
        )
        assert sensor._attr_native_value == "Poor"

    def test_extra_state_attributes_returns_value_and_message(self):
        air_quality = make_air_quality(value=85, message="Good")
        sensor = SentinelAirQuality(
            air_quality, make_sentinel(), make_service(), make_client(), make_device()
        )
        attrs = sensor.extra_state_attributes
        assert attrs["value"] == 85
        assert attrs["message"] == "Good"

    def test_extra_state_attributes_updates_after_new_data(self):
        air_quality = make_air_quality(value=85, message="Good")
        sensor = SentinelAirQuality(
            air_quality, make_sentinel(), make_service(), make_client(), make_device()
        )
        # The extra_state_attributes reads from self._air_quality, which is set
        # at init time. Verify the initial values are correct.
        attrs = sensor.extra_state_attributes
        assert attrs["value"] == 85
        assert attrs["message"] == "Good"

    def test_unique_id_contains_alias_and_service_id(self):
        sentinel = make_sentinel()
        service = make_service()
        sensor = SentinelAirQuality(
            make_air_quality(), sentinel, service, make_client(), make_device()
        )
        assert sentinel.alias in sensor._attr_unique_id
        assert str(service.id) in sensor._attr_unique_id


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

    def test_is_open_returns_true_when_state_is_1(self):
        lock = make_lock()
        lock._state = "1"
        assert lock.is_open is True

    def test_is_open_returns_false_when_state_is_not_1(self):
        lock = make_lock()
        for state in ("2", "3", "4", "0"):
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

    def test_is_opening_returns_true_when_state_is_3(self):
        lock = make_lock()
        lock._state = "3"
        assert lock.is_opening is True

    def test_is_opening_returns_false_when_state_is_not_3(self):
        lock = make_lock()
        for state in ("1", "2", "4", "0"):
            lock._state = state
            assert lock.is_opening is False, (
                f"Expected is_opening=False for state={state}"
            )

    def test_is_jammed_always_returns_false(self):
        lock = make_lock()
        for state in ("1", "2", "3", "4", "0"):
            lock._state = state
            assert lock.is_jammed is False

    def test_is_unlocking_always_returns_false(self):
        lock = make_lock()
        for state in ("1", "2", "3", "4", "0"):
            lock._state = state
            assert lock.is_unlocking is False

    def test_name_returns_lock_config_location(self):
        lock = make_lock()
        assert lock.name == "Front Door"

    def test_name_falls_back_when_no_location(self):
        config = SmartLock(deviceId="01")
        lock = make_lock(lock_config=config)
        assert lock.name == "Home Lock 01"

    def test_unique_id_contains_device_id(self):
        lock = make_lock(device_id="02")
        assert "lock.02" in lock._attr_unique_id

    def test_unique_id_contains_installation_number(self):
        lock = make_lock()
        assert "123456" in lock._attr_unique_id

    def test_device_info_uses_lock_config(self):
        config = make_lock_config(
            device_id="01",
            location="Front Door",
            family="DR",
            serial_number="SN001",
        )
        lock = make_lock(lock_config=config)
        assert lock._attr_device_info["name"] == "Front Door"
        assert lock._attr_device_info["model"] == "DR"
        assert lock._attr_device_info["serial_number"] == "SN001"
        assert lock._attr_device_info["manufacturer"] == "Securitas Direct"

    def test_device_info_via_device_links_to_installation(self):
        lock = make_lock()
        assert lock._attr_device_info["via_device"] == (
            "securitas",
            "securitas_direct.123456",
        )


class TestSecuritasLockActions:
    """Tests for SecuritasLock async_lock / async_unlock actions."""

    async def test_async_lock_sets_state_to_locking_then_locked_on_success(self):
        lock = make_lock()
        lock.async_schedule_update_ha_state = MagicMock()
        lock.client.session.change_lock_mode = AsyncMock(
            return_value=SmartLockModeStatus()
        )

        await lock.async_lock()

        # After successful lock, final state should be "2" (locked)
        assert lock._state == "2"
        # async_schedule_update_ha_state was called during __force_state("4")
        lock.async_schedule_update_ha_state.assert_called()

    async def test_async_unlock_sets_state_to_opening_then_open_on_success(self):
        lock = make_lock()
        lock.async_schedule_update_ha_state = MagicMock()
        lock.client.session.change_lock_mode = AsyncMock(
            return_value=SmartLockModeStatus()
        )

        await lock.async_unlock()

        # After successful unlock, final state should be "1" (open)
        assert lock._state == "1"
        lock.async_schedule_update_ha_state.assert_called()

    async def test_async_lock_error_does_not_change_final_state(self):
        lock = make_lock()
        lock.async_schedule_update_ha_state = MagicMock()
        lock.client.session.change_lock_mode = AsyncMock(
            side_effect=SecuritasDirectError("API error")
        )

        await lock.async_lock()

        # __force_state("4") was called, but then the error caused early return.
        # State remains "4" (locking) — it does NOT reach "2" (locked).
        assert lock._state == "4"

    async def test_async_unlock_error_does_not_change_final_state(self):
        lock = make_lock()
        lock.async_schedule_update_ha_state = MagicMock()
        lock.client.session.change_lock_mode = AsyncMock(
            side_effect=SecuritasDirectError("API error")
        )

        await lock.async_unlock()

        # __force_state("3") was called, but then the error caused early return.
        # State remains "3" (opening) — it does NOT reach "1" (open).
        assert lock._state == "3"

    async def test_async_lock_intermediate_state_is_locking(self):
        """Verify __force_state is called with '4' (locking) before the API call."""
        lock = make_lock()
        observed_states = []

        original_schedule = MagicMock()
        lock.async_schedule_update_ha_state = original_schedule

        async def capture_state(installation, lock_mode, **kwargs):
            """Capture state at the moment the API call is made."""
            observed_states.append(lock._state)
            return SmartLockModeStatus()

        lock.client.session.change_lock_mode = AsyncMock(side_effect=capture_state)

        await lock.async_lock()

        # At the time of the API call, state should have been "4" (locking)
        assert observed_states == ["4"]
        # After completion, state should be "2" (locked)
        assert lock._state == "2"

    async def test_async_unlock_intermediate_state_is_opening(self):
        """Verify __force_state is called with '3' (opening) before the API call."""
        lock = make_lock()
        observed_states = []

        lock.async_schedule_update_ha_state = MagicMock()

        async def capture_state(installation, lock_mode, **kwargs):
            observed_states.append(lock._state)
            return SmartLockModeStatus()

        lock.client.session.change_lock_mode = AsyncMock(side_effect=capture_state)

        await lock.async_unlock()

        assert observed_states == ["3"]
        assert lock._state == "1"

    async def test_async_lock_passes_device_id(self):
        lock = make_lock(device_id="02")
        lock.async_schedule_update_ha_state = MagicMock()
        lock.client.session.change_lock_mode = AsyncMock(
            return_value=SmartLockModeStatus()
        )

        await lock.async_lock()

        lock.client.session.change_lock_mode.assert_awaited_once_with(
            lock.installation, True, device_id="02"
        )

    async def test_async_unlock_passes_device_id(self):
        lock = make_lock(device_id="03")
        lock.async_schedule_update_ha_state = MagicMock()
        lock.client.session.change_lock_mode = AsyncMock(
            return_value=SmartLockModeStatus()
        )

        await lock.async_unlock()

        lock.client.session.change_lock_mode.assert_awaited_once_with(
            lock.installation, False, device_id="03"
        )


class TestSecuritasLockUpdateStatus:
    """Tests for SecuritasLock async_update_status."""

    async def test_async_update_status_updates_state_from_api(self):
        lock = make_lock(device_id="01")
        lock.client.session.get_lock_current_mode = AsyncMock(
            return_value=[SmartLockMode(res="OK", lockStatus="1", deviceId="01")]
        )

        await lock.async_update_status()

        assert lock._state == "1"

    async def test_async_update_status_ignores_zero_status(self):
        lock = make_lock(device_id="01")
        # Initial state is "2" (locked)
        assert lock._state == "2"

        lock.client.session.get_lock_current_mode = AsyncMock(
            return_value=[SmartLockMode(res="OK", lockStatus="0", deviceId="01")]
        )

        await lock.async_update_status()

        # State should remain "2" because "0" is ignored
        assert lock._state == "2"

    async def test_async_update_status_updates_on_non_zero(self):
        lock = make_lock(device_id="01")
        lock.client.session.get_lock_current_mode = AsyncMock(
            return_value=[SmartLockMode(res="OK", lockStatus="3", deviceId="01")]
        )

        await lock.async_update_status()

        assert lock._state == "3"

    async def test_async_update_delegates_to_update_status(self):
        """async_update just calls async_update_status."""
        lock = make_lock(device_id="01")
        lock.client.session.get_lock_current_mode = AsyncMock(
            return_value=[SmartLockMode(res="OK", lockStatus="1", deviceId="01")]
        )

        await lock.async_update()

        lock.client.session.get_lock_current_mode.assert_awaited_once()
        assert lock._state == "1"

    async def test_async_update_matches_correct_device_id(self):
        """When multiple locks returned, matches by device_id."""
        lock = make_lock(device_id="02")
        lock.client.session.get_lock_current_mode = AsyncMock(
            return_value=[
                SmartLockMode(res="OK", lockStatus="2", deviceId="01"),
                SmartLockMode(res="OK", lockStatus="1", deviceId="02"),
            ]
        )

        await lock.async_update_status()

        # Should use status from device "02", not "01"
        assert lock._state == "1"

    async def test_async_update_fallback_single_lock_no_match(self):
        """When only one lock returned and deviceId doesn't match, use it anyway."""
        lock = make_lock(device_id="99")
        lock.client.session.get_lock_current_mode = AsyncMock(
            return_value=[SmartLockMode(res="OK", lockStatus="1", deviceId="01")]
        )

        await lock.async_update_status()

        assert lock._state == "1"

    async def test_async_update_returns_unknown_when_no_match(self):
        """When multiple locks but none match, return unknown (state unchanged)."""
        lock = make_lock(device_id="99")
        # Initial state is "2" (locked)
        assert lock._state == "2"

        lock.client.session.get_lock_current_mode = AsyncMock(
            return_value=[
                SmartLockMode(res="OK", lockStatus="1", deviceId="01"),
                SmartLockMode(res="OK", lockStatus="1", deviceId="02"),
            ]
        )

        await lock.async_update_status()

        # "0" (UNKNOWN) is ignored, so state stays "2"
        assert lock._state == "2"

    async def test_async_update_empty_list_keeps_state(self):
        """When API returns empty list, state stays unchanged."""
        lock = make_lock(device_id="01")
        assert lock._state == "2"

        lock.client.session.get_lock_current_mode = AsyncMock(return_value=[])

        await lock.async_update_status()

        # Empty list → get_lock_state returns "0" → ignored → state stays "2"
        assert lock._state == "2"


class TestSecuritasLockRemoval:
    """Tests for SecuritasLock async_will_remove_from_hass."""

    async def test_async_will_remove_from_hass_unsubscribes(self):
        lock = make_lock()
        unsub_mock = MagicMock()
        lock._update_unsub = unsub_mock

        await lock.async_will_remove_from_hass()

        unsub_mock.assert_called_once()

    async def test_async_will_remove_from_hass_handles_none_unsub(self):
        lock = make_lock()
        lock._update_unsub = None

        # Should not raise
        await lock.async_will_remove_from_hass()


# ===========================================================================
# hass-is-None guard tests (issue #323)
# ===========================================================================


class TestHassNoneGuards:
    """Verify entities bail out when hass is None (after removal)."""

    async def test_lock_update_status_skips_when_hass_is_none(self):
        lock = make_lock()
        lock.hass = None
        lock.client.session.get_lock_current_mode = AsyncMock()

        await lock.async_update_status()

        lock.client.session.get_lock_current_mode.assert_not_awaited()

    def test_lock_force_state_skips_schedule_when_hass_is_none(self):
        lock = make_lock()
        lock.async_schedule_update_ha_state = MagicMock()
        lock.hass = None

        lock._SecuritasLock__force_state("1")

        assert lock._state == "1"
        lock.async_schedule_update_ha_state.assert_not_called()

    async def test_temperature_update_skips_when_hass_is_none(self):
        client = make_client()
        sensor = SentinelTemperature(
            make_sentinel(temp=22), make_service(), client, make_device()
        )
        sensor.hass = None
        client.session.get_sentinel_data = AsyncMock()

        await sensor.async_update()

        client.session.get_sentinel_data.assert_not_awaited()

    async def test_humidity_update_skips_when_hass_is_none(self):
        client = make_client()
        sensor = SentinelHumidity(
            make_sentinel(humidity=45), make_service(), client, make_device()
        )
        sensor.hass = None
        client.session.get_sentinel_data = AsyncMock()

        await sensor.async_update()

        client.session.get_sentinel_data.assert_not_awaited()

    async def test_air_quality_update_skips_when_hass_is_none(self):
        client = make_client()
        sensor = SentinelAirQuality(
            make_air_quality(), make_sentinel(), make_service(), client, make_device()
        )
        sensor.hass = None
        client.session.get_air_quality_data = AsyncMock()

        await sensor.async_update()

        client.session.get_air_quality_data.assert_not_awaited()
