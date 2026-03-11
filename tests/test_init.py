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
    CONF_CODE_ARM_REQUIRED,
    CONF_COUNTRY,
    CONF_DELAY_CHECK_OPERATION,
    CONF_DEVICE_INDIGITALL,
    CONF_INSTALLATION,
    CONF_MAP_AWAY,
    CONF_MAP_CUSTOM,
    CONF_MAP_HOME,
    CONF_MAP_NIGHT,
    CONF_MAP_VACATION,
    CONF_HAS_PERI,
    CONF_NOTIFY_GROUP,
    DOMAIN,
    PLATFORMS,
    SecuritasDirectDevice,
    SecuritasHub,
    _build_config_dict,
    _notify_error,
    add_device_information,
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
    async_update_options,
)
from custom_components.securitas.securitas_direct_new_api.const import (
    STD_DEFAULTS,
)
from custom_components.securitas.securitas_direct_new_api.dataTypes import (
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
# 1b. TestSecuritasHubInit — real constructor, catches missing config keys
# ===========================================================================


class TestSecuritasHubInit:
    """Verify SecuritasHub.__init__ works with config dicts from various sources."""

    def test_hub_init_with_config_entry_data(self, hass):
        """SecuritasHub.__init__ should accept make_config_entry_data() without KeyError."""
        config = make_config_entry_data()
        hub = SecuritasHub(config, None, MagicMock(), hass)
        assert hub.country == "ES"

    def test_hub_init_with_minimal_config_flow_config(self, hass):
        """SecuritasHub.__init__ should accept the config dict built by _create_client."""
        from custom_components.securitas import (
            DEFAULT_DELAY_CHECK_OPERATION,
        )

        # Simulate the config dict built by async_step_user before _create_client()
        config = OrderedDict(
            {
                CONF_COUNTRY: "ES",
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "test-password",
                CONF_DELAY_CHECK_OPERATION: DEFAULT_DELAY_CHECK_OPERATION,
                CONF_DEVICE_ID: "test-device-id",
                CONF_UNIQUE_ID: "test-uuid",
                CONF_DEVICE_INDIGITALL: "",
            }
        )
        hub = SecuritasHub(config, None, MagicMock(), hass)
        assert hub.country == "ES"


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
        assert info["identifiers"] == {(DOMAIN, "v4_securitas_direct.123456")}  # type: ignore[typeddict-item]
        assert info["manufacturer"] == "Securitas Direct"  # type: ignore[typeddict-item]
        assert info["model"] == "SDVFAST"  # type: ignore[typeddict-item]
        assert info["hw_version"] == "PREMIUM"  # type: ignore[typeddict-item]
        assert info["name"] == "MyHome"  # type: ignore[typeddict-item]


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
                CONF_DEVICE_ID: "test-device-id",
                CONF_UNIQUE_ID: "test-uuid",
                CONF_DEVICE_INDIGITALL: "test-indigitall",
                CONF_DELAY_CHECK_OPERATION: 2,
                CONF_SCAN_INTERVAL: 120,
                CONF_CODE: "",
                CONF_HAS_PERI: False,
                CONF_CODE_ARM_REQUIRED: False,
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

    async def test_update_overview_uses_general_status(self):
        """update_overview always uses check_general_status."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        hub.session.check_general_status = AsyncMock(
            return_value=SStatus(status="T", timestampUpdate="2024-01-01")
        )
        inst = make_installation()

        result = await hub.update_overview(inst)

        hub.session.check_general_status.assert_awaited_once_with(inst)
        assert result.protomResponse == "T"
        assert result.installation_number == inst.number

    async def test_update_overview_reraises_403(self):
        """update_overview re-raises 403 errors from check_general_status."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        hub.session.check_general_status = AsyncMock(
            side_effect=SecuritasDirectError("HTTP 403", http_status=403)
        )
        inst = make_installation()

        with pytest.raises(SecuritasDirectError) as exc_info:
            await hub.update_overview(inst)
        assert exc_info.value.http_status == 403
        # _last_api_time should still be updated even on 403 (for cooldown)
        assert hub._api_queue._last_api_time > 0

    async def test_update_overview_403_updates_last_api_time(self):
        """403 on check_general_status still updates _last_api_time for cooldown."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        hub.session.check_general_status = AsyncMock(
            side_effect=SecuritasDirectError("HTTP 403", http_status=403)
        )
        inst = make_installation()

        with pytest.raises(SecuritasDirectError):
            await hub.update_overview(inst)
        assert hub._api_queue._last_api_time > 0

    async def test_update_overview_swallows_non_403_error(self):
        """update_overview swallows non-403 errors and returns empty status."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        hub.session.check_general_status = AsyncMock(
            side_effect=SecuritasDirectError("Network error")
        )
        inst = make_installation()

        result = await hub.update_overview(inst)
        # Should return empty CheckAlarmStatus, not raise
        assert not result.protomResponse

    async def test_update_overview_cooldown_between_calls(self):
        """update_overview updates _api_queue._last_api_time after API calls."""
        hub = self._make_hub()
        hub.session = AsyncMock()
        hub.session.check_general_status = AsyncMock(
            return_value=SStatus(status="D", timestampUpdate="2024-01-01")
        )
        inst = make_installation()

        assert hub._api_queue._last_api_time == 0
        await hub.update_overview(inst)
        # The queue should have updated _last_api_time
        assert hub._api_queue._last_api_time > 0


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
        assert entry.entry_id in hass.data[DOMAIN]
        assert "hub" in hass.data[DOMAIN][entry.entry_id]
        assert "devices" in hass.data[DOMAIN][entry.entry_id]

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

    async def test_setup_missing_device_id_raises_not_ready(self, hass):
        """Missing CONF_DEVICE_ID should raise ConfigEntryNotReady."""
        data = make_config_entry_data()
        del data[CONF_DEVICE_ID]
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)

    async def test_setup_missing_unique_id_raises_not_ready(self, hass):
        """Missing CONF_UNIQUE_ID should raise ConfigEntryNotReady."""
        data = make_config_entry_data()
        del data[CONF_UNIQUE_ID]
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)

    async def test_setup_missing_indigitall_raises_not_ready(self, hass):
        """Missing CONF_DEVICE_INDIGITALL should raise ConfigEntryNotReady."""
        data = make_config_entry_data()
        del data[CONF_DEVICE_INDIGITALL]
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)

    async def test_setup_stores_hub_in_hass_data(self, hass, mock_hub):
        """After successful setup, SecuritasHub should be stored in per-entry data."""
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

        assert hass.data[DOMAIN][entry.entry_id]["hub"] is mock_hub

    async def test_setup_stores_devices_in_hass_data(self, hass, mock_hub):
        """After successful setup, devices list should be in per-entry data."""
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

        devices = hass.data[DOMAIN][entry.entry_id]["devices"]
        assert len(devices) == 1
        assert isinstance(devices[0], SecuritasDirectDevice)

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

        # Verify both card JS URLs are registered (alarm card + camera card)
        assert mock_add_js.call_count == 2
        js_urls = [call[0][1] for call in mock_add_js.call_args_list]
        assert any(
            u.startswith("/securitas_panel/securitas-alarm-card.js?v=") for u in js_urls
        )
        assert any(
            u.startswith("/securitas_panel/securitas-camera-card.js?v=")
            for u in js_urls
        )

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
        # Both cards registered exactly once despite two setup calls (guarded by card_registered flag)
        assert mock_add_js.call_count == 2
        js_urls = [call[0][1] for call in mock_add_js.call_args_list]
        assert any(
            u.startswith("/securitas_panel/securitas-alarm-card.js?v=") for u in js_urls
        )
        assert any(
            u.startswith("/securitas_panel/securitas-camera-card.js?v=")
            for u in js_urls
        )


# ===========================================================================
# 5b. TestBuildConfigDict
# ===========================================================================


class TestBuildConfigDict:
    """Tests for _build_config_dict() helper."""

    def test_builds_config_from_entry_data(self):
        """Should build config dict with all expected keys."""
        data = make_config_entry_data()
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        config, need_sign_in = _build_config_dict(entry)
        assert config[CONF_USERNAME] == data[CONF_USERNAME]
        assert config[CONF_PASSWORD] == data[CONF_PASSWORD]
        assert config[CONF_COUNTRY] == data.get(CONF_COUNTRY)
        assert need_sign_in is False

    def test_need_sign_in_when_device_id_missing(self):
        """Should set need_sign_in=True when CONF_DEVICE_ID is missing."""
        data = make_config_entry_data()
        del data[CONF_DEVICE_ID]
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        _, need_sign_in = _build_config_dict(entry)
        assert need_sign_in is True

    def test_need_sign_in_when_unique_id_missing(self):
        """Should set need_sign_in=True when CONF_UNIQUE_ID is missing."""
        data = make_config_entry_data()
        del data[CONF_UNIQUE_ID]
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        _, need_sign_in = _build_config_dict(entry)
        assert need_sign_in is True

    def test_need_sign_in_when_indigitall_missing(self):
        """Should set need_sign_in=True when CONF_DEVICE_INDIGITALL is missing."""
        data = make_config_entry_data()
        del data[CONF_DEVICE_INDIGITALL]
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        _, need_sign_in = _build_config_dict(entry)
        assert need_sign_in is True

    def test_options_override_data(self):
        """Options should override data values."""
        data = make_config_entry_data(code="1111")
        entry = MockConfigEntry(domain=DOMAIN, data=data, options={CONF_CODE: "9999"})
        config, _ = _build_config_dict(entry)
        assert config[CONF_CODE] == "9999"

    def test_mapping_config_included(self):
        """Map config keys should be in the returned config."""
        data = make_config_entry_data()
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        config, _ = _build_config_dict(entry)
        assert CONF_MAP_HOME in config
        assert CONF_MAP_AWAY in config
        assert CONF_MAP_NIGHT in config
        assert CONF_MAP_CUSTOM in config
        assert CONF_MAP_VACATION in config


# ===========================================================================
# 5c. TestMaxPollAttempts
# ===========================================================================


class TestMaxPollAttempts:
    """Tests for SecuritasHub._max_poll_attempts()."""

    def _make_hub(self, delay=2):
        config = OrderedDict(
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "test-password",
                CONF_COUNTRY: "ES",
                CONF_DEVICE_ID: "test-device-id",
                CONF_UNIQUE_ID: "test-uuid",
                CONF_DEVICE_INDIGITALL: "test-indigitall",
                CONF_DELAY_CHECK_OPERATION: delay,
                CONF_SCAN_INTERVAL: 120,
                CONF_CODE: "",
                CONF_HAS_PERI: False,
                CONF_CODE_ARM_REQUIRED: False,
            }
        )
        return SecuritasHub(config, MagicMock(), MagicMock(), MagicMock())

    def test_default_timeout(self):
        """Default timeout of 30s with delay=2 should return 15."""
        hub = self._make_hub(delay=2)
        assert hub._max_poll_attempts() == 15

    def test_custom_timeout(self):
        """Custom timeout of 60s with delay=2 should return 30."""
        hub = self._make_hub(delay=2)
        assert hub._max_poll_attempts(timeout_seconds=60) == 30

    def test_minimum_10(self):
        """Should return at least 10 even with large delay."""
        hub = self._make_hub(delay=100)
        assert hub._max_poll_attempts() == 10

    def test_zero_delay(self):
        """Zero delay should not cause division by zero (uses max(1, delay))."""
        hub = self._make_hub(delay=0)
        result = hub._max_poll_attempts(timeout_seconds=30)
        assert result == 30


# ===========================================================================
# 5d. TestValidateAndStoreImage
# ===========================================================================


class TestValidateAndStoreImage:
    """Tests for SecuritasHub._validate_and_store_image()."""

    def _make_hub(self):
        config = OrderedDict(
            {
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "test-password",
                CONF_COUNTRY: "ES",
                CONF_DEVICE_ID: "test-device-id",
                CONF_UNIQUE_ID: "test-uuid",
                CONF_DEVICE_INDIGITALL: "test-indigitall",
                CONF_DELAY_CHECK_OPERATION: 2,
                CONF_SCAN_INTERVAL: 120,
                CONF_CODE: "",
                CONF_HAS_PERI: False,
                CONF_CODE_ARM_REQUIRED: False,
            }
        )
        return SecuritasHub(config, MagicMock(), MagicMock(), MagicMock())

    def test_none_thumbnail_returns_none(self):
        """None thumbnail should return None."""
        hub = self._make_hub()
        inst = make_installation()
        result = hub._validate_and_store_image(None, inst, MagicMock())
        assert result is None

    def test_none_image_returns_none(self):
        """Thumbnail with None image should return None."""
        hub = self._make_hub()
        inst = make_installation()
        thumbnail = MagicMock()
        thumbnail.image = None
        result = hub._validate_and_store_image(thumbnail, inst, MagicMock())
        assert result is None

    def test_valid_jpeg_stored(self):
        """Valid JPEG data should be stored and returned."""
        import base64

        hub = self._make_hub()
        inst = make_installation(number="123")
        camera = MagicMock()
        camera.zone_id = "Z1"
        camera.name = "Camera1"
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        thumbnail = MagicMock()
        thumbnail.image = base64.b64encode(jpeg_bytes).decode()
        thumbnail.timestamp = "2024-01-01T00:00:00"
        result = hub._validate_and_store_image(thumbnail, inst, camera)
        assert result == jpeg_bytes
        assert hub.camera_images["123_Z1"] == jpeg_bytes
        assert hub.camera_timestamps["123_Z1"] == "2024-01-01T00:00:00"

    def test_invalid_jpeg_returns_none(self):
        """Non-JPEG data should return None."""
        import base64

        hub = self._make_hub()
        inst = make_installation(number="123")
        camera = MagicMock()
        camera.zone_id = "Z1"
        camera.name = "Camera1"
        thumbnail = MagicMock()
        thumbnail.image = base64.b64encode(b"NOT_JPEG_DATA").decode()
        result = hub._validate_and_store_image(
            thumbnail, inst, camera, log_warnings=False
        )
        assert result is None
        assert "123_Z1" not in hub.camera_images


# ===========================================================================
# 5e. TestScheduleInitialUpdates
# ===========================================================================


class TestScheduleInitialUpdates:
    """Tests for schedule_initial_updates() in entity.py."""

    def test_empty_entities_no_op(self, hass):
        """Empty entities list should not schedule anything."""
        from custom_components.securitas.entity import schedule_initial_updates

        # Should not raise
        schedule_initial_updates(hass, [])

    def test_schedules_callback(self, hass):
        """Non-empty entities should schedule a callback via async_call_later."""
        from custom_components.securitas.entity import schedule_initial_updates

        entity = MagicMock()
        with patch(
            "custom_components.securitas.entity.async_call_later"
        ) as mock_call_later:
            schedule_initial_updates(hass, [entity], delay=10)
        mock_call_later.assert_called_once()
        assert mock_call_later.call_args[0][1] == 10

    def test_callback_refreshes_entities(self, hass):
        """The scheduled callback should call async_schedule_update_ha_state on each entity."""
        from custom_components.securitas.entity import schedule_initial_updates

        entity1 = MagicMock()
        entity2 = MagicMock()
        with patch(
            "custom_components.securitas.entity.async_call_later"
        ) as mock_call_later:
            schedule_initial_updates(hass, [entity1, entity2])
        # Extract the callback and invoke it
        cb = mock_call_later.call_args[0][2]
        cb(None)
        entity1.async_schedule_update_ha_state.assert_called_once_with(
            force_refresh=True
        )
        entity2.async_schedule_update_ha_state.assert_called_once_with(
            force_refresh=True
        )


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
                CONF_HAS_PERI: data.get(CONF_HAS_PERI, False),
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

        # Set up a second entry to keep DOMAIN alive after unload
        entry2 = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry2.add_to_hass(hass)
        username = entry.data[CONF_USERNAME]

        # Pre-populate hass.data as async_setup_entry would
        hass.data[DOMAIN] = {
            entry.entry_id: {"hub": hub, "devices": []},
            entry2.entry_id: {"hub": hub, "devices": []},
            "sessions": {username: {"hub": hub, "ref_count": 2}},
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
        # DOMAIN should still be in hass.data because entry2 remains
        assert DOMAIN in hass.data

    async def test_unload_removes_domain_when_empty(self, hass):
        """When the last entry is unloaded, DOMAIN should be removed from hass.data."""
        hub = make_securitas_hub_mock()
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        username = entry.data[CONF_USERNAME]
        hass.data[DOMAIN] = {
            entry.entry_id: {"hub": hub, "devices": []},
            "sessions": {username: {"hub": hub, "ref_count": 1}},
        }

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await async_unload_entry(hass, entry)

        assert DOMAIN not in hass.data


# ===========================================================================
# 8. TestSharedSession - Shared API session with reference counting
# ===========================================================================


class TestSharedSession:
    """Tests for shared API session with reference counting."""

    @pytest.fixture
    def mock_hub(self):
        """Create a mock SecuritasHub for setup tests."""
        hub = make_securitas_hub_mock()
        hub.session.list_installations = AsyncMock(
            return_value=[
                make_installation(number="111", alias="Home"),
                make_installation(number="222", alias="Office"),
            ]
        )
        return hub

    def _setup_context(self, mock_hub):
        """Return a context manager stack for patching SecuritasHub + dependencies."""
        return (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
        )

    async def test_first_entry_creates_session_with_ref_count_1(self, hass, mock_hub):
        """First entry for a username should create a new session with ref_count=1."""
        data = make_config_entry_data()
        data[CONF_INSTALLATION] = "111"
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
            result = await async_setup_entry(hass, entry)

        assert result is True
        mock_hub.login.assert_awaited_once()
        username = data[CONF_USERNAME]
        sessions = hass.data[DOMAIN]["sessions"]
        assert username in sessions
        assert sessions[username]["ref_count"] == 1
        assert sessions[username]["hub"] is mock_hub

    async def test_second_entry_reuses_session_ref_count_2(self, hass, mock_hub):
        """Second entry for the same username should reuse the session, ref_count=2."""
        data1 = make_config_entry_data()
        data1[CONF_INSTALLATION] = "111"
        entry1 = MockConfigEntry(domain=DOMAIN, data=data1)
        entry1.add_to_hass(hass)

        data2 = make_config_entry_data()
        data2[CONF_INSTALLATION] = "222"
        entry2 = MockConfigEntry(domain=DOMAIN, data=data2)
        entry2.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            result1 = await async_setup_entry(hass, entry1)
            result2 = await async_setup_entry(hass, entry2)

        assert result1 is True
        assert result2 is True
        # Login should only be called once (for the first entry)
        mock_hub.login.assert_awaited_once()
        username = data1[CONF_USERNAME]
        sessions = hass.data[DOMAIN]["sessions"]
        assert sessions[username]["ref_count"] == 2

    async def test_per_entry_data_stored(self, hass, mock_hub):
        """Each entry should have its own per-entry data with hub and devices."""
        data1 = make_config_entry_data()
        data1[CONF_INSTALLATION] = "111"
        entry1 = MockConfigEntry(domain=DOMAIN, data=data1)
        entry1.add_to_hass(hass)

        data2 = make_config_entry_data()
        data2[CONF_INSTALLATION] = "222"
        entry2 = MockConfigEntry(domain=DOMAIN, data=data2)
        entry2.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            await async_setup_entry(hass, entry1)
            await async_setup_entry(hass, entry2)

        # Each entry should have its own data
        entry1_data = hass.data[DOMAIN][entry1.entry_id]
        entry2_data = hass.data[DOMAIN][entry2.entry_id]

        assert entry1_data["hub"] is mock_hub
        assert entry2_data["hub"] is mock_hub
        # Each entry should have only its own installation's device
        assert len(entry1_data["devices"]) == 1
        assert entry1_data["devices"][0].installation.number == "111"
        assert len(entry2_data["devices"]) == 1
        assert entry2_data["devices"][0].installation.number == "222"

    async def test_concurrent_setup_shares_single_hub(self, hass, mock_hub):
        """Concurrent async_setup_entry calls should share one hub, not create two."""
        import asyncio

        data1 = make_config_entry_data()
        data1[CONF_INSTALLATION] = "111"
        entry1 = MockConfigEntry(domain=DOMAIN, data=data1)
        entry1.add_to_hass(hass)

        data2 = make_config_entry_data()
        data2[CONF_INSTALLATION] = "222"
        entry2 = MockConfigEntry(domain=DOMAIN, data=data2)
        entry2.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            # Run both setup calls concurrently, simulating HA restart
            results = await asyncio.gather(
                async_setup_entry(hass, entry1),
                async_setup_entry(hass, entry2),
            )

        assert results == [True, True]
        # Login should only be called once — the setup lock prevents the
        # second entry from creating its own hub before the first finishes.
        mock_hub.login.assert_awaited_once()
        username = data1[CONF_USERNAME]
        sessions = hass.data[DOMAIN]["sessions"]
        assert sessions[username]["ref_count"] == 2
        # Both entries should reference the same hub
        assert hass.data[DOMAIN][entry1.entry_id]["hub"] is mock_hub
        assert hass.data[DOMAIN][entry2.entry_id]["hub"] is mock_hub

    async def test_unload_one_entry_decrements_ref_count(self, hass, mock_hub):
        """Unloading one entry should decrement ref count but keep the session."""
        data1 = make_config_entry_data()
        data1[CONF_INSTALLATION] = "111"
        entry1 = MockConfigEntry(domain=DOMAIN, data=data1)
        entry1.add_to_hass(hass)

        data2 = make_config_entry_data()
        data2[CONF_INSTALLATION] = "222"
        entry2 = MockConfigEntry(domain=DOMAIN, data=data2)
        entry2.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            await async_setup_entry(hass, entry1)
            await async_setup_entry(hass, entry2)

        username = data1[CONF_USERNAME]
        assert hass.data[DOMAIN]["sessions"][username]["ref_count"] == 2

        # Unload entry1
        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await async_unload_entry(hass, entry1)

        assert result is True
        # Session should still exist with ref_count=1
        assert username in hass.data[DOMAIN]["sessions"]
        assert hass.data[DOMAIN]["sessions"][username]["ref_count"] == 1
        # entry1 data removed, entry2 data remains
        assert entry1.entry_id not in hass.data[DOMAIN]
        assert entry2.entry_id in hass.data[DOMAIN]

    async def test_unload_last_entry_removes_session(self, hass, mock_hub):
        """Unloading the last entry should remove the session entirely."""
        data = make_config_entry_data()
        data[CONF_INSTALLATION] = "111"
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

        username = data[CONF_USERNAME]
        assert hass.data[DOMAIN]["sessions"][username]["ref_count"] == 1

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await async_unload_entry(hass, entry)

        assert result is True
        # Entire DOMAIN should be cleaned up
        assert DOMAIN not in hass.data

    async def test_per_entry_data_populated(self, hass, mock_hub):
        """Per-entry data should contain hub and filtered devices."""
        data = make_config_entry_data()
        data[CONF_INSTALLATION] = "111"
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

        # Per-entry data should be present
        entry_data = hass.data[DOMAIN][entry.entry_id]
        assert entry_data["hub"] is mock_hub
        devices = entry_data["devices"]
        assert len(devices) == 1
        assert isinstance(devices[0], SecuritasDirectDevice)
        # Old backward-compat keys should NOT be present
        assert SecuritasHub.__name__ not in hass.data[DOMAIN]

    async def test_legacy_entry_without_installation_gets_all(self, hass, mock_hub):
        """An entry without CONF_INSTALLATION should get all installations."""
        data = make_config_entry_data()
        # No CONF_INSTALLATION key — legacy behavior
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

        entry_data = hass.data[DOMAIN][entry.entry_id]
        # Should get all installations (2 from mock_hub fixture)
        assert len(entry_data["devices"]) == 2


# ===========================================================================
# Migration tests
# ===========================================================================


class TestAsyncMigrateEntry:
    """Tests for async_migrate_entry — rejects all entries below v3."""

    async def test_migration_v1_rejected(self, hass):
        """v1 entry is rejected with return False (user must delete and re-add)."""
        data = make_config_entry_data(username="user@example.com")

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            unique_id="user@example.com",
            version=1,
        )
        entry.add_to_hass(hass)

        with patch("custom_components.securitas._notify_error"):
            result = await async_migrate_entry(hass, entry)

        assert result is False
        # Entry version remains unchanged
        assert entry.version == 1

    async def test_migration_v2_rejected(self, hass):
        """v2 entry is rejected with return False (user must delete and re-add)."""
        data = make_config_entry_data(username="user@example.com")
        data[CONF_INSTALLATION] = "123456"

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            unique_id="user@example.com_123456",
            version=2,
        )
        entry.add_to_hass(hass)

        with patch("custom_components.securitas._notify_error"):
            result = await async_migrate_entry(hass, entry)

        assert result is False
        assert entry.version == 2

    async def test_migration_v3_accepted(self, hass):
        """v3 entry passes through unchanged (current version)."""
        data = make_config_entry_data(username="user@example.com")
        data[CONF_INSTALLATION] = "123456"

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            unique_id="user@example.com_123456",
            version=3,
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 3


class TestPerDomainQueueSharing:
    """Tests for per-domain ApiQueue sharing."""

    async def test_same_country_shares_queue(self, hass):
        """Two entries with same country should share one ApiQueue."""
        data1 = make_config_entry_data(username="user1@test.com")
        data2 = make_config_entry_data(username="user2@test.com")
        entry1 = MockConfigEntry(domain=DOMAIN, data=data1)
        entry2 = MockConfigEntry(domain=DOMAIN, data=data2)
        entry1.add_to_hass(hass)
        entry2.add_to_hass(hass)

        mock_hub1 = make_securitas_hub_mock()
        mock_hub1.session.list_installations = AsyncMock(
            return_value=[make_installation()]
        )
        mock_hub2 = make_securitas_hub_mock()
        mock_hub2.session.list_installations = AsyncMock(
            return_value=[make_installation(number="654321")]
        )

        # Set up entry1
        mock_cls1 = MagicMock(return_value=mock_hub1)
        mock_cls1.__name__ = "SecuritasHub"
        with (
            patch("custom_components.securitas.SecuritasHub", mock_cls1),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            await async_setup_entry(hass, entry1)

        # Set up entry2
        mock_cls2 = MagicMock(return_value=mock_hub2)
        mock_cls2.__name__ = "SecuritasHub"
        with (
            patch("custom_components.securitas.SecuritasHub", mock_cls2),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            await async_setup_entry(hass, entry2)

        # Both hubs should have the same queue
        hub1 = hass.data[DOMAIN][entry1.entry_id]["hub"]
        hub2 = hass.data[DOMAIN][entry2.entry_id]["hub"]
        assert hub1.api_queue is hub2.api_queue

    async def test_different_country_gets_separate_queue(self, hass):
        """Two entries with different countries should get separate queues."""
        data_es = make_config_entry_data(username="user1@test.com", country="ES")
        data_it = make_config_entry_data(username="user2@test.com", country="IT")
        entry_es = MockConfigEntry(domain=DOMAIN, data=data_es)
        entry_it = MockConfigEntry(domain=DOMAIN, data=data_it)
        entry_es.add_to_hass(hass)
        entry_it.add_to_hass(hass)

        mock_hub_es = make_securitas_hub_mock()
        mock_hub_es.session.list_installations = AsyncMock(
            return_value=[make_installation()]
        )
        mock_hub_it = make_securitas_hub_mock()
        mock_hub_it.session.list_installations = AsyncMock(
            return_value=[make_installation(number="654321")]
        )

        # Set up ES entry
        mock_cls_es = MagicMock(return_value=mock_hub_es)
        mock_cls_es.__name__ = "SecuritasHub"
        with (
            patch("custom_components.securitas.SecuritasHub", mock_cls_es),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            await async_setup_entry(hass, entry_es)

        # Set up IT entry
        mock_cls_it = MagicMock(return_value=mock_hub_it)
        mock_cls_it.__name__ = "SecuritasHub"
        with (
            patch("custom_components.securitas.SecuritasHub", mock_cls_it),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            await async_setup_entry(hass, entry_it)

        hub_es = hass.data[DOMAIN][entry_es.entry_id]["hub"]
        hub_it = hass.data[DOMAIN][entry_it.entry_id]["hub"]
        assert hub_es.api_queue is not hub_it.api_queue
