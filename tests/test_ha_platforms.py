"""Tests for sensor and lock platform entities."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    AirQuality,
    Attribute,
    Attributes,
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
    AirQualityFetcher,
    SentinelAirQuality,
    SentinelAirQualityStatus,
    SentinelHumidity,
    SentinelTemperature,
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
        alias="Living", air_quality="2", humidity=humidity, temperature=temp
    )


def make_client():
    """Create a mock SecuritasHub client."""
    client = MagicMock()
    client.session = AsyncMock()
    client.config = {"scan_interval": 120}
    client.lang = "es"
    return client


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
            returns an empty list (so ``get_lock_state`` returns UNKNOWN
            and the optimistic fallback is used).
    """
    installation = make_installation()
    client = MagicMock()
    client.config = {"scan_interval": 120}
    client.session = AsyncMock()
    client.change_lock_mode = AsyncMock()
    if poll_status is not None:
        client.get_lock_modes = AsyncMock(
            return_value=[SmartLockMode(lockStatus=poll_status, deviceId=device_id)]
        )
    else:
        client.get_lock_modes = AsyncMock(return_value=[])
    hass = MagicMock()
    hass.async_create_task = MagicMock()
    hass.services = MagicMock()

    lock_entity = SecuritasLock(
        installation=installation,
        client=client,
        hass=hass,
        device_id=device_id,
        initial_status=initial_status,
        lock_config=lock_config,
    )
    lock_entity.entity_id = f"lock.securitas_{installation.number}_{device_id}"
    # Mock HA state-writing methods (no platform registered in unit tests)
    lock_entity.async_write_ha_state = MagicMock()
    lock_entity.async_schedule_update_ha_state = MagicMock()
    return lock_entity


# ===========================================================================
# SentinelTemperature tests
# ===========================================================================


class TestSentinelTemperature:
    """Tests for SentinelTemperature sensor entity."""

    def test_init_starts_with_no_value(self):
        sensor = SentinelTemperature(make_service(), make_client(), make_installation())
        assert sensor._attr_native_value is None

    def test_init_sets_device_class_to_temperature(self):
        from homeassistant.components.sensor import SensorDeviceClass

        sensor = SentinelTemperature(make_service(), make_client(), make_installation())
        assert sensor._attr_device_class == SensorDeviceClass.TEMPERATURE

    def test_init_sets_unit_to_celsius(self):
        from homeassistant.const import UnitOfTemperature

        sensor = SentinelTemperature(make_service(), make_client(), make_installation())
        assert sensor._attr_native_unit_of_measurement == UnitOfTemperature.CELSIUS

    async def test_async_update_fetches_sentinel_and_sets_temperature(self):
        client = make_client()
        service = make_service()
        installation = make_installation()
        sensor = SentinelTemperature(service, client, installation)
        sensor.hass = MagicMock()
        assert sensor._attr_native_value is None

        client.get_sentinel = AsyncMock(return_value=make_sentinel(temp=30))
        await sensor.async_update()

        client.get_sentinel.assert_awaited_once_with(installation, service)
        assert sensor._attr_native_value == 30

    async def test_async_update_handles_error_gracefully(self):
        client = make_client()
        sensor = SentinelTemperature(make_service(), client, make_installation())
        sensor.hass = MagicMock()

        client.get_sentinel = AsyncMock(side_effect=SecuritasDirectError("API error"))
        await sensor.async_update()

        assert sensor._attr_native_value is None

    def test_unique_id_contains_installation_number_and_service_id(self):
        service = make_service()
        installation = make_installation()
        sensor = SentinelTemperature(service, make_client(), installation)
        assert installation.number in sensor._attr_unique_id  # type: ignore[operator]
        assert str(service.id) in sensor._attr_unique_id  # type: ignore[operator]
        assert "temperature" in sensor._attr_unique_id  # type: ignore[operator]

    def test_name_contains_installation_alias(self):
        installation = make_installation()
        sensor = SentinelTemperature(make_service(), make_client(), installation)
        assert installation.alias in sensor._attr_name  # type: ignore[operator]
        assert "Temperature" in sensor._attr_name  # type: ignore[operator]


# ===========================================================================
# SentinelHumidity tests
# ===========================================================================


class TestSentinelHumidity:
    """Tests for SentinelHumidity sensor entity."""

    def test_init_starts_with_no_value(self):
        sensor = SentinelHumidity(make_service(), make_client(), make_installation())
        assert sensor._attr_native_value is None

    def test_init_sets_device_class_to_humidity(self):
        from homeassistant.components.sensor import SensorDeviceClass

        sensor = SentinelHumidity(make_service(), make_client(), make_installation())
        assert sensor._attr_device_class == SensorDeviceClass.HUMIDITY

    def test_init_sets_unit_to_percentage(self):
        from homeassistant.const import PERCENTAGE

        sensor = SentinelHumidity(make_service(), make_client(), make_installation())
        assert sensor._attr_native_unit_of_measurement == PERCENTAGE

    async def test_async_update_fetches_sentinel_and_sets_humidity(self):
        client = make_client()
        service = make_service()
        installation = make_installation()
        sensor = SentinelHumidity(service, client, installation)
        sensor.hass = MagicMock()

        client.get_sentinel = AsyncMock(return_value=make_sentinel(humidity=60))
        await sensor.async_update()

        client.get_sentinel.assert_awaited_once_with(installation, service)
        assert sensor._attr_native_value == 60

    async def test_async_update_handles_error_gracefully(self):
        client = make_client()
        sensor = SentinelHumidity(make_service(), client, make_installation())
        sensor.hass = MagicMock()

        client.get_sentinel = AsyncMock(side_effect=SecuritasDirectError("API error"))
        await sensor.async_update()

        assert sensor._attr_native_value is None

    def test_unique_id_contains_installation_number_and_service_id(self):
        service = make_service()
        installation = make_installation()
        sensor = SentinelHumidity(service, make_client(), installation)
        assert installation.number in sensor._attr_unique_id  # type: ignore[operator]
        assert str(service.id) in sensor._attr_unique_id  # type: ignore[operator]
        assert "humidity" in sensor._attr_unique_id  # type: ignore[operator]


# ===========================================================================
# AirQualityFetcher + SentinelAirQuality + SentinelAirQualityStatus tests
# ===========================================================================


def _mock_sentinel_with_zone(zone="JX01"):
    """Create a Sentinel with a device zone."""
    return Sentinel(
        alias="Living", air_quality="1", humidity=63, temperature=22, zone=zone
    )


def _make_fetcher(client=None, service=None, installation=None):
    """Create an AirQualityFetcher with mocked dependencies."""
    return AirQualityFetcher(
        service or make_service(),
        client or make_client(),
        installation or make_installation(),
    )


class TestAirQualityFetcher:
    """Tests for AirQualityFetcher — shared fetch for both entities."""

    async def test_fetch_returns_air_quality(self):
        client = make_client()
        client.get_sentinel = AsyncMock(return_value=_mock_sentinel_with_zone())
        client.get_air_quality = AsyncMock(
            return_value=AirQuality(value=122, status_current=1)
        )
        fetcher = _make_fetcher(client=client)
        result = await fetcher.fetch()
        assert result is not None
        assert result.value == 122
        assert result.status_current == 1

    async def test_fetch_returns_none_on_sentinel_error(self):
        client = make_client()
        client.get_sentinel = AsyncMock(side_effect=SecuritasDirectError("err"))
        fetcher = _make_fetcher(client=client)
        assert await fetcher.fetch() is None

    async def test_fetch_returns_none_on_air_quality_error(self):
        client = make_client()
        client.get_sentinel = AsyncMock(return_value=_mock_sentinel_with_zone())
        client.get_air_quality = AsyncMock(side_effect=SecuritasDirectError("err"))
        fetcher = _make_fetcher(client=client)
        assert await fetcher.fetch() is None

    async def test_fetch_returns_none_when_api_returns_none(self):
        client = make_client()
        client.get_sentinel = AsyncMock(return_value=_mock_sentinel_with_zone())
        client.get_air_quality = AsyncMock(return_value=None)
        fetcher = _make_fetcher(client=client)
        assert await fetcher.fetch() is None

    async def test_fetch_uses_zone_from_sentinel(self):
        client = make_client()
        installation = make_installation()
        client.get_sentinel = AsyncMock(
            return_value=_mock_sentinel_with_zone(zone="ZZ99")
        )
        client.get_air_quality = AsyncMock(
            return_value=AirQuality(value=10, status_current=1)
        )
        fetcher = _make_fetcher(client=client, installation=installation)
        await fetcher.fetch()
        client.get_air_quality.assert_awaited_once_with(installation, "ZZ99")


class TestSentinelAirQuality:
    """Tests for SentinelAirQuality numeric sensor."""

    def test_init_starts_with_no_value(self):
        fetcher = _make_fetcher()
        sensor = SentinelAirQuality(fetcher, make_installation())
        assert sensor._attr_native_value is None

    async def test_async_update_sets_value(self):
        client = make_client()
        client.get_sentinel = AsyncMock(return_value=_mock_sentinel_with_zone())
        client.get_air_quality = AsyncMock(
            return_value=AirQuality(value=122, status_current=1)
        )
        fetcher = _make_fetcher(client=client)
        sensor = SentinelAirQuality(fetcher, make_installation())
        sensor.hass = MagicMock()

        await sensor.async_update()
        assert sensor._attr_native_value == 122

    async def test_async_update_none_keeps_old_value(self):
        client = make_client()
        client.get_sentinel = AsyncMock(return_value=_mock_sentinel_with_zone())
        client.get_air_quality = AsyncMock(return_value=None)
        fetcher = _make_fetcher(client=client)
        sensor = SentinelAirQuality(fetcher, make_installation())
        sensor.hass = MagicMock()

        await sensor.async_update()
        assert sensor._attr_native_value is None

    def test_unique_id_contains_airquality(self):
        service = make_service()
        installation = make_installation()
        fetcher = _make_fetcher(service=service, installation=installation)
        sensor = SentinelAirQuality(fetcher, installation)
        assert installation.number in sensor._attr_unique_id  # type: ignore[operator]
        assert "airquality" in sensor._attr_unique_id  # type: ignore[operator]


class TestSentinelAirQualityStatus:
    """Tests for SentinelAirQualityStatus categorical sensor."""

    def test_init_starts_with_no_value(self):
        fetcher = _make_fetcher()
        sensor = SentinelAirQualityStatus(fetcher, make_installation())
        assert sensor._attr_native_value is None

    async def test_async_update_sets_status_label(self):
        client = make_client()
        client.get_sentinel = AsyncMock(return_value=_mock_sentinel_with_zone())
        client.get_air_quality = AsyncMock(
            return_value=AirQuality(value=122, status_current=1)
        )
        fetcher = _make_fetcher(client=client)
        sensor = SentinelAirQualityStatus(fetcher, make_installation())
        sensor.hass = MagicMock()

        await sensor.async_update()
        assert sensor._attr_native_value == "Good"

    async def test_status_poor(self):
        client = make_client()
        client.get_sentinel = AsyncMock(return_value=_mock_sentinel_with_zone())
        client.get_air_quality = AsyncMock(
            return_value=AirQuality(value=200, status_current=2)
        )
        fetcher = _make_fetcher(client=client)
        sensor = SentinelAirQualityStatus(fetcher, make_installation())
        sensor.hass = MagicMock()

        await sensor.async_update()
        assert sensor._attr_native_value == "Poor"

    async def test_unknown_status_code(self, caplog):
        """Unknown codes fall back to the raw code string and log a warning."""
        client = make_client()
        client.get_sentinel = AsyncMock(return_value=_mock_sentinel_with_zone())
        client.get_air_quality = AsyncMock(
            return_value=AirQuality(value=200, status_current=99)
        )
        fetcher = _make_fetcher(client=client)
        sensor = SentinelAirQualityStatus(fetcher, make_installation())
        sensor.hass = MagicMock()

        await sensor.async_update()
        assert sensor._attr_native_value == "99"
        assert "Unknown air quality status code '99'" in caplog.text

    def test_unique_id_contains_status(self):
        fetcher = _make_fetcher()
        sensor = SentinelAirQualityStatus(fetcher, make_installation())
        assert "airquality_status" in sensor._attr_unique_id  # type: ignore[operator]

    async def test_both_entities_use_same_fetcher(self):
        """Both numeric and status entities get consistent data."""
        client = make_client()
        client.get_sentinel = AsyncMock(return_value=_mock_sentinel_with_zone())
        client.get_air_quality = AsyncMock(
            return_value=AirQuality(value=92, status_current=1)
        )
        fetcher = _make_fetcher(client=client)
        numeric = SentinelAirQuality(fetcher, make_installation())
        status = SentinelAirQualityStatus(fetcher, make_installation())
        numeric.hass = MagicMock()
        status.hass = MagicMock()

        await numeric.async_update()
        await status.async_update()

        assert numeric._attr_native_value == 92
        assert status._attr_native_value == "Good"


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
            serialNumber="SN001",
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
                holdBackLatchTime=3,
                calibrationType=0,
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
            features=LockFeatures(holdBackLatchTime=3, calibrationType=0),
        )
        lock = make_lock(lock_config=lock_config)
        assert lock.supported_features == lock_mod.LockEntityFeature.OPEN

    def test_supported_features_holdback_zero_returns_zero(self):
        import homeassistant.components.lock as lock_mod

        lock_config = SmartLock(
            res="OK",
            features=LockFeatures(holdBackLatchTime=0, calibrationType=0),
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
        lock.client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_lock()

        # After successful lock, state comes from the fresh API poll ("2")
        assert lock._state == "2"
        # async_schedule_update_ha_state was called during _force_state("4")
        lock.async_schedule_update_ha_state.assert_called()  # type: ignore[attr-defined]
        # async_write_ha_state is called after successful state change
        lock.async_write_ha_state.assert_called()  # type: ignore[attr-defined]
        # get_lock_modes was called with FOREGROUND priority to fetch real status
        lock.client.get_lock_modes.assert_awaited_once_with(  # type: ignore[attr-defined]
            lock.installation, priority=ApiQueue.FOREGROUND
        )

    async def test_async_lock_uses_optimistic_state_when_poll_returns_unknown(self):
        lock = make_lock()  # no poll_status → get_lock_modes returns []
        lock.client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_lock()

        # Falls back to optimistic "2" (locked) when poll returns UNKNOWN
        assert lock._state == "2"

    async def test_async_unlock_sets_state_to_opening_then_open_on_success(self):
        lock = make_lock(poll_status="1")
        lock.client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_unlock()

        # After successful unlock, state comes from fresh API poll ("1")
        assert lock._state == "1"
        lock.async_schedule_update_ha_state.assert_called()  # type: ignore[attr-defined]
        lock.async_write_ha_state.assert_called()  # type: ignore[attr-defined]

    async def test_async_lock_error_restores_previous_state(self):
        lock = make_lock()
        lock.client.change_lock_mode = AsyncMock(
            side_effect=SecuritasDirectError("API error")
        )

        await lock.async_lock()

        # On error, state is restored from _last_state (initial "2" = locked)
        assert lock._state == "2"

    async def test_async_unlock_error_restores_previous_state(self):
        lock = make_lock()
        lock.client.change_lock_mode = AsyncMock(
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

        lock.client.change_lock_mode = AsyncMock(side_effect=capture_state)

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

        lock.client.change_lock_mode = AsyncMock(side_effect=capture_state)

        await lock.async_unlock()

        assert observed_states == ["3"]
        assert lock._state == "1"

    async def test_async_open_sets_state_to_opening_then_open_on_success(self):
        lock = make_lock(poll_status="1")
        lock.client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_open()

        assert lock._state == "1"
        lock.async_schedule_update_ha_state.assert_called()  # type: ignore[attr-defined]
        lock.async_write_ha_state.assert_called()  # type: ignore[attr-defined]

    async def test_async_open_error_restores_previous_state(self):
        lock = make_lock()
        lock.client.change_lock_mode = AsyncMock(
            side_effect=SecuritasDirectError("API error")
        )

        await lock.async_open()

        assert lock._state == "2"

    async def test_async_open_calls_change_lock_mode_with_false(self):
        lock = make_lock(poll_status="1")
        lock.client.change_lock_mode = AsyncMock(return_value=SmartLockModeStatus())

        await lock.async_open()

        lock.client.change_lock_mode.assert_awaited_once_with(
            lock.installation, False, "01"
        )

    async def test_async_open_intermediate_state_is_opening(self):
        """Verify _force_state is called with '3' (opening) before the API call."""
        lock = make_lock(poll_status="1")
        observed_states = []

        async def capture_state(installation, lock_mode, device_id=None):
            observed_states.append(lock._state)
            return SmartLockModeStatus()

        lock.client.change_lock_mode = AsyncMock(side_effect=capture_state)

        await lock.async_open()

        assert observed_states == ["3"]
        assert lock._state == "1"

    async def test_async_lock_stale_poll_trusts_api(self):
        """When API still returns pre-command state, we trust it."""
        # Lock starts open ("1"), we lock it, but the API still returns "1".
        # After the 6s wait the API should normally have the new state, but
        # if it doesn't, we trust what the API says rather than guess.
        lock = make_lock(initial_status="1", poll_status="1")
        lock.client.change_lock_mode = AsyncMock(return_value=None)

        await lock.async_lock()

        assert lock._state == "1"

    async def test_async_unlock_stale_poll_trusts_api(self):
        """When API still returns pre-command state, we trust it."""
        lock = make_lock(initial_status="2", poll_status="2")
        lock.client.change_lock_mode = AsyncMock(return_value=None)

        await lock.async_unlock()

        assert lock._state == "2"

    async def test_async_lock_confirmed_state_used_when_api_agrees(self):
        """When API returns the expected new state, it is used directly."""
        # Lock starts open ("1"), we lock it, API confirms "2"
        lock = make_lock(initial_status="1", poll_status="2")
        lock.client.change_lock_mode = AsyncMock(return_value=None)

        await lock.async_lock()

        # API returned "2" which differs from pre-command "1" → use it
        assert lock._state == "2"

    async def test_async_unlock_confirmed_state_used_when_api_agrees(self):
        """When API returns the expected new state, it is used directly."""
        # Lock starts locked ("2"), we unlock it, API confirms "1"
        lock = make_lock(initial_status="2", poll_status="1")
        lock.client.change_lock_mode = AsyncMock(return_value=None)

        await lock.async_unlock()

        # API returned "1" which differs from pre-command "2" → use it
        assert lock._state == "1"

    async def test_async_lock_poll_exception_uses_optimistic_state(self):
        """When get_lock_state raises, optimistic state is used."""
        lock = make_lock()
        lock.client.change_lock_mode = AsyncMock(return_value=None)
        lock.client.get_lock_modes = AsyncMock(side_effect=Exception("network error"))

        await lock.async_lock()

        # Exception → UNKNOWN → optimistic "2" (locked)
        assert lock._state == "2"


class TestSecuritasLockUpdateStatus:
    """Tests for SecuritasLock async_update_status."""

    async def test_async_update_status_updates_state_from_api(self):
        lock = make_lock()
        lock.client.get_lock_modes = AsyncMock(
            return_value=[SmartLockMode(res="OK", lockStatus="1", deviceId="01")]
        )

        await lock.async_update_status()

        assert lock._state == "1"

    async def test_async_update_status_ignores_zero_status(self):
        lock = make_lock()
        # Initial state is "2" (locked)
        assert lock._state == "2"

        lock.client.get_lock_modes = AsyncMock(
            return_value=[SmartLockMode(res="OK", lockStatus="0", deviceId="01")]
        )

        await lock.async_update_status()

        # State should remain "2" because "0" is ignored
        assert lock._state == "2"

    async def test_async_update_status_updates_on_non_zero(self):
        lock = make_lock()
        lock.client.get_lock_modes = AsyncMock(
            return_value=[SmartLockMode(res="OK", lockStatus="3", deviceId="01")]
        )

        await lock.async_update_status()

        assert lock._state == "3"

    async def test_async_update_status_ignores_other_device_ids(self):
        """Only status for the lock's own device_id is used."""
        lock = make_lock(device_id="01")
        lock.client.get_lock_modes = AsyncMock(
            return_value=[
                SmartLockMode(res="OK", lockStatus="1", deviceId="02"),
            ]
        )

        await lock.async_update_status()

        # No matching device_id → get_lock_state returns "0" (unknown) → ignored
        assert lock._state == "2"

    async def test_lock_config_with_holdback_gives_open_feature(self):
        """Lock created with holdBackLatchTime exposes OPEN feature."""
        import homeassistant.components.lock as lock_mod

        lock_config = SmartLock(
            res="OK",
            features=LockFeatures(holdBackLatchTime=3, calibrationType=0),
        )
        lock = make_lock(lock_config=lock_config)
        lock.client.get_lock_modes = AsyncMock(
            return_value=[SmartLockMode(lockStatus="2", deviceId="01")]
        )

        await lock.async_update_status()

        assert lock.supported_features == lock_mod.LockEntityFeature.OPEN

    async def test_async_update_delegates_to_update_status(self):
        """async_update just calls async_update_status."""
        lock = make_lock()
        lock.client.get_lock_modes = AsyncMock(
            return_value=[SmartLockMode(res="OK", lockStatus="1", deviceId="01")]
        )

        await lock.async_update()

        lock.client.get_lock_modes.assert_awaited_once()
        assert lock._state == "1"


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
        lock.hass = None  # type: ignore[attr-defined]
        lock.client.get_lock_modes = AsyncMock()

        await lock.async_update_status()

        lock.client.get_lock_modes.assert_not_awaited()

    def test_lock_force_state_skips_schedule_when_hass_is_none(self):
        lock = make_lock()
        lock.hass = None  # type: ignore[attr-defined]

        lock._force_state("1")

        assert lock._state == "1"
        lock.async_schedule_update_ha_state.assert_not_called()  # type: ignore[attr-defined]

    async def test_temperature_update_skips_when_hass_is_none(self):
        client = make_client()
        sensor = SentinelTemperature(make_service(), client, make_installation())
        sensor.hass = None  # type: ignore[attr-defined]
        client.get_sentinel = AsyncMock()

        await sensor.async_update()

        client.get_sentinel.assert_not_awaited()

    async def test_humidity_update_skips_when_hass_is_none(self):
        client = make_client()
        sensor = SentinelHumidity(make_service(), client, make_installation())
        sensor.hass = None  # type: ignore[attr-defined]
        client.get_sentinel = AsyncMock()

        await sensor.async_update()

        client.get_sentinel.assert_not_awaited()

    async def test_air_quality_update_skips_when_hass_is_none(self):
        client = make_client()
        fetcher = _make_fetcher(client=client)
        sensor = SentinelAirQuality(fetcher, make_installation())
        sensor.hass = None  # type: ignore[attr-defined]
        client.get_sentinel = AsyncMock()

        await sensor.async_update()

        client.get_sentinel.assert_not_awaited()
