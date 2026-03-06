"""Tests for custom_components/securitas/__init__.py."""

from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
)
from homeassistant.components.http import StaticPathConfig
from homeassistant.exceptions import ConfigEntryNotReady

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.securitas import (
    CONF_CHECK_ALARM_PANEL,
    CONF_CODE_ARM_REQUIRED,
    CONF_COUNTRY,
    CONF_DELAY_CHECK_OPERATION,
    CONF_DEVICE_INDIGITALL,
    CONF_INSTALLATION_KEY,
    CONF_MAP_AWAY,
    CONF_MAP_CUSTOM,
    CONF_MAP_HOME,
    CONF_MAP_NIGHT,
    CONF_MAP_VACATION,
    CONF_NOTIFY_GROUP,
    CONF_PERI_ALARM,
    CONF_USE_2FA,
    DOMAIN,
    PLATFORMS,
    SecuritasDirectDevice,
    SecuritasHub,
    _notify_error,
    add_device_information,
    async_setup_entry,
    async_unload_entry,
    async_update_options,
)
from custom_components.securitas.securitas_direct_new_api.const import (
    PERI_DEFAULTS,
    STD_DEFAULTS,
)
from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    CheckAlarmStatus,
    SStatus,
)
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    Login2FAError,
    LoginError,
    SecuritasDirectError,
)

from tests.conftest import (
    make_config_entry_data,
    make_installation,
    make_securitas_hub_mock,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helper: patch SecuritasHub preserving __name__
# ---------------------------------------------------------------------------


def _patch_hub(mock_hub):
    """Patch SecuritasHub constructor to return mock_hub while preserving __name__.

    The production code accesses SecuritasHub.__name__ (line 239), so the
    replacement object must expose that attribute.
    """
    mock_cls = MagicMock(return_value=mock_hub)
    mock_cls.__name__ = "SecuritasHub"
    return patch("custom_components.securitas.SecuritasHub", mock_cls)


# ===========================================================================
# 1. TestAddDeviceInformation
# ===========================================================================


class TestAddDeviceInformation:
    """Tests for add_device_information() pure function."""

    def test_generates_device_id_when_missing(self):
        """Should generate a device_id when not present in config."""
        config = OrderedDict({CONF_COUNTRY: "ES"})
        result = add_device_information(config)
        assert CONF_DEVICE_ID in result
        assert isinstance(result[CONF_DEVICE_ID], str)
        assert len(result[CONF_DEVICE_ID]) > 0

    def test_generates_unique_id_when_missing(self):
        """Should generate a unique_id when not present in config."""
        config = OrderedDict({CONF_COUNTRY: "ES"})
        result = add_device_information(config)
        assert CONF_UNIQUE_ID in result
        assert isinstance(result[CONF_UNIQUE_ID], str)
        assert len(result[CONF_UNIQUE_ID]) > 0

    def test_generates_indigitall_when_missing(self):
        """Should generate an indigitall device id when not present."""
        config = OrderedDict({CONF_COUNTRY: "ES"})
        result = add_device_information(config)
        assert CONF_DEVICE_INDIGITALL in result
        assert isinstance(result[CONF_DEVICE_INDIGITALL], str)
        # UUID4 has hyphens and is 36 chars
        assert len(result[CONF_DEVICE_INDIGITALL]) == 36

    def test_preserves_existing_values(self):
        """Should not overwrite existing device_id, unique_id, indigitall."""
        config = OrderedDict(
            {
                CONF_COUNTRY: "ES",
                CONF_DEVICE_ID: "my-device-id",
                CONF_UNIQUE_ID: "my-unique-id",
                CONF_DEVICE_INDIGITALL: "my-indigitall",
            }
        )
        result = add_device_information(config)
        assert result[CONF_DEVICE_ID] == "my-device-id"
        assert result[CONF_UNIQUE_ID] == "my-unique-id"
        assert result[CONF_DEVICE_INDIGITALL] == "my-indigitall"


# ===========================================================================
# 2. TestNotifyError
# ===========================================================================


class TestNotifyError:
    """Tests for _notify_error() helper."""

    def test_creates_persistent_notification(self):
        """Should call persistent_notification.create with correct data."""
        hass = MagicMock()
        hass.async_create_task = MagicMock()
        _notify_error(hass, "test_id", "Test Title", "Test message")
        hass.async_create_task.assert_called_once()
        # Verify async_call was invoked correctly
        hass.services.async_call.assert_called_once_with(
            domain="persistent_notification",
            service="create",
            service_data={
                "title": "Test Title",
                "message": "Test message",
                "notification_id": f"{DOMAIN}.test_id",
            },
        )

    def test_notification_id_includes_domain(self):
        """notification_id should be prefixed with the integration domain."""
        hass = MagicMock()
        hass.async_create_task = MagicMock()
        _notify_error(hass, "my_error", "Title", "Msg")
        # async_call is called with keyword args for service_data
        call_args = hass.services.async_call.call_args
        service_data = call_args[1].get(
            "service_data", call_args[0][2] if len(call_args[0]) > 2 else None
        )
        assert service_data["notification_id"] == f"{DOMAIN}.my_error"


# ===========================================================================
# 3. TestSecuritasDirectDevice
# ===========================================================================


class TestSecuritasDirectDevice:
    """Tests for the SecuritasDirectDevice wrapper class."""

    def _make_device(self, **overrides) -> SecuritasDirectDevice:
        installation = make_installation(**overrides)
        return SecuritasDirectDevice(installation)

    def test_available_returns_true(self):
        """Device should always report as available."""
        device = self._make_device()
        assert device.available is True

    def test_device_id_returns_installation_number(self):
        """device_id should return the installation number."""
        device = self._make_device(number="999888")
        assert device.device_id == "999888"

    def test_address_returns_installation_address(self):
        """address should return the installation address."""
        device = self._make_device(address="42 Elm Street")
        assert device.address == "42 Elm Street"

    def test_city_returns_installation_city(self):
        """city should return the installation city."""
        device = self._make_device(city="Barcelona")
        assert device.city == "Barcelona"

    def test_postal_code_returns_installation_postal_code(self):
        """postal_code should return the installation postalCode."""
        device = self._make_device(postalCode="08001")
        assert device.postal_code == "08001"

    def test_device_info_structure(self):
        """device_info should return a valid DeviceInfo dict."""
        device = self._make_device(alias="MyHome", type="PREMIUM", panel="SDVFAST")
        info = device.device_info
        assert info["identifiers"] == {(DOMAIN, "MyHome")}
        assert info["manufacturer"] == "Securitas Direct"
        assert info["model"] == "PREMIUM"
        assert info["hw_version"] == "SDVFAST"
        assert info["name"] == "MyHome"


# ===========================================================================
# 4. TestSecuritasHub
# ===========================================================================


class TestSecuritasHub:
    """Tests for the SecuritasHub wrapper class."""

    def _make_config(self, **overrides) -> OrderedDict:
        """Build a minimal config OrderedDict for SecuritasHub."""
        config = OrderedDict(
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "test-password",
                CONF_COUNTRY: "ES",
                CONF_CHECK_ALARM_PANEL: True,
                CONF_DEVICE_ID: "test-device-id",
                CONF_UNIQUE_ID: "test-uuid",
                CONF_DEVICE_INDIGITALL: "test-indigitall",
                CONF_DELAY_CHECK_OPERATION: 2,
                CONF_SCAN_INTERVAL: 120,
                CONF_CODE: "",
                CONF_PERI_ALARM: False,
                CONF_CODE_ARM_REQUIRED: False,
                CONF_USE_2FA: True,
            }
        )
        config.update(overrides)
        return config

    def _make_hub(self, config=None, **config_overrides) -> SecuritasHub:
        """Create a SecuritasHub with mocked dependencies."""
        if config is None:
            config = self._make_config(**config_overrides)
        return SecuritasHub(config, MagicMock(), MagicMock(), MagicMock())

    def test_init_creates_api_manager(self):
        """Constructor should create an ApiManager session."""
        hub = self._make_hub()
        assert hub.session is not None
        assert hub.config[CONF_USERNAME] == "test@example.com"
        assert hub.country == "ES"
        assert hub.check_alarm is True

    def test_init_stores_config(self):
        """Constructor should store the domain config."""
        config = self._make_config()
        hub = SecuritasHub(config, MagicMock(), MagicMock(), MagicMock())
        assert hub.config is config

    async def test_login_delegates_to_session(self):
        """login() should delegate to session.login()."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        await hub.login()
        hub.session.login.assert_awaited_once()

    async def test_validate_device_delegates(self):
        """validate_device() should delegate to session.validate_device()."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        hub.session.validate_device = AsyncMock(return_value=("hash", []))
        result = await hub.validate_device()
        hub.session.validate_device.assert_awaited_once_with(False, "", "")
        assert result == ("hash", [])

    async def test_send_sms_code_delegates(self):
        """send_sms_code() should delegate to session.validate_device() with correct args."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        hub.session.validate_device = AsyncMock(return_value=("hash", []))
        await hub.send_sms_code("otp-hash", "123456")
        hub.session.validate_device.assert_awaited_once_with(True, "otp-hash", "123456")

    async def test_refresh_token_delegates(self):
        """refresh_token() should delegate to session.refresh_token()."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        hub.session.refresh_token = AsyncMock(return_value=True)
        result = await hub.refresh_token()
        hub.session.refresh_token.assert_awaited_once()
        assert result is True

    async def test_get_services_delegates(self):
        """get_services() should delegate to session.get_all_services()."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        hub.session.get_all_services = AsyncMock(return_value=[])
        inst = make_installation()
        result = await hub.get_services(inst)
        hub.session.get_all_services.assert_awaited_once_with(inst)
        assert result == []

    async def test_logout_returns_false_on_failure(self):
        """logout() should return False when session.logout() returns falsy."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        hub.session.logout = AsyncMock(return_value=False)
        result = await hub.logout()
        assert result is False

    async def test_logout_returns_true_on_success(self):
        """logout() should return True when session.logout() returns truthy."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        hub.session.logout = AsyncMock(return_value=True)
        result = await hub.logout()
        assert result is True

    def test_get_set_authentication_token(self):
        """get/set_authentication_token should read/write session.authentication_token."""
        hub = self._make_hub()
        hub.session = MagicMock()
        hub.session.authentication_token = "original-token"
        assert hub.get_authentication_token() == "original-token"
        hub.set_authentication_token("new-token")
        assert hub.session.authentication_token == "new-token"

    async def test_update_overview_check_alarm_true(self):
        """update_overview with check_alarm=True should use check_alarm + check_alarm_status."""
        hub = self._make_hub(**{CONF_CHECK_ALARM_PANEL: True})
        hub.session = AsyncMock()
        hub.session.check_alarm = AsyncMock(return_value="ref-123")
        expected_status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="armed",
            InstallationNumer="123456",
            protomResponse="T",
            protomResponseData="",
        )
        hub.session.check_alarm_status = AsyncMock(return_value=expected_status)
        inst = make_installation()

        with patch("custom_components.securitas.asyncio.sleep", new_callable=AsyncMock):
            result = await hub.update_overview(inst)

        hub.session.check_alarm.assert_awaited_once_with(inst)
        hub.session.check_alarm_status.assert_awaited_once()
        assert result == expected_status

    async def test_update_overview_check_alarm_false(self):
        """update_overview with check_alarm=False should use check_general_status."""
        hub = self._make_hub(**{CONF_CHECK_ALARM_PANEL: False})
        hub.session = AsyncMock()
        hub.session.check_general_status = AsyncMock(
            return_value=SStatus(status="armed", timestampUpdate="2024-01-01")
        )
        inst = make_installation()
        result = await hub.update_overview(inst)
        hub.session.check_general_status.assert_awaited_once_with(inst)
        assert result.status == "armed"
        assert result.InstallationNumer == inst.number

    async def test_update_overview_reraises_403_check_alarm(self):
        """update_overview re-raises 403 errors from check_alarm_status."""
        hub = self._make_hub(**{CONF_CHECK_ALARM_PANEL: True})
        hub.session = AsyncMock()
        hub.session.check_alarm = AsyncMock(return_value="ref-123")
        hub.session.check_alarm_status = AsyncMock(
            side_effect=SecuritasDirectError("HTTP 403", http_status=403)
        )
        inst = make_installation()

        with pytest.raises(SecuritasDirectError) as exc_info:
            with patch(
                "custom_components.securitas.asyncio.sleep", new_callable=AsyncMock
            ):
                await hub.update_overview(inst)
        assert exc_info.value.http_status == 403

    async def test_update_overview_reraises_403_general_status(self):
        """update_overview re-raises 403 from check_general_status."""
        hub = self._make_hub(**{CONF_CHECK_ALARM_PANEL: False})
        hub.session = AsyncMock()
        hub.session.check_general_status = AsyncMock(
            side_effect=SecuritasDirectError("HTTP 403", http_status=403)
        )
        inst = make_installation()

        with pytest.raises(SecuritasDirectError) as exc_info:
            await hub.update_overview(inst)
        assert exc_info.value.http_status == 403

    async def test_update_overview_swallows_non_403_error(self):
        """update_overview swallows non-403 errors and returns empty status."""
        hub = self._make_hub(**{CONF_CHECK_ALARM_PANEL: True})
        hub.session = AsyncMock()
        hub.session.check_alarm = AsyncMock(
            side_effect=SecuritasDirectError("Network error")
        )
        inst = make_installation()

        with patch("custom_components.securitas.asyncio.sleep", new_callable=AsyncMock):
            result = await hub.update_overview(inst)
        # Should return empty CheckAlarmStatus, not raise
        assert not result.protomResponse

    async def test_update_overview_cooldown_between_calls(self):
        """update_overview waits if called too soon after previous API call."""
        hub = self._make_hub(**{CONF_CHECK_ALARM_PANEL: True})
        hub.session = AsyncMock()
        hub.session.check_alarm = AsyncMock(return_value="ref-123")
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="D",
            protomResponseData="",
        )
        hub.session.check_alarm_status = AsyncMock(return_value=status)
        inst = make_installation()

        import time

        # Simulate recent API call
        hub._last_api_time = time.monotonic()

        with patch(
            "custom_components.securitas.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            await hub.update_overview(inst)

        # asyncio.sleep should have been called for the cooldown
        # (once for cooldown, once for poll delay)
        assert mock_sleep.call_count >= 2

    async def test_update_overview_updates_last_api_time(self):
        """update_overview updates _last_api_time after API calls."""
        hub = self._make_hub(**{CONF_CHECK_ALARM_PANEL: True})
        hub.session = AsyncMock()
        hub.session.check_alarm = AsyncMock(return_value="ref-123")
        status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="D",
            protomResponseData="",
        )
        hub.session.check_alarm_status = AsyncMock(return_value=status)
        inst = make_installation()

        assert hub._last_api_time == 0

        with patch("custom_components.securitas.asyncio.sleep", new_callable=AsyncMock):
            await hub.update_overview(inst)

        assert hub._last_api_time > 0


# ===========================================================================
# 5. TestAsyncSetupEntry
# ===========================================================================


class TestAsyncSetupEntry:
    """Tests for async_setup_entry()."""

    @pytest.fixture
    def mock_hub(self):
        """Create a mock SecuritasHub for setup tests."""
        hub = make_securitas_hub_mock()
        hub.session.list_installations = AsyncMock(return_value=[make_installation()])
        return hub

    async def test_setup_success(self, hass, mock_hub):
        """Successful setup should login, list installations, forward platforms, return True."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True
        mock_hub.login.assert_awaited_once()
        mock_hub.session.list_installations.assert_awaited_once()
        assert DOMAIN in hass.data
        assert CONF_INSTALLATION_KEY in hass.data[DOMAIN]

    async def test_setup_login_2fa_error(self, hass, mock_hub):
        """Login2FAError should return False and create a notification."""
        mock_hub.login = AsyncMock(side_effect=Login2FAError("2FA required"))
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch("custom_components.securitas._notify_error") as mock_notify,
            patch.object(
                hass.config_entries.flow, "async_init", new_callable=AsyncMock
            ),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is False
        mock_notify.assert_called_once()
        assert mock_notify.call_args[0][1] == "2fa_error"

    async def test_setup_login_error(self, hass, mock_hub):
        """LoginError should return False and create a notification."""
        mock_hub.login = AsyncMock(side_effect=LoginError("bad credentials"))
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch("custom_components.securitas._notify_error") as mock_notify,
            patch.object(
                hass.config_entries.flow, "async_init", new_callable=AsyncMock
            ),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is False
        mock_notify.assert_called_once()
        assert mock_notify.call_args[0][1] == "login_error"

    async def test_setup_securitas_error_during_login(self, hass, mock_hub):
        """SecuritasDirectError during login should raise ConfigEntryNotReady."""
        mock_hub.login = AsyncMock(
            side_effect=SecuritasDirectError("connection failed")
        )
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

    async def test_setup_securitas_error_during_list_installations(
        self, hass, mock_hub
    ):
        """SecuritasDirectError during list_installations should raise ConfigEntryNotReady."""
        mock_hub.session.list_installations = AsyncMock(
            side_effect=SecuritasDirectError("network error")
        )
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

    async def test_setup_securitas_error_during_get_services(self, hass, mock_hub):
        """SecuritasDirectError during get_services should raise ConfigEntryNotReady."""
        mock_hub.get_services = AsyncMock(
            side_effect=SecuritasDirectError("service error")
        )
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

    async def test_setup_missing_device_id_triggers_sign_in(self, hass):
        """Missing CONF_DEVICE_ID should trigger need_sign_in path and return False."""
        data = make_config_entry_data()
        del data[CONF_DEVICE_ID]
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries.flow, "async_init", new_callable=AsyncMock
        ):
            result = await async_setup_entry(hass, entry)
        assert result is False

    async def test_setup_missing_unique_id_triggers_sign_in(self, hass):
        """Missing CONF_UNIQUE_ID should trigger need_sign_in path and return False."""
        data = make_config_entry_data()
        del data[CONF_UNIQUE_ID]
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries.flow, "async_init", new_callable=AsyncMock
        ):
            result = await async_setup_entry(hass, entry)
        assert result is False

    async def test_setup_missing_indigitall_triggers_sign_in(self, hass):
        """Missing CONF_DEVICE_INDIGITALL should trigger need_sign_in path and return False."""
        data = make_config_entry_data()
        del data[CONF_DEVICE_INDIGITALL]
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries.flow, "async_init", new_callable=AsyncMock
        ):
            result = await async_setup_entry(hass, entry)
        assert result is False

    async def test_setup_stores_hub_in_hass_data(self, hass, mock_hub):
        """After successful setup, SecuritasHub should be stored in hass.data."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            await async_setup_entry(hass, entry)

        assert hass.data[DOMAIN][SecuritasHub.__name__] is mock_hub

    async def test_setup_stores_devices_in_hass_data(self, hass, mock_hub):
        """After successful setup, devices list should be in hass.data."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            await async_setup_entry(hass, entry)

        devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
        assert len(devices) == 1
        assert isinstance(devices[0], SecuritasDirectDevice)

    async def test_setup_mapping_migration_std(self, hass, mock_hub):
        """When map_home is None, STD defaults should be applied (peri_alarm=False)."""
        data = make_config_entry_data()
        # Remove mapping keys to trigger migration
        data[CONF_MAP_HOME] = None
        data[CONF_MAP_AWAY] = None
        data[CONF_MAP_NIGHT] = None
        data[CONF_MAP_CUSTOM] = None
        data[CONF_MAP_VACATION] = None
        data[CONF_PERI_ALARM] = False
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            await async_setup_entry(hass, entry)

        # After migration, entry data should have STD defaults
        assert entry.data[CONF_MAP_HOME] == STD_DEFAULTS[CONF_MAP_HOME]
        assert entry.data[CONF_MAP_AWAY] == STD_DEFAULTS[CONF_MAP_AWAY]
        assert entry.data[CONF_MAP_VACATION] == STD_DEFAULTS[CONF_MAP_VACATION]

    async def test_setup_mapping_migration_peri(self, hass, mock_hub):
        """When map_home is None with peri_alarm=True, PERI defaults should be applied."""
        data = make_config_entry_data()
        data[CONF_MAP_HOME] = None
        data[CONF_MAP_AWAY] = None
        data[CONF_MAP_NIGHT] = None
        data[CONF_MAP_CUSTOM] = None
        data[CONF_MAP_VACATION] = None
        data[CONF_PERI_ALARM] = True
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            await async_setup_entry(hass, entry)

        assert entry.data[CONF_MAP_HOME] == PERI_DEFAULTS[CONF_MAP_HOME]
        assert entry.data[CONF_MAP_AWAY] == PERI_DEFAULTS[CONF_MAP_AWAY]
        assert entry.data[CONF_MAP_VACATION] == PERI_DEFAULTS[CONF_MAP_VACATION]

    async def test_setup_no_migration_when_maps_present(self, hass, mock_hub):
        """When map_home already has a value, no migration should happen."""
        data = make_config_entry_data()
        # Make sure maps have values (they do by default from make_config_entry_data)
        assert data[CONF_MAP_HOME] is not None
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            await async_setup_entry(hass, entry)

        # data should remain as it was
        assert entry.data[CONF_MAP_HOME] == STD_DEFAULTS[CONF_MAP_HOME]

    async def test_setup_forwards_platforms(self, hass, mock_hub):
        """Successful setup should forward all PLATFORMS."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ) as mock_forward,
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True
        mock_forward.assert_awaited_once_with(entry, PLATFORMS)

    async def test_setup_registers_static_path_and_extra_js(self, hass, mock_hub):
        """Successful setup should register the alarm card static path and JS URL."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        # Make hass.http truthy with an async_register_static_paths mock
        hass.http = MagicMock()
        hass.http.async_register_static_paths = AsyncMock()

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.securitas.frontend.add_extra_js_url"
            ) as mock_add_js,
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True

        # Verify static path registration
        hass.http.async_register_static_paths.assert_awaited_once()
        call_args = hass.http.async_register_static_paths.call_args[0][0]
        assert len(call_args) == 1
        assert isinstance(call_args[0], StaticPathConfig)
        assert call_args[0].url_path == "/securitas_panel"

        # Verify extra JS URL registration (includes version cache-buster)
        mock_add_js.assert_called_once()
        js_url = mock_add_js.call_args[0][1]
        assert js_url.startswith("/securitas_panel/securitas-alarm-card.js?v=")

    async def test_setup_skips_card_when_no_http(self, hass, mock_hub):
        """When hass.http is None, neither static paths nor extra JS should be registered."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        hass.http = None

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.securitas.frontend.add_extra_js_url"
            ) as mock_add_js,
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True
        mock_add_js.assert_not_called()

    async def test_setup_card_registration_idempotent(self, hass, mock_hub):
        """Calling async_setup_entry twice should only register card JS once."""
        # Make hass.http truthy with an async_register_static_paths mock
        hass.http = MagicMock()
        hass.http.async_register_static_paths = AsyncMock()

        entry1 = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry1.add_to_hass(hass)

        entry2 = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry2.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.securitas.frontend.add_extra_js_url"
            ) as mock_add_js,
        ):
            result1 = await async_setup_entry(hass, entry1)
            result2 = await async_setup_entry(hass, entry2)

        assert result1 is True
        assert result2 is True
        # Card registered only once (guarded by card_registered flag)
        mock_add_js.assert_called_once()
        js_url = mock_add_js.call_args[0][1]
        assert js_url.startswith("/securitas_panel/securitas-alarm-card.js?v=")


# ===========================================================================
# 6. TestAsyncUpdateOptions
# ===========================================================================


class TestAsyncUpdateOptions:
    """Tests for async_update_options()."""

    async def test_reload_when_options_differ(self, hass):
        """Should reload when options differ from data."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=make_config_entry_data(scan_interval=120),
            options={CONF_SCAN_INTERVAL: 300},
        )
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
        ) as mock_reload:
            await async_update_options(hass, entry)
            mock_reload.assert_awaited_once_with(entry.entry_id)

    async def test_no_reload_when_options_same(self, hass):
        """Should not reload when options match data."""
        data = make_config_entry_data()
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            options={
                CONF_CODE: data[CONF_CODE],
                CONF_CODE_ARM_REQUIRED: data[CONF_CODE_ARM_REQUIRED],
                CONF_SCAN_INTERVAL: data[CONF_SCAN_INTERVAL],
                CONF_CHECK_ALARM_PANEL: data[CONF_CHECK_ALARM_PANEL],
                CONF_PERI_ALARM: data[CONF_PERI_ALARM],
                CONF_MAP_HOME: data[CONF_MAP_HOME],
                CONF_MAP_AWAY: data[CONF_MAP_AWAY],
                CONF_MAP_NIGHT: data[CONF_MAP_NIGHT],
                CONF_MAP_CUSTOM: data[CONF_MAP_CUSTOM],
                CONF_MAP_VACATION: data[CONF_MAP_VACATION],
                CONF_NOTIFY_GROUP: "",
            },
        )
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
        ) as mock_reload:
            await async_update_options(hass, entry)
            mock_reload.assert_not_awaited()

    async def test_reload_when_notify_group_changes(self, hass):
        """Should reload when only notify_group changes."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=make_config_entry_data(),
            options={CONF_NOTIFY_GROUP: "notify.mobile_app"},
        )
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
        ) as mock_reload:
            await async_update_options(hass, entry)
            mock_reload.assert_awaited_once_with(entry.entry_id)

    async def test_reload_when_map_vacation_changes(self, hass):
        """Should reload when map_vacation option changes."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=make_config_entry_data(),
            options={CONF_MAP_VACATION: "total"},
        )
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
        ) as mock_reload:
            await async_update_options(hass, entry)
            mock_reload.assert_awaited_once_with(entry.entry_id)

    async def test_reload_when_code_changes(self, hass):
        """Should reload when just the code option changes."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=make_config_entry_data(code=""),
            options={CONF_CODE: "1234"},
        )
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
        ) as mock_reload:
            await async_update_options(hass, entry)
            mock_reload.assert_awaited_once_with(entry.entry_id)


# ===========================================================================
# 7. TestAsyncUnloadEntry
# ===========================================================================


class TestAsyncUnloadEntry:
    """Tests for async_unload_entry()."""

    async def test_unload_success(self, hass):
        """Unload should unload platforms and clean hass.data."""
        hub = make_securitas_hub_mock()
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        # Pre-populate hass.data as async_setup_entry would
        hass.data[DOMAIN] = {
            entry.entry_id: hub,
            "other_key": "other_value",
        }

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_unload:
            result = await async_unload_entry(hass, entry)

        assert result is True
        mock_unload.assert_awaited_once_with(entry, PLATFORMS)
        # entry_id key should be removed
        assert entry.entry_id not in hass.data[DOMAIN]
        # DOMAIN should still be in hass.data because other_key remains
        assert DOMAIN in hass.data

    async def test_unload_removes_domain_when_empty(self, hass):
        """When the last entry is unloaded, DOMAIN should be removed from hass.data."""
        hub = make_securitas_hub_mock()
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        # Only one key in domain data
        hass.data[DOMAIN] = {
            entry.entry_id: hub,
        }

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await async_unload_entry(hass, entry)

        assert DOMAIN not in hass.data
