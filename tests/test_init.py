"""Tests for custom_components/securitas/__init__.py."""

import asyncio
import contextlib
import hashlib
import logging
import os
import time
from collections import Counter, OrderedDict
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from homeassistant.util.async_ import get_scheduled_timer_handles
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

import custom_components.securitas as securitas_init
from custom_components.securitas import (
    _INSTALLATIONS_CACHE,
    _OPTIONS_MANAGED_FIELDS,
    CONF_CODE_ARM_REQUIRED,
    CONF_CODE_HASH,
    CONF_CODE_IS_NUMERIC,
    CONF_COUNTRY,
    CONF_DELAY_CHECK_OPERATION,
    CONF_DEVICE_INDIGITALL,
    CONF_ENABLE_INTERIOR_PANEL,
    CONF_ENABLE_PERIMETER_PANEL,
    CONF_FORCE_ARM_NOTIFICATIONS,
    CONF_INSTALLATION,
    CONF_LOCK_CODE_REQUIRED,
    CONF_MAP_AWAY,
    CONF_MAP_CUSTOM,
    CONF_MAP_HOME,
    CONF_MAP_NIGHT,
    CONF_MAP_VACATION,
    CONF_NOTIFY_GROUP,
    CONF_REFRESH_TOKEN,
    CONFIG_SCHEMA,
    DOMAIN,
    PANEL_OPTION_KEYS,
    PLATFORMS,
    VerisureDevice,
    VerisureHub,
    _account_lock,
    _attach_token_persistence,
    _build_config_dict,
    _cached_installations,
    _get_or_create_session,
    _new_session_record,
    _options_are_authoritative,
    _raise_sign_in_issue,
    _store_installations_cache,
    _synced_entry_data,
    add_device_information,
    async_migrate_entry,
    async_remove_entry,
    async_setup_entry,
    async_unload_entry,
    async_update_options,
)
from custom_components.securitas.const import API_CACHE_TTL, CONF_KEEP_PASSWORD
from custom_components.securitas.hub import (
    _async_notify,
    _hashed_issue_id,
    _notify,
    raise_renewal_refused_issue,
    raise_unreachable_issue,
)
from custom_components.securitas.log_filter import SensitiveDataFilter
from custom_components.securitas.pin_crypto import hash_pin, verify_pin
from custom_components.securitas.verisure_owa_api.client import _base as client_base
from custom_components.securitas.verisure_owa_api.const import (
    STD_DEFAULTS,
)
from custom_components.securitas.verisure_owa_api.exceptions import (
    AccountBlockedError,
    APIConnectionError,
    AuthenticationError,
    SessionExpiredError,
    TwoFactorRequiredError,
    VerisureOwaError,
)
from tests.conftest import (
    LOGIN_SERVER_FAULTS,
    LOGIN_WRONG_PASSWORD,
    login_error_reply,
    login_rejected_error,
    make_config_entry_data,
    make_installation,
    make_securitas_hub_mock,
    refresh_login_crash_error,
    refresh_response,
    refresh_token_rejected_err7_error,
    refresh_token_rejected_error,
)
from tests.test_hub import make_hub

# ---------------------------------------------------------------------------
# Helper: patch VerisureHub preserving __name__
# ---------------------------------------------------------------------------


def _patch_hub(mock_hub):
    """Patch VerisureHub constructor to return mock_hub while preserving __name__.

    MagicMock does not have a proper __name__ attribute, so we set it
    to make the mock behave like a real class. The real __init__ records its
    second positional arg (the ConfigEntry, or None during the config flow) as
    ``self.config_entry``; mirror that here so the session-reuse path in
    ``_get_or_create_session`` can read ``hub.config_entry`` (spec=VerisureHub
    otherwise omits the instance attribute).
    """

    def _construct(*args, **_kwargs):
        # VerisureHub(config, config_entry, session, hass)
        if len(args) >= 2:
            mock_hub.config_entry = args[1]
        return mock_hub

    mock_cls = MagicMock(side_effect=_construct)
    mock_cls.__name__ = "VerisureHub"
    return patch("custom_components.securitas.VerisureHub", mock_cls)


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

    def test_generated_device_id_uses_16_char_uuid_form(self):
        """Generated device_id uses the 16-char uuid form, not the legacy FCM form.

        The API distinguishes idDevice from uuid, but the FCM-token idDevice
        was an accidental orphan (ed4a1e6): every UI install has minted a
        16-char idDevice since Jan 2024 and Verisure accepts it. Both mint
        paths now converge on generate_uuid().
        """
        config = OrderedDict({CONF_COUNTRY: "ES"})
        result = add_device_information(config)
        assert len(result[CONF_DEVICE_ID]) == 16
        assert "-" not in result[CONF_DEVICE_ID]

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
# 1b. TestVerisureHubInit — real constructor, catches missing config keys
# ===========================================================================


class TestVerisureHubInit:
    """Verify VerisureHub.__init__ works with config dicts from various sources."""

    def test_hub_init_with_config_entry_data(self, hass):
        """VerisureHub.__init__ should accept make_config_entry_data() without KeyError."""
        config = make_config_entry_data()
        hub = VerisureHub(config, None, MagicMock(), hass)
        assert hub.country == "ES"

    def test_hub_init_with_minimal_config_flow_config(self, hass):
        """VerisureHub.__init__ should accept the config dict built by _create_client."""
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
        hub = VerisureHub(config, None, MagicMock(), hass)
        assert hub.country == "ES"


# ===========================================================================
# 2. TestAsyncNotify — translated persistent notifications
# ===========================================================================


class TestAsyncNotify:
    """Tests for _async_notify() and _notify() helpers."""

    async def test_looks_up_title_and_message_from_translations_dict(self):
        """Resolves title/message via get_notification_strings and posts to persistent_notification."""
        hass = MagicMock()
        hass.config.language = "en"
        hass.services.async_call = AsyncMock()

        with patch(
            "custom_components.securitas.hub.get_notification_strings",
            return_value={"title": "Hello", "message": "World message"},
        ) as mocked:
            await _async_notify(hass, "my_id", "my_key")

        mocked.assert_called_once_with(hass, "my_key")
        hass.services.async_call.assert_awaited_once_with(
            domain="persistent_notification",
            service="create",
            service_data={
                "title": "Hello",
                "message": "World message",
                "notification_id": f"{DOMAIN}.my_id",
            },
        )

    async def test_interpolates_placeholders_into_title_and_message(self):
        """Placeholders are substituted in both title and message."""
        hass = MagicMock()
        hass.config.language = "es"
        hass.services.async_call = AsyncMock()

        with patch(
            "custom_components.securitas.hub.get_notification_strings",
            return_value={"title": "Hola {name}", "message": "{count} cosas"},
        ):
            await _async_notify(hass, "g1", "greeting", {"name": "Bob", "count": 3})

        service_data = hass.services.async_call.call_args[1]["service_data"]
        assert service_data["title"] == "Hola Bob"
        assert service_data["message"] == "3 cosas"

    def test_notify_sync_wrapper_schedules_async_notify(self):
        """_notify() schedules _async_notify via hass.async_create_task."""
        hass = MagicMock()
        hass.async_create_task = MagicMock()
        _notify(hass, "id1", "key1", {"x": "y"})
        hass.async_create_task.assert_called_once()
        coro = hass.async_create_task.call_args[0][0]
        # Coroutine is the _async_notify call — close it to avoid RuntimeWarning
        coro.close()


# ===========================================================================
# 3. TestVerisureDevice
# ===========================================================================


class TestVerisureDevice:
    """Tests for the VerisureDevice wrapper class."""

    def _make_device(self, **overrides) -> VerisureDevice:
        installation = make_installation(**overrides)
        return VerisureDevice(installation)

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
        device = self._make_device(postal_code="08001")
        assert device.postal_code == "08001"

    def test_device_info_structure(self):
        """device_info should return a valid DeviceInfo dict."""
        device = self._make_device(alias="MyHome", type="PREMIUM", panel="SDVFAST")
        info = device.device_info
        assert info["identifiers"] == {(DOMAIN, "v4_securitas_direct.123456")}  # type: ignore[typeddict-item]
        assert info["manufacturer"] == "Verisure"  # type: ignore[typeddict-item]
        assert info["model"] == "SDVFAST"  # type: ignore[typeddict-item]
        assert info["hw_version"] == "PREMIUM"  # type: ignore[typeddict-item]
        assert info["name"] == "MyHome"  # type: ignore[typeddict-item]


# ===========================================================================
# 4. TestVerisureHub
# ===========================================================================


class TestVerisureHub:
    """Tests for the VerisureHub wrapper class."""

    def _make_config(self, **overrides) -> OrderedDict:
        """Build a minimal config OrderedDict for VerisureHub."""
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
                CONF_CODE_HASH: None,
                CONF_CODE_ARM_REQUIRED: False,
            }
        )
        config.update(overrides)
        return config

    def _make_hub(self, config=None, **config_overrides) -> VerisureHub:
        """Create a VerisureHub with mocked dependencies."""
        if config is None:
            config = self._make_config(**config_overrides)
        return VerisureHub(config, MagicMock(), MagicMock(), MagicMock())

    def test_init_creates_api_manager(self):
        """Constructor should create a VerisureOwaClient."""
        hub = self._make_hub()
        assert hub.client is not None
        assert hub.config[CONF_USERNAME] == "test@example.com"
        assert hub.country == "ES"

    def test_init_stores_config(self):
        """Constructor should store the domain config."""
        config = self._make_config()
        hub = VerisureHub(config, MagicMock(), MagicMock(), MagicMock())
        assert hub.config is config

    async def test_login_delegates_to_session(self):
        """login() should delegate to session.login() when no refresh token is available."""
        hub = self._make_hub()
        hub.client = AsyncMock()
        hub.client.refresh_token_value = ""
        await hub.login()
        hub.client.login.assert_awaited_once()

    async def test_validate_device_delegates(self):
        """validate_device() should delegate to session.validate_device()."""
        hub = self._make_hub()
        hub.client = AsyncMock()
        hub.client.validate_device = AsyncMock(return_value=("hash", []))
        result = await hub.validate_device()
        hub.client.validate_device.assert_awaited_once_with(False, "", "")
        assert result == ("hash", [])

    async def test_send_sms_code_delegates(self):
        """send_sms_code() should delegate to session.validate_device() with correct args."""
        hub = self._make_hub()
        hub.client = AsyncMock()
        hub.client.validate_device = AsyncMock(return_value=("hash", []))
        await hub.send_sms_code("otp-hash", "123456")
        hub.client.validate_device.assert_awaited_once_with(True, "otp-hash", "123456")

    async def test_refresh_token_delegates(self):
        """refresh_token() should delegate to session.refresh_token()."""
        hub = self._make_hub()
        hub.client = AsyncMock()
        hub.client.refresh_token = AsyncMock(return_value=True)
        result = await hub.refresh_token()
        hub.client.refresh_token.assert_awaited_once()
        assert result is True

    async def test_get_services_delegates(self):
        """get_services() should delegate to session.get_all_services()."""
        hub = self._make_hub()
        hub.client = AsyncMock()
        hub.client.get_services = AsyncMock(return_value=[])
        inst = make_installation()
        result = await hub.get_services(inst)
        hub.client.get_services.assert_awaited_once_with(inst)
        assert result == []

    def test_get_authentication_token(self):
        """get_authentication_token should read session.authentication_token."""
        hub = self._make_hub()
        hub.client = MagicMock()
        hub.client.authentication_token = "original-token"
        assert hub.get_authentication_token() == "original-token"


# ===========================================================================
# 5. TestAsyncSetupEntry
# ===========================================================================


class TestAsyncSetupEntry:
    """Tests for async_setup_entry()."""

    @pytest.fixture
    def mock_hub(self):
        """Create a mock VerisureHub for setup tests."""
        hub = make_securitas_hub_mock()
        hub.client.list_installations = AsyncMock(return_value=[make_installation()])
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
        mock_hub.client.list_installations.assert_awaited_once()
        assert DOMAIN in hass.data
        assert entry.entry_id in hass.data[DOMAIN]
        assert "hub" in hass.data[DOMAIN][entry.entry_id]
        assert "devices" in hass.data[DOMAIN][entry.entry_id]

    async def test_setup_registers_each_accounts_kept_password(self, hass, mock_hub):
        """Two accounts' kept passwords stay redacted side by side."""
        mock_hub.login = AsyncMock(side_effect=VerisureOwaError("connection failed"))
        for username, password in (
            ("first@example.com", "first-secret"),
            ("second@example.com", "second-secret"),
        ):
            data = make_config_entry_data(username=username, password=password)
            data[CONF_KEEP_PASSWORD] = True
            entry = MockConfigEntry(domain=DOMAIN, data=data)
            entry.add_to_hass(hass)
            with (
                _patch_hub(mock_hub),
                patch("custom_components.securitas.async_get_clientsession"),
                pytest.raises(ConfigEntryNotReady),
            ):
                await async_setup_entry(hass, entry)

        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="first-secret and second-secret",
            args=(),
            exc_info=None,
        )
        hass.data[DOMAIN]["log_filter"].filter(record)
        assert record.msg == "[PASSWORD] and [PASSWORD]"

    async def test_setup_succeeds_with_refresh_token_only_entry(self, hass, mock_hub):
        """Refresh-token-shape entries (no CONF_PASSWORD) must set up cleanly."""
        from custom_components.securitas.const import CONF_REFRESH_TOKEN

        data = make_config_entry_data()
        data.pop(CONF_PASSWORD)
        data[CONF_REFRESH_TOKEN] = "persisted-refresh-token"

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

    async def test_setup_securitas_error_during_login(self, hass, mock_hub):
        """VerisureOwaError during login should raise ConfigEntryNotReady."""
        mock_hub.login = AsyncMock(side_effect=VerisureOwaError("connection failed"))
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

    async def test_setup_connection_error_retries_rather_than_prompting_reauth(
        self, hass, mock_hub
    ):
        """Connection failure during login raises ConfigEntryNotReady, not AuthFailed."""
        mock_hub.login = AsyncMock(
            side_effect=APIConnectionError(
                "Connection error with URL https://x: ConnectionTimeoutError"
            )
        )
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

    async def test_setup_login_error_does_not_leak_response_body(self, hass, mock_hub):
        """User-facing ConfigEntryNotReady must not embed raw response body.

        log_detail() may include the raw API response (which can contain
        tokens) for unknown errors. That detail belongs in the (filtered)
        log, not in the user-facing exception text.
        """
        err = VerisureOwaError("connection failed")
        err.response_body = {
            "data": {"hash": "leaked-auth-token-value"},
        }
        mock_hub.login = AsyncMock(side_effect=err)
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            pytest.raises(ConfigEntryNotReady) as exc_info,
        ):
            await async_setup_entry(hass, entry)

        # Token must not appear in the user-facing message
        assert "leaked-auth-token-value" not in str(exc_info.value)

    async def test_setup_securitas_error_during_list_installations(
        self, hass, mock_hub
    ):
        """VerisureOwaError during list_installations should raise ConfigEntryNotReady."""
        mock_hub.client.list_installations = AsyncMock(
            side_effect=VerisureOwaError("network error")
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
        """After successful setup, VerisureHub should be stored in per-entry data."""
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
        assert isinstance(devices[0], VerisureDevice)

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

        # Verify static path registration (both new and legacy paths)
        hass.http.async_register_static_paths.assert_awaited_once()
        call_args = hass.http.async_register_static_paths.call_args[0][0]
        assert len(call_args) == 2
        paths = [cfg.url_path for cfg in call_args]
        assert "/verisure-owa-panel" in paths
        assert "/securitas_panel" in paths

        # Verify all card JS URLs plus the global More Info module are registered.
        assert mock_add_js.call_count == 5
        js_urls = [call[0][1] for call in mock_add_js.call_args_list]
        assert any(
            u.startswith("/verisure-owa-panel/verisure-owa-alarm-card.js?v=")
            for u in js_urls
        )
        # The lightweight chip/badge module is registered as its own resource so
        # the always-visible alarm chip renders without first downloading the
        # heavy alarm-card bundle.
        assert any(
            u.startswith("/verisure-owa-panel/verisure-owa-alarm-chip.js?v=")
            for u in js_urls
        )
        # ...and it must be registered BEFORE the heavy alarm card: in the
        # add_extra_js_url fallback, resources inject as ordered
        # <script type="module"> tags that execute in document order, so the
        # lightweight chip must come first to render ASAP on cold load.
        chip_idx = next(
            i for i, u in enumerate(js_urls) if "verisure-owa-alarm-chip.js" in u
        )
        card_idx = next(
            i for i, u in enumerate(js_urls) if "verisure-owa-alarm-card.js" in u
        )
        assert chip_idx < card_idx, (
            f"chip ({chip_idx}) must register before card ({card_idx}) so it "
            "loads first in the add_extra_js_url fallback"
        )
        assert any(
            u.startswith("/verisure-owa-panel/verisure-owa-camera-card.js?v=")
            for u in js_urls
        )
        assert any(
            u.startswith("/verisure-owa-panel/verisure-owa-activity-log-card.js?v=")
            for u in js_urls
        )
        assert any(
            u.startswith("/verisure-owa-panel/verisure-owa-more-info.js?v=")
            for u in js_urls
        )

    async def test_setup_static_paths_cache_policy(self, hass, mock_hub):
        """Static paths use a differential cache policy.

        ``/verisure-owa-panel`` (cache_headers=True): the integration only ever
        emits cache-busted URLs here — entry points via ``_card_url`` and the
        imports between modules via ``scripts/stamp_card_imports.py``, all
        ``?v=<content hash>-<version>`` — so a long max-age is
        safe and gives the cold-load speed-up (the alarm chip no longer renders
        5-10s late).

        ``/securitas_panel`` (cache_headers=False): legacy path for pre-v5 URLs
        users hardcoded into resources/Markdown cards. Those URLs carry NO
        ``?v=`` bust token, so a long max-age would pin them stale ~31 days
        after an update; revalidation keeps them fresh.
        """
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

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
            patch("custom_components.securitas.frontend.add_extra_js_url"),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True
        hass.http.async_register_static_paths.assert_awaited_once()
        call_args = hass.http.async_register_static_paths.call_args[0][0]
        cache_by_path = {cfg.url_path: cfg.cache_headers for cfg in call_args}
        assert cache_by_path == {
            "/verisure-owa-panel": True,
            "/securitas_panel": False,
        }, cache_by_path

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
        # All card resources and the global More Info module are registered
        # exactly once despite two setup calls.
        # (guarded by card_registered flag)
        assert mock_add_js.call_count == 5
        js_urls = [call[0][1] for call in mock_add_js.call_args_list]
        assert any(
            u.startswith("/verisure-owa-panel/verisure-owa-alarm-card.js?v=")
            for u in js_urls
        )
        assert any(
            u.startswith("/verisure-owa-panel/verisure-owa-camera-card.js?v=")
            for u in js_urls
        )
        assert any(
            u.startswith("/verisure-owa-panel/verisure-owa-activity-log-card.js?v=")
            for u in js_urls
        )
        assert any(
            u.startswith("/verisure-owa-panel/verisure-owa-more-info.js?v=")
            for u in js_urls
        )

    class _FakeResources:
        """Minimal stand-in for HA's Lovelace ResourceStorageCollection."""

        def __init__(self, items=()):
            self.loaded = False
            self._items = [dict(item) for item in items]
            self._next_id = len(self._items)

        async def async_load(self):
            self.loaded = True

        def async_items(self):
            return list(self._items)

        async def async_create_item(self, data):
            self._next_id += 1
            item = {"id": f"res-{self._next_id}", **data}
            self._items.append(item)
            return item

        async def async_update_item(self, item_id, data):
            item = next(i for i in self._items if i["id"] == item_id)
            item.update(data)
            return item

        async def async_delete_item(self, item_id):
            self._items = [i for i in self._items if i["id"] != item_id]

    async def _setup_with_resources(self, hass, mock_hub, resources):
        lovelace_data = MagicMock()
        lovelace_data.resources = resources
        hass.data["lovelace"] = lovelace_data

        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

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
            assert await async_setup_entry(hass, entry)
        return [call[0][1] for call in mock_add_js.call_args_list]

    async def test_setup_loads_more_info_on_every_page(self, hass, mock_hub):
        """The More Info module is injected into every page, not a dashboard
        resource: HA loads dashboard resources only on dashboards, so opening
        the alarm from the Home, Security or Settings pages showed an empty
        dialog (#624)."""
        resources = self._FakeResources()

        js_urls = await self._setup_with_resources(hass, mock_hub, resources)

        assert any(
            u.startswith("/verisure-owa-panel/verisure-owa-more-info.js?v=")
            for u in js_urls
        ), js_urls
        assert not any(
            "verisure-owa-more-info.js" in item["url"]
            for item in resources.async_items()
        ), resources.async_items()

    async def test_setup_removes_the_more_info_resource_of_earlier_versions(
        self, hass, mock_hub
    ):
        """v5.8 registered More Info as a dashboard resource; left in place it
        would load the old module on dashboards alongside the new one."""
        resources = self._FakeResources(
            [
                {
                    "id": "old-more-info",
                    "res_type": "module",
                    "url": "/verisure-owa-panel/verisure-owa-more-info.js?v=abc-5.8.0",
                },
                {"id": "someone-else", "res_type": "module", "url": "/local/x.js"},
            ]
        )

        await self._setup_with_resources(hass, mock_hub, resources)

        urls = [item["url"] for item in resources.async_items()]
        assert not any("verisure-owa-more-info.js" in u for u in urls), urls
        assert "/local/x.js" in urls

    async def test_two_accounts_each_fetches_own_installations(self, hass):
        """Two accounts' entries each list and keep their own installations, so
        each finds its own installation and its entities are available."""
        italian_installation = make_installation(number="1111", alias="Gran Via")
        spanish_installation = make_installation(number="2222", alias="Rome")

        italian_hub = make_securitas_hub_mock()
        italian_hub.client.list_installations = AsyncMock(
            return_value=[italian_installation]
        )
        italian_hub.client.get_services = AsyncMock(return_value=[])

        spanish_hub = make_securitas_hub_mock()
        spanish_hub.client.list_installations = AsyncMock(
            return_value=[spanish_installation]
        )
        spanish_hub.client.get_services = AsyncMock(return_value=[])

        italian_data = make_config_entry_data(username="italian@example.com")
        italian_data[CONF_INSTALLATION] = "1111"
        spanish_data = make_config_entry_data(username="spanish@example.com")
        spanish_data[CONF_INSTALLATION] = "2222"

        entry_it = MockConfigEntry(domain=DOMAIN, data=italian_data)
        entry_it.add_to_hass(hass)
        entry_es = MockConfigEntry(domain=DOMAIN, data=spanish_data)
        entry_es.add_to_hass(hass)

        hubs_by_username = {
            "italian@example.com": italian_hub,
            "spanish@example.com": spanish_hub,
        }

        def hub_factory(config, entry, *args, **kwargs):
            return hubs_by_username[config[CONF_USERNAME]]

        mock_hub_cls = MagicMock(side_effect=hub_factory)
        mock_hub_cls.__name__ = "VerisureHub"

        with (
            patch("custom_components.securitas.VerisureHub", mock_hub_cls),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            result_it = await async_setup_entry(hass, entry_it)
            result_es = await async_setup_entry(hass, entry_es)

        assert result_it is True
        assert result_es is True

        # Each hub must have fetched its own installation list exactly once
        italian_hub.client.list_installations.assert_awaited_once()
        spanish_hub.client.list_installations.assert_awaited_once()

        # Each entry must have exactly one device (its own installation)
        it_devices = hass.data[DOMAIN][entry_it.entry_id]["devices"]
        es_devices = hass.data[DOMAIN][entry_es.entry_id]["devices"]
        assert len(it_devices) == 1
        assert it_devices[0].installation.number == "1111"
        assert len(es_devices) == 1
        assert es_devices[0].installation.number == "2222"

    async def test_reading_the_cache_forgets_the_lists_that_expired(self, hass):
        """A removed integration's list, which holds addresses, is dropped
        once past its usual time by the next read of any account's list."""
        _store_installations_cache(hass, "old@example.com", [make_installation()])
        _store_installations_cache(hass, "fresh@example.com", [make_installation()])
        hass.data[_INSTALLATIONS_CACHE]["old@example.com"]["time"] -= API_CACHE_TTL

        assert _cached_installations(hass, "fresh@example.com") is not None

        assert set(hass.data[_INSTALLATIONS_CACHE]) == {"fresh@example.com"}

    async def test_storing_a_list_forgets_the_lists_that_expired(self, hass):
        """The cached lists outlive the integration's clean-up, so storing one
        drops those past their usual time rather than keep them forever."""
        _store_installations_cache(hass, "old@example.com", [make_installation()])
        _store_installations_cache(hass, "fresh@example.com", [make_installation()])
        hass.data[_INSTALLATIONS_CACHE]["old@example.com"]["time"] -= API_CACHE_TTL

        _store_installations_cache(hass, "new@example.com", [make_installation()])

        assert set(hass.data[_INSTALLATIONS_CACHE]) == {
            "fresh@example.com",
            "new@example.com",
        }

    async def test_the_lists_are_forgotten_once_the_last_one_expires(self, hass):
        """With nothing left to read or store them (the integration removed),
        the lists are dropped once the most recently stored one has expired,
        and storing another list does not add a second timer."""
        _store_installations_cache(hass, "old@example.com", [make_installation()])
        _store_installations_cache(hass, "new@example.com", [make_installation()])
        assert len(_pending_installations_cache_expiries(hass)) == 1

        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        assert set(hass.data[_INSTALLATIONS_CACHE]) == {
            "old@example.com",
            "new@example.com",
        }

        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(seconds=API_CACHE_TTL + 1)
        )
        assert _INSTALLATIONS_CACHE not in hass.data
        assert _pending_installations_cache_expiries(hass) == []


def _pending_installations_cache_expiries(hass):
    """The timers still set to forget the cached installation lists."""
    return [
        handle
        for handle in get_scheduled_timer_handles(hass.loop)
        if not handle.cancelled()
        and "installations" in getattr(handle._args[-1], "name", "")
    ]


# ===========================================================================
# 5b. TestBuildConfigDict
# ===========================================================================


class TestOptionsManagedFields:
    """Tests for the _OPTIONS_MANAGED_FIELDS tuple."""

    def test_each_field_listed_once(self):
        """A key listed twice is a copy/paste slip — harmless but misleading."""
        duplicates = sorted(
            key for key, count in Counter(_OPTIONS_MANAGED_FIELDS).items() if count > 1
        )
        assert not duplicates

    def test_lock_code_required_is_options_managed(self):
        """Clearing the lock PIN toggle in options must not resurrect it from data."""
        assert CONF_LOCK_CODE_REQUIRED in _OPTIONS_MANAGED_FIELDS

    def test_panel_option_keys_are_options_managed(self):
        """The seed keys must be a subset of the managed set.

        ``_options_are_authoritative`` treats an options dict holding nothing
        beyond PANEL_OPTION_KEYS as "the options flow hasn't run". A toggle
        outside _OPTIONS_MANAGED_FIELDS would make the guard discount a key
        the sync never touches, so the two sets have to stay related.
        """
        assert set(PANEL_OPTION_KEYS).issubset(_OPTIONS_MANAGED_FIELDS)


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

    @pytest.mark.parametrize("kept", [True, False])
    def test_keep_password_flag_passes_through(self, kept):
        data = make_config_entry_data()
        data[CONF_KEEP_PASSWORD] = kept
        config, _ = _build_config_dict(MockConfigEntry(domain=DOMAIN, data=data))
        assert config[CONF_KEEP_PASSWORD] is kept

    def test_keep_password_flag_defaults_to_false(self):
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        config, _ = _build_config_dict(entry)
        assert config[CONF_KEEP_PASSWORD] is False

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
        options_hash = hash_pin("9999")
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            options={CONF_CODE_HASH: options_hash, CONF_CODE_IS_NUMERIC: True},
        )
        config, _ = _build_config_dict(entry)
        assert config[CONF_CODE_HASH] == options_hash
        assert verify_pin("9999", config[CONF_CODE_HASH])
        assert not verify_pin("1111", config[CONF_CODE_HASH])

    def test_lock_code_required_from_options(self):
        """The lock PIN toggle set in options reaches the entry's config."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=make_config_entry_data(),
            options={CONF_LOCK_CODE_REQUIRED: True},
        )
        config, _ = _build_config_dict(entry)
        assert config[CONF_LOCK_CODE_REQUIRED] is True

    def test_lock_code_required_defaults_off(self):
        """Entries predating the option come up with the gate off."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        config, _ = _build_config_dict(entry)
        assert config[CONF_LOCK_CODE_REQUIRED] is False

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


# ===========================================================================
# 5d. TestValidateAndStoreImage
# ===========================================================================


class TestValidateAndStoreImage:
    """Tests for VerisureHub._validate_and_store_image()."""

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
                CONF_CODE_HASH: None,
                CONF_CODE_ARM_REQUIRED: False,
            }
        )
        return VerisureHub(config, MagicMock(), MagicMock(), MagicMock())

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
# 6. TestAsyncUpdateOptions
# ===========================================================================


class TestAsyncUpdateOptions:
    """Tests for async_update_options()."""

    def test_options_none_is_not_authoritative(self):
        """`options=None` at entry creation must not blow up the guard.

        `_create_entry_for_installation` passes `options=None` when the
        installation has no sub-panels. HA coerces that to an empty mapping
        (`MappingProxyType(options or {})`), so `entry.options` is never
        None — but the guard went from a None-tolerant `not entry.options`
        to `set(entry.options)`, so pin the coercion we now rely on.
        """
        entry = MockConfigEntry(
            domain=DOMAIN, data=make_config_entry_data(code="1234"), options=None
        )

        assert entry.options == {}
        assert _options_are_authoritative(entry) is False
        assert _synced_entry_data(entry) is None

    def test_entry_creation_options_do_not_wipe_data(self):
        """A fresh install's toggles-only options must not gut entry.data.

        See ``_options_are_authoritative`` for why that dict isn't
        authoritative despite being non-empty.
        """
        data = make_config_entry_data(code="1234")
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            options={
                CONF_ENABLE_PERIMETER_PANEL: True,
                CONF_ENABLE_INTERIOR_PANEL: False,
            },
        )

        synced = _synced_entry_data(entry)

        assert synced is None, (
            "entry.data must be left alone until the options flow has run; "
            f"would have dropped {sorted(set(data) - set(synced))}"
        )

    async def test_entry_creation_options_still_yield_a_working_pin(self, hass):
        """The end-to-end consequence: the PIN gate survives the sync.

        Also pins the second half of the win — no entry rewrite means no
        spurious full reload on the first login after a fresh install.
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=make_config_entry_data(code="1234"),
            options={CONF_ENABLE_PERIMETER_PANEL: True},
        )
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries, "async_reload", new_callable=AsyncMock
        ) as mock_reload:
            await async_update_options(hass, entry)

        mock_reload.assert_not_awaited()
        config, _ = _build_config_dict(entry)
        assert verify_pin("1234", config[CONF_CODE_HASH])
        assert config[CONF_MAP_HOME]

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
                CONF_CODE_HASH: data[CONF_CODE_HASH],
                CONF_CODE_IS_NUMERIC: data[CONF_CODE_IS_NUMERIC],
                CONF_CODE_ARM_REQUIRED: data[CONF_CODE_ARM_REQUIRED],
                CONF_SCAN_INTERVAL: data[CONF_SCAN_INTERVAL],
                CONF_MAP_HOME: data[CONF_MAP_HOME],
                CONF_MAP_AWAY: data[CONF_MAP_AWAY],
                CONF_MAP_NIGHT: data[CONF_MAP_NIGHT],
                **{
                    k: data[k]
                    for k in (CONF_MAP_CUSTOM, CONF_MAP_VACATION)
                    if k in data
                },
                CONF_NOTIFY_GROUP: "",
                CONF_FORCE_ARM_NOTIFICATIONS: data[CONF_FORCE_ARM_NOTIFICATIONS],
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
            options={CONF_CODE_HASH: hash_pin("1234"), CONF_CODE_IS_NUMERIC: True},
        )
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
        ) as mock_reload:
            await async_update_options(hass, entry)
            mock_reload.assert_awaited_once_with(entry.entry_id)

    async def test_reload_when_lock_automations_changes(self, hass):
        """Adding per-lock automation config (with all other settings matching)
        must trigger a config-entry reload so the lock entity's
        async_added_to_hass re-reads CONF_LOCK_AUTOMATIONS. Without the reload,
        the auto-lock listener keeps its stale empty circuit lists from the
        original load and never fires.
        """
        from custom_components.securitas.const import CONF_LOCK_AUTOMATIONS

        data = make_config_entry_data()
        # All non-lock options match data so the existing trigger keys don't
        # spuriously cause a reload — isolating CONF_LOCK_AUTOMATIONS as the
        # only differing setting.
        options = {
            CONF_CODE_HASH: data[CONF_CODE_HASH],
            CONF_CODE_IS_NUMERIC: data[CONF_CODE_IS_NUMERIC],
            CONF_CODE_ARM_REQUIRED: data[CONF_CODE_ARM_REQUIRED],
            CONF_SCAN_INTERVAL: data[CONF_SCAN_INTERVAL],
            CONF_MAP_HOME: data[CONF_MAP_HOME],
            CONF_MAP_AWAY: data[CONF_MAP_AWAY],
            CONF_MAP_NIGHT: data[CONF_MAP_NIGHT],
            **{k: data[k] for k in (CONF_MAP_CUSTOM, CONF_MAP_VACATION) if k in data},
            CONF_NOTIFY_GROUP: "",
            CONF_FORCE_ARM_NOTIFICATIONS: data[CONF_FORCE_ARM_NOTIFICATIONS],
            CONF_LOCK_AUTOMATIONS: {
                "01": {"lock_on_arm": ["interior"], "unlock_disarms": ["interior"]}
            },
        }
        entry = MockConfigEntry(domain=DOMAIN, data=data, options=options)
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
        ) as mock_reload:
            await async_update_options(hass, entry)
            mock_reload.assert_awaited_once_with(entry.entry_id)

    async def test_clearing_map_vacation_removes_stale_data_value(self, hass):
        """Clearing CONF_MAP_VACATION via options must clear it from entry.data too.

        Regression: the listener used to merge `{**entry.data, **entry.options}`,
        which preserved the prior value in entry.data when the user cleared the
        field. _opt() then resurrected the stale value, so the form pre-filled
        again on the next open — the field appeared "stuck".
        """
        data = make_config_entry_data(
            has_peri=True,
            map_vacation="partial_night_peri",
        )
        # User just saved new options that omit CONF_MAP_VACATION (cleared).
        options = {
            CONF_CODE_HASH: data[CONF_CODE_HASH],
            CONF_CODE_IS_NUMERIC: data[CONF_CODE_IS_NUMERIC],
            CONF_CODE_ARM_REQUIRED: data[CONF_CODE_ARM_REQUIRED],
            CONF_SCAN_INTERVAL: data[CONF_SCAN_INTERVAL],
            CONF_MAP_HOME: data[CONF_MAP_HOME],
            CONF_MAP_AWAY: data[CONF_MAP_AWAY],
            CONF_MAP_NIGHT: data[CONF_MAP_NIGHT],
            CONF_MAP_CUSTOM: data[CONF_MAP_CUSTOM],
            # CONF_MAP_VACATION intentionally absent — user cleared the field.
            CONF_NOTIFY_GROUP: data[CONF_NOTIFY_GROUP],
            CONF_FORCE_ARM_NOTIFICATIONS: data[CONF_FORCE_ARM_NOTIFICATIONS],
        }
        entry = MockConfigEntry(domain=DOMAIN, data=data, options=options)
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
        ):
            await async_update_options(hass, entry)

        assert CONF_MAP_VACATION not in entry.data, (
            f"Stale CONF_MAP_VACATION should be cleared from entry.data, "
            f"got {entry.data.get(CONF_MAP_VACATION)!r}"
        )

    async def test_clearing_map_vacation_with_empty_string_clears_data(self, hass):
        """An empty-string vacation in options (UI 'Not used' selection) must
        propagate to entry.data, not leave a stale prior value behind."""
        data = make_config_entry_data(
            has_peri=True,
            map_vacation="partial_night_peri",
        )
        options = {
            CONF_CODE_HASH: data[CONF_CODE_HASH],
            CONF_CODE_IS_NUMERIC: data[CONF_CODE_IS_NUMERIC],
            CONF_CODE_ARM_REQUIRED: data[CONF_CODE_ARM_REQUIRED],
            CONF_SCAN_INTERVAL: data[CONF_SCAN_INTERVAL],
            CONF_MAP_HOME: data[CONF_MAP_HOME],
            CONF_MAP_AWAY: data[CONF_MAP_AWAY],
            CONF_MAP_NIGHT: data[CONF_MAP_NIGHT],
            CONF_MAP_CUSTOM: data[CONF_MAP_CUSTOM],
            CONF_MAP_VACATION: "",
            CONF_NOTIFY_GROUP: data[CONF_NOTIFY_GROUP],
            CONF_FORCE_ARM_NOTIFICATIONS: data[CONF_FORCE_ARM_NOTIFICATIONS],
        }
        entry = MockConfigEntry(domain=DOMAIN, data=data, options=options)
        entry.add_to_hass(hass)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
        ):
            await async_update_options(hass, entry)

        assert not entry.data.get(CONF_MAP_VACATION), (
            f"Cleared vacation should resolve to falsy in entry.data, "
            f"got {entry.data.get(CONF_MAP_VACATION)!r}"
        )

    @pytest.mark.parametrize(
        "toggle_key",
        [
            "enable_interior_panel",
            "enable_perimeter_panel",
            "enable_annex_panel",
        ],
    )
    async def test_reload_when_subpanel_toggle_changes(self, hass, toggle_key):
        """Toggling any sub-panel option triggers a config-entry reload."""
        data = make_config_entry_data()
        data[toggle_key] = False
        options = {
            CONF_CODE_HASH: data[CONF_CODE_HASH],
            CONF_CODE_IS_NUMERIC: data[CONF_CODE_IS_NUMERIC],
            CONF_CODE_ARM_REQUIRED: data[CONF_CODE_ARM_REQUIRED],
            CONF_SCAN_INTERVAL: data[CONF_SCAN_INTERVAL],
            CONF_MAP_HOME: data[CONF_MAP_HOME],
            CONF_MAP_AWAY: data[CONF_MAP_AWAY],
            CONF_MAP_NIGHT: data[CONF_MAP_NIGHT],
            **{k: data[k] for k in (CONF_MAP_CUSTOM, CONF_MAP_VACATION) if k in data},
            CONF_NOTIFY_GROUP: data[CONF_NOTIFY_GROUP],
            CONF_FORCE_ARM_NOTIFICATIONS: data[CONF_FORCE_ARM_NOTIFICATIONS],
            toggle_key: True,
        }
        entry = MockConfigEntry(domain=DOMAIN, data=data, options=options)
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
            "sessions": {
                username: {
                    "hub": hub,
                    "holders": {entry.entry_id, entry2.entry_id},
                }
            },
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

    async def test_unload_owner_entry_hands_off_persistence_to_survivor(self, hass):
        """Regression test for issue #557 — hand off the persistence target.

        Two entries for one username share a hub, and the hub persists rotated
        refresh tokens to whichever entry it is attached to. If that owning
        entry is removed while a co-tenant survives, the hub must re-attach to
        the survivor and persist the current token to it — otherwise rotations
        target the removed entry, the survivor's on-disk token goes stale, and
        the xSRefreshLogin 'fr' crash recurs on the survivor's next restart.
        """
        hub = make_securitas_hub_mock()
        hub.get_refresh_token = MagicMock(return_value="current-refresh-token")

        owner = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        owner.add_to_hass(hass)
        survivor = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        survivor.add_to_hass(hass)
        username = owner.data[CONF_USERNAME]

        # The hub currently persists rotated tokens to `owner`.
        hub.config_entry = owner
        hass.data[DOMAIN] = {
            owner.entry_id: {"hub": hub, "devices": []},
            survivor.entry_id: {"hub": hub, "devices": []},
            "sessions": {
                username: {
                    "hub": hub,
                    "holders": {owner.entry_id, survivor.entry_id},
                }
            },
        }

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await async_unload_entry(hass, owner)

        # Persistence must move to the surviving co-tenant, and the current
        # in-memory token must be written there immediately (not left stale).
        assert hub.config_entry is survivor
        hub.persist_current_refresh_token.assert_called_once_with()
        assert hass.data[DOMAIN]["sessions"][username]["holders"] == {survivor.entry_id}

    async def test_unload_non_owner_entry_leaves_persistence_target(self, hass):
        """Unloading a co-tenant that does NOT own persistence must not reattach."""
        hub = make_securitas_hub_mock()
        owner = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        owner.add_to_hass(hass)
        other = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        other.add_to_hass(hass)
        username = owner.data[CONF_USERNAME]

        hub.config_entry = owner
        hass.data[DOMAIN] = {
            owner.entry_id: {"hub": hub, "devices": []},
            other.entry_id: {"hub": hub, "devices": []},
            "sessions": {
                username: {
                    "hub": hub,
                    "holders": {owner.entry_id, other.entry_id},
                }
            },
        }

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await async_unload_entry(hass, other)

        # `owner` is still loaded and still owns persistence — no handoff.
        assert hub.config_entry is owner
        hub.persist_current_refresh_token.assert_not_called()

    async def test_unload_entry_that_never_held_keeps_cotenant_session(self, hass):
        """Unloading a non-holder must not drop the hold a holder still has.

        An entry that never took a hold must, when unloaded, leave the
        holders alone rather than pop the shared session out
        from under the co-tenant that is still using it.
        """
        hub = make_securitas_hub_mock()
        holder = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        holder.add_to_hass(hass)
        never_held = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        never_held.add_to_hass(hass)
        username = holder.data[CONF_USERNAME]

        hub.config_entry = holder
        hass.data[DOMAIN] = {
            holder.entry_id: {"hub": hub, "devices": []},
            "sessions": {
                username: {
                    "hub": hub,
                    "holders": {holder.entry_id},
                }
            },
        }

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await async_unload_entry(hass, never_held)

        assert result is True
        session = hass.data[DOMAIN]["sessions"][username]
        assert session["hub"] is hub
        assert session["holders"] == {holder.entry_id}
        # The holder still owns persistence — no handoff was triggered.
        assert hub.config_entry is holder
        hub.persist_current_refresh_token.assert_not_called()

    async def test_failed_platform_unload_preserves_runtime_data(self, hass):
        """A failed platform unload must leave the loaded entry intact."""
        hub = make_securitas_hub_mock()
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        username = entry.data[CONF_USERNAME]

        hass.data[DOMAIN] = {
            entry.entry_id: {
                "hub": hub,
                "devices": [],
            },
            "sessions": {username: {"hub": hub, "holders": {entry.entry_id}}},
        }

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await async_unload_entry(hass, entry)

        assert result is False
        assert hass.data[DOMAIN][entry.entry_id]["hub"] is hub
        assert len(hass.data[DOMAIN]["sessions"][username]["holders"]) == 1

    async def test_unload_removes_domain_when_empty(self, hass):
        """When the last entry is unloaded, DOMAIN should be removed from hass.data."""
        hub = make_securitas_hub_mock()
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        username = entry.data[CONF_USERNAME]
        hass.data[DOMAIN] = {
            entry.entry_id: {"hub": hub, "devices": []},
            "sessions": {username: {"hub": hub, "holders": {entry.entry_id}}},
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
# 8. TestSharedSession - Shared API session tracked by holder set
# ===========================================================================


class TestSharedSession:
    """Tests for shared API session tracked by holder set."""

    @pytest.fixture
    def mock_hub(self):
        """Create a mock VerisureHub for setup tests."""
        hub = make_securitas_hub_mock()
        hub.client.list_installations = AsyncMock(
            return_value=[
                make_installation(number="111", alias="Home"),
                make_installation(number="222", alias="Office"),
            ]
        )
        return hub

    def _setup_context(self, mock_hub):
        """Return a context manager stack for patching VerisureHub + dependencies."""
        return (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
        )

    async def test_first_entry_creates_session_with_one_holder(self, hass, mock_hub):
        """First entry for a username should create a session it alone holds."""
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
        assert sessions[username]["holders"] == {entry.entry_id}
        assert sessions[username]["hub"] is mock_hub

    async def test_second_entry_reuses_session_with_two_holders(self, hass, mock_hub):
        """Second entry for the same username should reuse the session and join it."""
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
        assert sessions[username]["holders"] == {entry1.entry_id, entry2.entry_id}

    async def test_failed_setup_retries_keep_one_hold_and_one_sign_in(
        self, hass, mock_hub
    ):
        """A setup that fails after registering must not take a second hold.

        ``_get_or_create_session`` registers the session and setup carries on.
        When a later step fails — ``_fetch_and_cache_installations`` is the
        usual one — HA raises ConfigEntryNotReady and never calls
        ``async_unload_entry``, so the hold stays. HA then retries setup,
        which must recognise the entry as an existing holder: no second
        hold, and no second sign-in (each login rotates the refresh token
        and the WAF rate-limits by IP).
        """
        data = make_config_entry_data()
        data[CONF_INSTALLATION] = "111"
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch(
                "custom_components.securitas._fetch_and_cache_installations",
                side_effect=VerisureOwaError("backend unavailable"),
            ),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            for _ in range(3):
                with pytest.raises(ConfigEntryNotReady):
                    await async_setup_entry(hass, entry)

        username = data[CONF_USERNAME]
        sessions = hass.data[DOMAIN]["sessions"]
        assert sessions[username]["holders"] == {entry.entry_id}
        mock_hub.login.assert_awaited_once()

    async def test_reused_config_flow_hub_gets_config_entry_attached(
        self, hass, mock_hub
    ):
        """Regression test for issue #557 — attach the entry to a reused hub.

        The config flow builds a VerisureHub with ``config_entry=None`` (the
        entry does not exist yet) and registers it in ``sessions``, held only
        by the flow.  When HA then sets up the freshly-created entry,
        ``_get_or_create_session`` reuses that detached hub.  It MUST attach
        the entry, otherwise ``_persist_refresh_token`` reports
        ``no-config-entry``, rotated refresh tokens are never written to the
        entry, and the stale original token triggers the ``xSRefreshLogin``
        'fr' crash on the next restart.
        """
        data = make_config_entry_data()
        data[CONF_INSTALLATION] = "111"
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        # Simulate the config flow having stored a detached hub in sessions.
        mock_hub.config_entry = None
        username = data[CONF_USERNAME]
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN].setdefault("sessions", {})[username] = {
            "hub": mock_hub,
            "holders": {"config_flow:flow-id"},
        }

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
        # The reused config-flow hub must now own the config entry so that
        # rotated refresh tokens are persisted rather than dropped.
        assert mock_hub.config_entry is entry
        # Reuse path: no fresh login, and the entry holds the flow's hub too.
        mock_hub.login.assert_not_awaited()
        assert hass.data[DOMAIN]["sessions"][username]["holders"] == {
            "config_flow:flow-id",
            entry.entry_id,
        }

    async def _set_up_on_detached_hub(self, hass, mock_hub, stored_token):
        data = make_config_entry_data()
        data[CONF_REFRESH_TOKEN] = stored_token
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)
        mock_hub.config_entry = None
        hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})[
            data[CONF_USERNAME]
        ] = {"hub": mock_hub, "holders": {"config_flow:flow-id"}}
        written_to: list = []
        mock_hub.persist_current_refresh_token.side_effect = lambda: written_to.append(
            mock_hub.config_entry
        )
        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch("custom_components.securitas._login_or_raise", AsyncMock()),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            assert await async_setup_entry(hass, entry) is True
        return entry, written_to

    async def test_attaching_a_reused_hub_writes_its_current_token(
        self, hass, mock_hub
    ):
        """The hub's token may have rotated past the one the entry stored; the
        entry must hold the current one at once, not after the next rotation."""
        mock_hub.get_refresh_token.return_value = "current-token"

        entry, written_to = await self._set_up_on_detached_hub(
            hass, mock_hub, stored_token="older-token"
        )

        assert mock_hub.config_entry is entry
        assert written_to == [entry]

    async def test_attaching_a_reused_hub_keeps_the_entry_token_over_a_refused_one(
        self, hass, mock_hub
    ):
        mock_hub.refresh_refusals_persisting = True
        mock_hub.get_refresh_token.return_value = "dead-token"

        entry, written_to = await self._set_up_on_detached_hub(
            hass, mock_hub, stored_token="own-stored-token"
        )

        assert mock_hub.config_entry is entry
        mock_hub.adopt_refresh_token.assert_called_once_with("own-stored-token")
        assert written_to == []

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

        # The first login waits until released, so the second setup runs while
        # it is in flight; only the account lock keeps it from signing in too.
        login_started, release_login = asyncio.Event(), asyncio.Event()

        async def _blocking_login(*_args, **_kwargs):
            login_started.set()
            await release_login.wait()

        mock_hub.login.side_effect = _blocking_login

        # Whether the account's lock was already held each time it was asked
        # for; ``async with`` acquires it straight after, so a held lock means
        # that caller waits.
        lock_was_held: list[bool] = []
        second_lock_request = asyncio.Event()

        def _watched_account_lock(hass_, username):
            lock = _account_lock(hass_, username)
            lock_was_held.append(lock.locked())
            if len(lock_was_held) == 2:
                second_lock_request.set()
            return lock

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
            patch(
                "custom_components.securitas._account_lock",
                side_effect=_watched_account_lock,
            ),
        ):
            # Run both setup calls concurrently, simulating HA restart
            setups = asyncio.gather(
                async_setup_entry(hass, entry1),
                async_setup_entry(hass, entry2),
                return_exceptions=True,
            )
            try:
                await asyncio.wait_for(login_started.wait(), 2)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(second_lock_request.wait(), 2)
                assert second_lock_request.is_set(), (
                    "the second setup never asked for the account lock; "
                    f"logins so far: {mock_hub.login.await_count}"
                )
                assert lock_was_held == [False, True]
                assert mock_hub.login.await_count == 1
            finally:
                release_login.set()
                results = await asyncio.wait_for(setups, 5)
                for result in results:
                    if isinstance(result, BaseException):
                        raise result

        assert results == [True, True]
        mock_hub.login.assert_awaited_once()
        username = data1[CONF_USERNAME]
        sessions = hass.data[DOMAIN]["sessions"]
        assert sessions[username]["holders"] == {entry1.entry_id, entry2.entry_id}
        # Both entries should reference the same hub
        assert hass.data[DOMAIN][entry1.entry_id]["hub"] is mock_hub
        assert hass.data[DOMAIN][entry2.entry_id]["hub"] is mock_hub

    async def test_unload_one_entry_drops_only_its_own_holder(self, hass, mock_hub):
        """Unloading one entry should drop its holder but keep the session."""
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
        holders = hass.data[DOMAIN]["sessions"][username]["holders"]
        assert holders == {entry1.entry_id, entry2.entry_id}

        # Unload entry1
        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await async_unload_entry(hass, entry1)

        assert result is True
        # Session should still exist, held by the entry that did not unload
        assert username in hass.data[DOMAIN]["sessions"]
        assert hass.data[DOMAIN]["sessions"][username]["holders"] == {entry2.entry_id}
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
        assert len(hass.data[DOMAIN]["sessions"][username]["holders"]) == 1

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
        assert isinstance(devices[0], VerisureDevice)
        # Old backward-compat keys should NOT be present
        assert VerisureHub.__name__ not in hass.data[DOMAIN]

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
        """v1 entry is rejected and notifies the user via translation key."""
        data = make_config_entry_data(username="user@example.com")

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            unique_id="user@example.com",
            version=1,
        )
        entry.add_to_hass(hass)

        with patch("custom_components.securitas._notify") as mock_notify:
            result = await async_migrate_entry(hass, entry)

        assert result is False
        # Entry version remains unchanged
        assert entry.version == 1
        mock_notify.assert_called_once_with(
            hass, "migration_required", "migration_required"
        )

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

        with patch("custom_components.securitas._notify"):
            result = await async_migrate_entry(hass, entry)

        assert result is False
        assert entry.version == 2

    async def test_migration_v3_migrated_to_v5_strips_legacy_token(self, hass):
        """v3 chains through v4 (drops CONF_TOKEN) straight to v5 in one call.

        CONF_PASSWORD is left in place: the next successful login will capture
        a refresh token and the persist-callback strips the password then.
        Doing it here would force a network login from inside async_migrate_entry,
        which is fragile (offline boots, account-blocked, etc.). The fixture's
        code is already in hashed form (make_config_entry_data hashes it), so
        the v4→v5 step is a no-op here — see TestCodeHashMigration for the
        legacy-plaintext-code cases.
        """
        from homeassistant.const import CONF_TOKEN

        data = make_config_entry_data(username="user@example.com")
        data[CONF_INSTALLATION] = "123456"
        data[CONF_TOKEN] = "stale-jwt"  # legacy dead write from older versions

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            unique_id="user@example.com_123456",
            version=3,
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 5
        assert entry.minor_version == 2
        assert CONF_TOKEN not in entry.data
        # CONF_PASSWORD intentionally retained — first setup login removes it.
        assert CONF_PASSWORD in entry.data

    async def test_migration_v5_accepted(self, hass):
        """v5 entry passes through unchanged (current version)."""
        data = make_config_entry_data(username="user@example.com")
        data[CONF_INSTALLATION] = "123456"

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            unique_id="user@example.com_123456",
            version=5,
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 5


def _minor_1_entry(hass, username, unique_id, installation="123456", title="Home"):
    """Add a v5.1 entry (saved before the 5.2 entry-ID migration) to hass."""
    data = make_config_entry_data(username=username)
    if username is None:
        del data[CONF_USERNAME]
    if installation is not None:
        data[CONF_INSTALLATION] = installation
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        unique_id=unique_id,
        title=title,
        version=5,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    return entry


class TestEntryIdMigration:
    """The v5.1 → v5.2 step: the entry ID rebuilt from the saved login, which
    is kept exactly as typed."""

    async def test_minor_2_migration_keeps_the_login_as_typed(self, hass):
        """Verisure Italy rejects a registered email typed in other capitals,
        so lower-casing a saved login could stop it signing in."""
        entry = _minor_1_entry(hass, "User@Example.com", "User@Example.com_123456")
        data_before = dict(entry.data)

        assert await async_migrate_entry(hass, entry) is True

        assert dict(entry.data) == data_before
        assert entry.unique_id == "User@Example.com_123456"
        assert (entry.version, entry.minor_version) == (5, 2)

    async def test_minor_2_migration_rebuilds_an_entry_id_left_from_an_account_switch(
        self, hass
    ):
        """An earlier release switched an entry's account on reauth without
        moving its ID off the old email."""
        entry = _minor_1_entry(hass, "New@example.com", "old@example.com_123456")

        assert await async_migrate_entry(hass, entry) is True

        assert entry.unique_id == "New@example.com_123456"

    async def test_minor_2_migration_tolerates_missing_username_and_installation(
        self, hass
    ):
        entry = _minor_1_entry(hass, None, "Legacy-ID", installation=None)

        assert await async_migrate_entry(hass, entry) is True

        assert CONF_USERNAME not in entry.data
        assert entry.unique_id == "Legacy-ID"
        assert entry.minor_version == 2

    async def test_minor_2_migration_ignores_entries_without_an_id(self, hass):
        """Entries with neither an email, an installation nor an entry ID
        keep no ID and still move to 5.2."""
        first = _minor_1_entry(hass, None, None, installation=None)
        second = _minor_1_entry(hass, None, None, installation=None)

        with patch("custom_components.securitas._notify") as mock_notify:
            assert await async_migrate_entry(hass, first) is True
            assert await async_migrate_entry(hass, second) is True

        assert (first.unique_id, second.unique_id) == (None, None)
        assert (first.minor_version, second.minor_version) == (2, 2)
        mock_notify.assert_not_called()

    @pytest.mark.parametrize("migrate_older_first", [True, False])
    async def test_minor_2_migration_keeps_both_entries_of_a_duplicate(
        self, hass, migrate_older_first
    ):
        """Two entries switched on reauth to the same account: whichever set
        up first owns the entities, so neither is removed. Both keep distinct
        entry IDs, and the migration posts no notification: a Repairs issue
        raised at setup asks the user to remove one."""
        older = _minor_1_entry(hass, "user@example.com", "old@example.com_123456")
        newer = _minor_1_entry(hass, "user@example.com", "other@example.com_123456")
        order = [older, newer] if migrate_older_first else [newer, older]
        second_id = order[1].unique_id

        with patch("custom_components.securitas._notify") as mock_notify:
            for entry in order:
                assert await async_migrate_entry(hass, entry) is True
            await hass.async_block_till_done()

        assert {e.entry_id for e in hass.config_entries.async_entries(DOMAIN)} == {
            older.entry_id,
            newer.entry_id,
        }
        assert order[0].unique_id == "user@example.com_123456"
        assert order[1].unique_id == second_id
        mock_notify.assert_not_called()

    async def test_minor_2_migration_keeps_an_entry_off_an_id_already_held(self, hass):
        """An entry already holding the rebuilt ID keeps it; the entry left
        with an old ID keeps its own."""
        holder = _minor_1_entry(hass, "user@example.com", "user@example.com_123456")
        switched = _minor_1_entry(hass, "user@example.com", "old@example.com_123456")

        with patch("custom_components.securitas._notify") as mock_notify:
            assert await async_migrate_entry(hass, switched) is True
            assert await async_migrate_entry(hass, holder) is True

        assert holder.unique_id == "user@example.com_123456"
        assert switched.unique_id == "old@example.com_123456"
        mock_notify.assert_not_called()


def _entry_for(hass, username, installation="123456", title="Home", unique_id=None):
    """Add an entry for one installation on one account to hass; ``unique_id``
    stands in for one left from an earlier account switch."""
    data = make_config_entry_data(username=username)
    data[CONF_INSTALLATION] = installation
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        unique_id=unique_id or f"{username}_{installation}",
        title=title,
        version=5,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    return entry


def _duplicate_entry_issues(hass):
    return {
        issue_id: issue
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue_id.startswith("duplicate_entry_")
    }


_CLASH_ISSUE_ID = (
    "duplicate_entry_" + hashlib.sha256(b"user@example.com_123456").hexdigest()[:12]
)


class TestDuplicateEntryIssue:
    """One installation held by two entries on the same account (an entry
    signed in again to the account the other uses) is flagged in Repairs for
    as long as both entries exist."""

    @pytest.fixture
    def mock_hub(self):
        hub = make_securitas_hub_mock()
        hub.client.list_installations = AsyncMock(return_value=[make_installation()])
        return hub

    @pytest.fixture
    def set_up(self, hass, mock_hub):
        async def _set_up(*entries):
            with (
                _patch_hub(mock_hub),
                patch("custom_components.securitas.async_get_clientsession"),
                patch.object(
                    hass.config_entries,
                    "async_forward_entry_setups",
                    new_callable=AsyncMock,
                ),
            ):
                for entry in entries:
                    assert await async_setup_entry(hass, entry) is True

        return _set_up

    async def test_two_entries_for_one_installation_raise_one_issue(self, hass, set_up):
        first = _entry_for(hass, "user@example.com", unique_id="old@example.com_123456")
        second = _entry_for(hass, "user@example.com")

        await set_up(first, second)

        issues = _duplicate_entry_issues(hass)
        assert list(issues) == [_CLASH_ISSUE_ID]
        issue = issues[_CLASH_ISSUE_ID]
        assert issue.is_fixable is False
        assert issue.is_persistent is False
        assert issue.severity == ir.IssueSeverity.WARNING
        assert issue.translation_key == "duplicate_entry"
        assert issue.translation_placeholders == {"installation": "Home"}
        # Home Assistant saves issue IDs and data; the email must stay out.
        assert "@" not in _CLASH_ISSUE_ID

    async def test_removing_one_of_the_entries_clears_the_issue(
        self, hass, set_up, enable_custom_integrations
    ):
        first = _entry_for(hass, "user@example.com", unique_id="old@example.com_123456")
        second = _entry_for(hass, "user@example.com")
        await set_up(first, second)
        assert list(_duplicate_entry_issues(hass)) == [_CLASH_ISSUE_ID]

        await hass.config_entries.async_remove(second.entry_id)
        await hass.async_block_till_done()

        assert _duplicate_entry_issues(hass) == {}

    async def test_the_entry_being_removed_no_longer_counts(self, hass, set_up):
        first = _entry_for(hass, "user@example.com", unique_id="old@example.com_123456")
        second = _entry_for(hass, "user@example.com")
        await set_up(first, second)
        assert list(_duplicate_entry_issues(hass)) == [_CLASH_ISSUE_ID]

        await async_remove_entry(hass, second)

        assert _duplicate_entry_issues(hass) == {}

    async def test_logins_in_other_capitals_raise_no_issue(self, hass, set_up):
        """Two spellings Verisure both accepts are two logins, not one
        account added twice."""
        first = _entry_for(hass, "User@Example.com")
        second = _entry_for(hass, "user@example.com")

        await set_up(first, second)

        assert _duplicate_entry_issues(hass) == {}

    async def test_different_installations_raise_no_issue(self, hass, set_up):
        home = _entry_for(hass, "user@example.com", "123456", "Home")
        office = _entry_for(hass, "user@example.com", "654321", "Office")

        await set_up(home, office)

        assert _duplicate_entry_issues(hass) == {}

    async def test_a_single_entry_raises_no_issue(self, hass, set_up):
        await set_up(_entry_for(hass, "user@example.com"))

        assert _duplicate_entry_issues(hass) == {}

    async def test_entries_without_an_id_do_not_clash(self, hass, set_up):
        """Entries with neither an email, an installation nor an entry ID
        have nothing to clash on."""
        for _ in range(2):
            MockConfigEntry(
                domain=DOMAIN, data={}, version=5, minor_version=2
            ).add_to_hass(hass)

        await set_up(_entry_for(hass, "user@example.com"))

        assert _duplicate_entry_issues(hass) == {}

    async def test_a_stale_issue_is_cleared_on_the_next_setup(self, hass, set_up):
        ir.async_create_issue(
            hass,
            DOMAIN,
            _CLASH_ISSUE_ID,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="duplicate_entry",
            translation_placeholders={"installation": "Home"},
        )

        await set_up(_entry_for(hass, "user@example.com"))

        assert _duplicate_entry_issues(hass) == {}


def _sign_in_issues(hass):
    """The Repairs issues asking to sign an account in again, blocked or not."""
    return {
        issue_id: issue
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue_id.startswith("sign_in_again_")
    }


_SIGN_IN_ISSUE_ID = (
    "sign_in_again_" + hashlib.sha256(b"test@example.com").hexdigest()[:12]
)


def _renewal_refused_issues(hass):
    return {
        issue_id: issue
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue_id.startswith("renewal_refused_")
    }


_RENEWAL_REFUSED_ISSUE_ID = (
    "renewal_refused_" + hashlib.sha256(b"test@example.com").hexdigest()[:12]
)


class TestSignInIssue:
    """A login setup cannot complete raises a Repairs issue saying why Home
    Assistant asks to sign the account in again. A sign-in that works, or no
    entry left on the account, clears it."""

    @pytest.fixture
    def mock_hub(self):
        hub = make_securitas_hub_mock()
        hub.client.list_installations = AsyncMock(return_value=[make_installation()])
        return hub

    async def _set_up(self, hass, entry, mock_hub):
        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            return await async_setup_entry(hass, entry)

    async def _fail(self, hass, entry, mock_hub, error):
        mock_hub.login = AsyncMock(side_effect=error)
        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            pytest.raises(ConfigEntryAuthFailed),
        ):
            await async_setup_entry(hass, entry)
        mock_hub.login = AsyncMock()

    @pytest.mark.parametrize(
        ("error", "reason"),
        [
            (TwoFactorRequiredError("2FA required"), "2FA required"),
            (AuthenticationError("bad credentials"), "Authentication failed"),
        ],
        ids=["code-needed", "login-rejected"],
    )
    async def test_a_rejected_login_raises_a_sign_in_repair_not_a_notification(
        self, hass, mock_hub, error, reason
    ):
        """Home Assistant asks to sign in again (ConfigEntryAuthFailed); the
        integration adds a plain-language Repairs issue saying why, rather than
        a notification quoting Verisure's error."""
        mock_hub.login = AsyncMock(side_effect=error)
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch("custom_components.securitas._notify") as mock_notify,
            pytest.raises(ConfigEntryAuthFailed, match=reason),
        ):
            await async_setup_entry(hass, entry)

        mock_notify.assert_not_called()
        issues = _sign_in_issues(hass)
        assert list(issues) == [_SIGN_IN_ISSUE_ID]
        issue = issues[_SIGN_IN_ISSUE_ID]
        assert issue.is_fixable is False
        # The username placeholder is the email; Home Assistant saves the
        # placeholders of persistent issues only.
        assert issue.is_persistent is False
        assert issue.severity == ir.IssueSeverity.ERROR
        assert issue.translation_key == "sign_in_again"
        assert issue.translation_placeholders == {"username": "test@example.com"}
        assert "@" not in _SIGN_IN_ISSUE_ID

    @pytest.mark.parametrize(
        "error",
        [
            TwoFactorRequiredError("2FA required"),
            AuthenticationError("bad credentials"),
            AccountBlockedError("blocked"),
        ],
        ids=["code-needed", "login-rejected", "blocked"],
    )
    async def test_a_sign_in_repair_replaces_the_unreachable_notice(
        self, hass, mock_hub, error
    ):
        """One problem, one notice: the sign-in issue removes the account's
        "can't reach Verisure" notice."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        raise_unreachable_issue(hass, "test@example.com")
        assert list(_unreachable_issues(hass)) == [_UNREACHABLE_ISSUE_ID]

        await self._fail(hass, entry, mock_hub, error)

        assert list(_sign_in_issues(hass)) == [_SIGN_IN_ISSUE_ID]
        assert _unreachable_issues(hass) == {}

    async def test_a_blocked_account_raises_a_repair_saying_how_to_unblock_it(
        self, hass, mock_hub
    ):
        """Signing in again with the same password fails while Verisure blocks
        the account, so its issue says to unblock it first."""
        mock_hub.login = AsyncMock(side_effect=AccountBlockedError("blocked"))
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            pytest.raises(ConfigEntryAuthFailed, match="Authentication failed"),
        ):
            await async_setup_entry(hass, entry)

        assert [d for d, _ in ir.async_get(hass).issues if d == DOMAIN] == [DOMAIN]
        issues = _sign_in_issues(hass)
        assert list(issues) == [_SIGN_IN_ISSUE_ID]
        issue = issues[_SIGN_IN_ISSUE_ID]
        assert issue.is_persistent is False
        assert issue.severity == ir.IssueSeverity.ERROR
        assert issue.translation_key == "account_blocked"
        assert issue.translation_placeholders == {"username": "test@example.com"}

    @pytest.mark.parametrize(
        "error",
        [AuthenticationError("bad credentials"), AccountBlockedError("blocked")],
        ids=["login-rejected", "account-blocked"],
    )
    async def test_a_successful_sign_in_clears_the_sign_in_repair(
        self, hass, mock_hub, error
    ):
        """Once the account signs in again, the issue has nothing left to say."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        await self._fail(hass, entry, mock_hub, error)
        assert list(_sign_in_issues(hass)) == [_SIGN_IN_ISSUE_ID]

        assert await self._set_up(hass, entry, mock_hub) is True

        mock_hub.login.assert_awaited_once()
        assert _sign_in_issues(hass) == {}

    @pytest.mark.parametrize("error_type", [AuthenticationError, AccountBlockedError])
    async def test_reusing_a_shared_session_whose_token_was_refused_keeps_it(
        self, hass, error_type
    ):
        """The shared session's token keeps being refused, and this entry's
        own token, adopted to replace it, is rejected: the shared token is put
        back. A co-tenant's setup then reuses the session without signing in,
        which proves nothing: the issue stays."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_USERNAME: "test@example.com", CONF_REFRESH_TOKEN: "replacement"},
        )
        entry.add_to_hass(hass)
        other = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_USERNAME: "test@example.com", CONF_REFRESH_TOKEN: "condemned"},
        )
        other.add_to_hass(hass)
        hub = make_hub(mock_client=False)
        hub.hass = hass
        hub.config_entry = entry
        hub.client.password = ""
        hub.client.refresh_token_value = "condemned"
        hub.client._refusals_persisting = True
        hub.client.refresh_token = AsyncMock(side_effect=error_type("rejected"))
        session = _new_session_record(hub)
        session["holders"].add(other.entry_id)
        hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})[
            "test@example.com"
        ] = session

        with pytest.raises(AuthenticationError):
            await _get_or_create_session(hass, dict(entry.data), entry)
        assert list(_sign_in_issues(hass)) == [_SIGN_IN_ISSUE_ID]
        assert hub.get_refresh_token() == "condemned"

        await _get_or_create_session(hass, dict(other.data), other)

        assert hub.client.refresh_token.await_count == 1
        assert list(_sign_in_issues(hass)) == [_SIGN_IN_ISSUE_ID]

    async def test_signing_in_as_another_account_clears_the_first_accounts_repair(
        self, hass, mock_hub
    ):
        """Signing the entry in again as another account leaves no entry on
        the first one, so its issue has nothing left to say."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        await self._fail(hass, entry, mock_hub, AuthenticationError("bad credentials"))
        assert list(_sign_in_issues(hass)) == [_SIGN_IN_ISSUE_ID]
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_USERNAME: "other@example.com"}
        )

        assert await self._set_up(hass, entry, mock_hub) is True

        assert _sign_in_issues(hass) == {}

    async def test_deleting_the_accounts_last_entry_clears_the_sign_in_repair(
        self, hass, mock_hub
    ):
        """Nothing is left to sign in again once the account's last entry is
        gone; another account's issue stays."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        other = MockConfigEntry(
            domain=DOMAIN, data=make_config_entry_data(username="other@example.com")
        )
        other.add_to_hass(hass)
        for failing in (entry, other):
            await self._fail(
                hass, failing, mock_hub, AuthenticationError("bad credentials")
            )
        assert len(_sign_in_issues(hass)) == 2

        await async_remove_entry(hass, entry)

        assert [i.translation_placeholders for i in _sign_in_issues(hass).values()] == [
            {"username": "other@example.com"}
        ]

    async def test_deleting_the_accounts_last_entry_clears_its_renewal_repair(
        self, hass
    ):
        """The renewal-refused notice goes with the account's last entry, by
        the same rule as the sign-in one; another account's stays."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        other = MockConfigEntry(
            domain=DOMAIN, data=make_config_entry_data(username="other@example.com")
        )
        other.add_to_hass(hass)
        raise_renewal_refused_issue(hass, "test@example.com")
        raise_renewal_refused_issue(hass, "other@example.com")

        await async_remove_entry(hass, entry)

        assert [
            i.translation_placeholders for i in _renewal_refused_issues(hass).values()
        ] == [{"username": "other@example.com"}]

    async def test_a_successful_sign_in_clears_the_renewal_repair(self, hass, mock_hub):
        """A sign-in at setup proves the account works again."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        raise_renewal_refused_issue(hass, "test@example.com")
        assert list(_renewal_refused_issues(hass)) == [_RENEWAL_REFUSED_ISSUE_ID]

        assert await self._set_up(hass, entry, mock_hub) is True

        mock_hub.login.assert_awaited_once()
        assert _renewal_refused_issues(hass) == {}


class TestCodeHashMigration:
    """Tests for the v4→v5 migration step that hashes a legacy plain-text PIN."""

    async def test_plaintext_code_in_data_is_hashed(self, hass):
        """A plain-text CONF_CODE in entry.data is replaced by its hash."""
        data = make_config_entry_data(username="user@example.com")
        data[CONF_INSTALLATION] = "123456"
        del data[CONF_CODE_HASH]
        del data[CONF_CODE_IS_NUMERIC]
        data["code"] = "1234"  # legacy plain-text key, pre-migration shape

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            unique_id="user@example.com_123456",
            version=4,
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 5
        assert "code" not in entry.data
        assert verify_pin("1234", entry.data[CONF_CODE_HASH])
        assert entry.data[CONF_CODE_IS_NUMERIC] is True

    async def test_plaintext_code_in_options_is_hashed(self, hass):
        """A plain-text CONF_CODE left in entry.options (post options-flow
        legacy entries) is hashed too, not just entry.data."""
        data = make_config_entry_data(username="user@example.com")
        data[CONF_INSTALLATION] = "123456"

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            options={"code": "abcd"},
            unique_id="user@example.com_123456",
            version=4,
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 5
        assert "code" not in entry.options
        assert verify_pin("abcd", entry.options[CONF_CODE_HASH])
        assert entry.options[CONF_CODE_IS_NUMERIC] is False

    async def test_no_code_migrates_cleanly(self, hass):
        """A v4 entry with no PIN configured migrates to v5 without
        introducing a spurious hash."""
        data = make_config_entry_data(username="user@example.com")
        data[CONF_INSTALLATION] = "123456"
        del data[CONF_CODE_HASH]
        del data[CONF_CODE_IS_NUMERIC]

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            unique_id="user@example.com_123456",
            version=4,
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 5
        assert CONF_CODE_HASH not in entry.data

    async def test_same_pin_in_data_and_options_yields_one_hash(self, hass):
        """A PIN present in both mappings is hashed once, not twice.

        Hashing is salted, so hashing each mapping independently would leave
        data and options holding different encodings of the same PIN. That
        makes ``_synced_entry_data`` see a diff where there is none, costing
        every upgrading user with a PIN a spurious entry reload.
        """
        data = make_config_entry_data(username="user@example.com")
        data[CONF_INSTALLATION] = "123456"
        del data[CONF_CODE_HASH]
        del data[CONF_CODE_IS_NUMERIC]
        data["code"] = "1234"

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            options={"code": "1234"},
            unique_id="user@example.com_123456",
            version=4,
        )
        entry.add_to_hass(hass)

        assert await async_migrate_entry(hass, entry) is True

        assert entry.data[CONF_CODE_HASH] == entry.options[CONF_CODE_HASH]
        assert verify_pin("1234", entry.data[CONF_CODE_HASH])

    async def test_different_pins_in_data_and_options_stay_distinct(self, hass):
        """Sharing a hash must not collapse two genuinely different PINs."""
        data = make_config_entry_data(username="user@example.com")
        data[CONF_INSTALLATION] = "123456"
        del data[CONF_CODE_HASH]
        del data[CONF_CODE_IS_NUMERIC]
        data["code"] = "1111"

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            options={"code": "2222"},
            unique_id="user@example.com_123456",
            version=4,
        )
        entry.add_to_hass(hass)

        assert await async_migrate_entry(hass, entry) is True

        assert verify_pin("1111", entry.data[CONF_CODE_HASH])
        assert verify_pin("2222", entry.options[CONF_CODE_HASH])

    @pytest.mark.parametrize(
        "legacy_value",
        [1234, ["1234"], {"pin": "1234"}, None],
        ids=["int", "list", "dict", "null"],
    )
    async def test_non_string_legacy_code_does_not_abort_migration(
        self, hass, legacy_value
    ):
        """A corrupt CONF_CODE must not take the whole entry down.

        An int reaches hash_pin and dies on .encode(); a list isn't hashable
        and dies as a memo key. Either raises out of async_migrate_entry, so
        HA marks the entry failed and the integration doesn't load at all —
        a far worse outcome than an unusable PIN the user can simply clear.
        """
        data = make_config_entry_data(username="user@example.com")
        data[CONF_INSTALLATION] = "123456"
        del data[CONF_CODE_HASH]
        del data[CONF_CODE_IS_NUMERIC]
        data["code"] = legacy_value

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            unique_id="user@example.com_123456",
            version=4,
        )
        entry.add_to_hass(hass)

        assert await async_migrate_entry(hass, entry) is True
        assert entry.version == 5
        assert "code" not in entry.data
        # Whatever it becomes, the entry stays loadable and the key is present.
        assert CONF_CODE_HASH in entry.data

    async def test_pin_cleared_in_options_is_not_resurrected(self, hass):
        """An empty CONF_CODE in options must keep shadowing the one in data.

        ``_opt()`` reads options first, then data — so a *present but empty*
        ``options["code"]`` means "the user removed the PIN" and shadows a
        stale ``data["code"]``. Hashing only non-empty values would leave
        CONF_CODE_HASH absent from options, which stops shadowing and brings
        the old PIN back to life.
        """
        data = make_config_entry_data(username="user@example.com")
        data[CONF_INSTALLATION] = "123456"
        del data[CONF_CODE_HASH]
        del data[CONF_CODE_IS_NUMERIC]
        data["code"] = "1234"

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            options={"code": ""},
            unique_id="user@example.com_123456",
            version=4,
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.options[CONF_CODE_HASH] is None
        config, _ = _build_config_dict(entry)
        assert config[CONF_CODE_HASH] is None


class TestYamlConfigSchema:
    """The YAML schema is inert — ``async_setup`` ignores its config entirely.

    Kept only so a legacy ``securitas:`` block doesn't fail config validation
    at startup, which is why it must tolerate keys it no longer declares.
    """

    def test_legacy_plaintext_code_key_still_validates(self):
        """A leftover YAML ``code:`` must not break startup after the key was
        dropped from the schema — it's ignored, not rejected."""
        config = {
            DOMAIN: {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "secret",
                "code": "1234",
            }
        }

        assert CONFIG_SCHEMA(config) is not None

    def test_schema_no_longer_declares_a_pin_field(self):
        """The PIN is never read from YAML, and must never be invited there."""
        keys = {
            getattr(marker, "schema", marker)
            for marker in CONFIG_SCHEMA.schema[DOMAIN].schema
        }
        assert "code" not in keys


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
        mock_hub1.client.list_installations = AsyncMock(
            return_value=[make_installation()]
        )
        mock_hub2 = make_securitas_hub_mock()
        mock_hub2.client.list_installations = AsyncMock(
            return_value=[make_installation(number="654321")]
        )

        # Set up entry1
        mock_cls1 = MagicMock(return_value=mock_hub1)
        mock_cls1.__name__ = "VerisureHub"
        with (
            patch("custom_components.securitas.VerisureHub", mock_cls1),
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
        mock_cls2.__name__ = "VerisureHub"
        with (
            patch("custom_components.securitas.VerisureHub", mock_cls2),
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
        mock_hub_es.client.list_installations = AsyncMock(
            return_value=[make_installation()]
        )
        mock_hub_it = make_securitas_hub_mock()
        mock_hub_it.client.list_installations = AsyncMock(
            return_value=[make_installation(number="654321")]
        )

        # Set up ES entry
        mock_cls_es = MagicMock(return_value=mock_hub_es)
        mock_cls_es.__name__ = "VerisureHub"
        with (
            patch("custom_components.securitas.VerisureHub", mock_cls_es),
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
        mock_cls_it.__name__ = "VerisureHub"
        with (
            patch("custom_components.securitas.VerisureHub", mock_cls_it),
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


# ===========================================================================
# _discover_cameras tests
# ===========================================================================


class TestDiscoverCameras:
    """Tests for _discover_cameras() background discovery function."""

    @pytest.mark.asyncio
    async def test_empty_camera_list_adds_no_entities(self):
        """When no cameras are found, camera_add_entities must not be called."""
        from custom_components.securitas import _discover_cameras
        from tests.conftest import make_installation

        hass = MagicMock()
        hub = MagicMock()
        hub.get_camera_devices = AsyncMock(return_value=[])
        camera_add = MagicMock()
        button_add = MagicMock()
        entry_data = {
            "camera_add_entities": camera_add,
            "button_add_entities": button_add,
        }
        entry = MagicMock()

        await _discover_cameras(hass, hub, make_installation(), entry_data, entry)

        camera_add.assert_not_called()
        button_add.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_from_get_camera_devices_is_caught(self, caplog):
        """An exception in get_camera_devices must not propagate — log warning and continue."""
        import logging

        from custom_components.securitas import _discover_cameras
        from tests.conftest import make_installation

        hass = MagicMock()
        hub = MagicMock()
        hub.get_camera_devices = AsyncMock(side_effect=Exception("network failure"))
        camera_add = MagicMock()
        button_add = MagicMock()
        entry_data = {
            "camera_add_entities": camera_add,
            "button_add_entities": button_add,
        }
        entry = MagicMock()

        with caplog.at_level(logging.WARNING, logger="custom_components.securitas"):
            # Must not raise
            await _discover_cameras(hass, hub, make_installation(), entry_data, entry)

        assert "Failed to get camera devices" in caplog.text
        camera_add.assert_not_called()
        button_add.assert_not_called()


class TestLockConfigRetry:
    """Tests for lock-config retry lifecycle ownership."""

    def test_cancel_callback_is_owned_by_entity_and_entry(self, hass):
        """Either entity removal or unloading the lock's own entry can cancel a
        pending retry. The shared hub is attached to whichever entry on the
        account signed in first, which may be another one (#643)."""
        from custom_components.securitas import _schedule_lock_config_retry

        hub = make_securitas_hub_mock()
        hub.config_entry = MagicMock()
        lock_entity = MagicMock()
        lock_entity.device_id = "1"
        own_entry = lock_entity.coordinator.config_entry
        cancel = MagicMock()

        with patch("homeassistant.helpers.event.async_call_later", return_value=cancel):
            _schedule_lock_config_retry(
                hass,
                hub,
                make_installation(),
                lock_entity,
            )

        lock_entity.async_on_remove.assert_called_once_with(cancel)
        own_entry.async_on_unload.assert_called_once_with(cancel)
        hub.config_entry.async_on_unload.assert_not_called()

    async def test_retry_waits_as_long_as_the_locks_entry_says(self, hass):
        """The shared hub's client carries the first entry's operation
        timeout, so the retry passes the lock's own entry's timeout (#643)."""
        from custom_components.securitas import _schedule_lock_config_retry
        from custom_components.securitas.const import CONF_OPERATION_POLL_TIMEOUT
        from tests.test_ha_platforms import make_lock

        hub = make_securitas_hub_mock()
        hub.api_queue = MagicMock()
        hub.get_lock_config = AsyncMock(return_value=None)
        lock_entity = make_lock(
            config={"scan_interval": 120, CONF_OPERATION_POLL_TIMEOUT: 7}
        )
        lock_entity.async_on_remove = MagicMock()
        installation = make_installation()

        with patch("homeassistant.helpers.event.async_call_later") as call_later:
            _schedule_lock_config_retry(hass, hub, installation, lock_entity)
            retry = call_later.call_args.args[2]
            await retry(None)

        assert hub.get_lock_config.await_args.kwargs["poll_timeout"] == 7.0


class TestDiscoverLocks:
    """Tests for lock discovery."""

    async def test_lock_config_fetch_waits_as_long_as_the_entry_says(self):
        """The shared hub's client carries the first entry's operation
        timeout, so discovery passes this entry's timeout (#643)."""
        from custom_components.securitas import _discover_locks
        from custom_components.securitas.const import CONF_OPERATION_POLL_TIMEOUT
        from custom_components.securitas.verisure_owa_api import (
            SmartLock,
            SmartLockMode,
        )

        hub = make_securitas_hub_mock()
        hub.api_queue = MagicMock()
        hub.get_services = AsyncMock(return_value=[MagicMock(request="DOORLOCK")])
        hub.get_lock_modes = AsyncMock(
            return_value=[SmartLockMode(lock_status="2", device_id="01")]
        )
        hub.get_lock_config = AsyncMock(return_value=SmartLock(res="OK"))
        entry_data = {
            "config": {CONF_OPERATION_POLL_TIMEOUT: 7},
            "lock_coordinator": MagicMock(),
            "lock_add_entities": MagicMock(),
        }

        with patch("custom_components.securitas.lock.VerisureLock"):
            await _discover_locks(MagicMock(), hub, make_installation(), entry_data)

        hub.get_lock_config.assert_awaited_once()
        assert hub.get_lock_config.await_args.kwargs["poll_timeout"] == 7.0


# ===========================================================================
# _async_discover_devices tests — ordering + completion signalling
# ===========================================================================


class TestAsyncDiscoverDevices:
    """Tests for _async_discover_devices() ordering and event signalling."""

    @pytest.mark.asyncio
    async def test_locks_discovered_before_cameras(self):
        """Locks must submit to the queue before cameras (options-flow latency).

        Locks gate the Lock Automation options step; cameras don't. Order the
        sequential awaits so a user opening options waits only on lock work.
        """
        import asyncio

        from custom_components.securitas import _async_discover_devices
        from custom_components.securitas.const import DOMAIN

        hass = MagicMock()
        hass.data = {DOMAIN: {}}

        call_order: list[str] = []

        async def fake_discover_cameras(*_args, **_kwargs):
            call_order.append("cameras")

        async def fake_discover_locks(*_args, **_kwargs):
            call_order.append("locks")

        entry = MagicMock()
        entry.entry_id = "entry-1"
        hass.data[DOMAIN][entry.entry_id] = {
            "hub": MagicMock(),
            "devices": [VerisureDevice(make_installation())],
            "lock_discovery_complete": asyncio.Event(),
        }

        with (
            patch(
                "custom_components.securitas.discovery._discover_cameras",
                new=fake_discover_cameras,
            ),
            patch(
                "custom_components.securitas.discovery._discover_locks",
                new=fake_discover_locks,
            ),
        ):
            await _async_discover_devices(hass, entry)

        assert call_order == ["locks", "cameras"], (
            f"Expected locks before cameras, got {call_order}"
        )

    @pytest.mark.asyncio
    async def test_lock_discovery_event_is_set_on_completion(self):
        """The lock_discovery_complete event must be set once discovery returns."""
        import asyncio

        from custom_components.securitas import _async_discover_devices
        from custom_components.securitas.const import DOMAIN

        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        event = asyncio.Event()
        entry = MagicMock()
        entry.entry_id = "entry-2"
        hass.data[DOMAIN][entry.entry_id] = {
            "hub": MagicMock(),
            "devices": [VerisureDevice(make_installation())],
            "lock_discovery_complete": event,
        }

        with (
            patch(
                "custom_components.securitas.discovery._discover_cameras",
                new=AsyncMock(),
            ),
            patch(
                "custom_components.securitas.discovery._discover_locks",
                new=AsyncMock(),
            ),
        ):
            await _async_discover_devices(hass, entry)

        assert event.is_set()

    @pytest.mark.asyncio
    async def test_lock_discovery_event_is_set_even_when_discovery_raises(self):
        """The event must be set even if _discover_locks raises — never hang options."""
        import asyncio

        from custom_components.securitas import _async_discover_devices
        from custom_components.securitas.const import DOMAIN

        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        event = asyncio.Event()
        entry = MagicMock()
        entry.entry_id = "entry-3"
        hass.data[DOMAIN][entry.entry_id] = {
            "hub": MagicMock(),
            "devices": [VerisureDevice(make_installation())],
            "lock_discovery_complete": event,
        }

        async def boom(*_args, **_kwargs):
            raise RuntimeError("discovery exploded")

        # Whether or not the function re-raises, the event must be set.
        with (
            patch(
                "custom_components.securitas.discovery._discover_cameras",
                new=AsyncMock(),
            ),
            patch(
                "custom_components.securitas.discovery._discover_locks",
                new=boom,
            ),
            contextlib.suppress(RuntimeError),
        ):
            await _async_discover_devices(hass, entry)

        assert event.is_set()


# ===========================================================================
# Phase F3: Static-URL alias
# ===========================================================================


class TestStaticPathAliases:
    """Verify that both /verisure-owa-panel and /securitas_panel are registered."""

    @pytest.fixture
    def mock_hub(self):
        """Create a mock VerisureHub for setup tests."""
        from tests.conftest import make_installation, make_securitas_hub_mock

        hub = make_securitas_hub_mock()
        hub.client.list_installations = AsyncMock(return_value=[make_installation()])
        return hub

    async def test_static_paths_register_both_new_and_legacy(self, hass, mock_hub):
        """Setup should register both /verisure-owa-panel and /securitas_panel."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

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
            patch("custom_components.securitas.frontend.add_extra_js_url"),
        ):
            result = await async_setup_entry(hass, entry)

        assert result is True
        hass.http.async_register_static_paths.assert_awaited_once()
        call_args = hass.http.async_register_static_paths.call_args[0][0]
        paths = [cfg.url_path for cfg in call_args]
        assert "/verisure-owa-panel" in paths
        assert "/securitas_panel" in paths


# ===========================================================================
# TestServiceTargetCompatibility
# ===========================================================================


class TestServiceTargetCompatibility:
    """Service target extraction supports both ends of the HA version range."""

    async def test_legacy_helper_receives_hass(self):
        import custom_components.securitas as integration

        hass = MagicMock()
        call = MagicMock()
        call.hass = hass
        extract = AsyncMock(return_value={"alarm_control_panel.home"})

        with (
            patch.object(integration, "_EXTRACT_ENTITY_IDS_REQUIRES_HASS", True),
            patch.object(integration, "async_extract_entity_ids", extract),
        ):
            result = await integration._async_extract_service_entity_ids(call)

        assert result == {"alarm_control_panel.home"}
        extract.assert_awaited_once_with(hass, call)

    async def test_current_helper_receives_only_service_call(self):
        import custom_components.securitas as integration

        call = MagicMock()
        extract = AsyncMock(return_value={"alarm_control_panel.home"})

        with (
            patch.object(integration, "_EXTRACT_ENTITY_IDS_REQUIRES_HASS", False),
            patch.object(integration, "async_extract_entity_ids", extract),
        ):
            result = await integration._async_extract_service_entity_ids(call)

        assert result == {"alarm_control_panel.home"}
        extract.assert_awaited_once_with(call)


# ===========================================================================
# TestServiceDescriptionTargets
# ===========================================================================


class TestServiceDescriptionTargets:
    """Regression guard: service ``target`` entity filters must be lists.

    These descriptions reach HA via ``async_set_service_schema``, which copies
    ``target`` through *unchanged* — unlike ``services.yaml``, which is
    validated by ``TargetSelector.CONFIG_SCHEMA`` and normalised with
    ``cv.ensure_list``. HA's automation-editor lookup
    (``_get_automation_component_domains``) iterates ``target["entity"]``
    expecting a list of ``{integration, domain}`` mappings; a bare mapping
    iterates to its *string keys* and raises ``AttributeError``, which aborts
    the shared cross-integration lookup and breaks the action/target picker for
    *every* integration while this one is loaded (PR #525).
    """

    def test_target_entity_filters_are_lists(self):
        """Every service ``target["entity"]`` must be a list of mapping filters."""
        from custom_components.securitas import (
            _ALIASED_SERVICES,
            _V5_ENTITY_SERVICES,
        )

        schemas = [(name, schema) for name, _sr, schema in _ALIASED_SERVICES]
        schemas += [
            (spec["service_name"], spec["schema"])
            for spec in _V5_ENTITY_SERVICES
            if spec.get("schema")
        ]
        targets = [
            (name, schema["target"]["entity"])
            for name, schema in schemas
            if schema.get("target", {}).get("entity") is not None
        ]

        # Guard against a vacuous pass if the specs move or lose their targets.
        assert targets, "no service target entity filters found — did the specs move?"

        for service_name, entity in targets:
            assert isinstance(entity, list), (
                f"{service_name}: target['entity'] must be a list of mapping "
                f"filters (async_set_service_schema does not run cv.ensure_list), "
                f"got {type(entity).__name__}"
            )
            assert entity and all(isinstance(item, dict) for item in entity), (
                f"{service_name}: target['entity'] must be a non-empty list of "
                "mapping filters"
            )
            # HA's entity-filter schema normalises `domain` with cv.ensure_list
            # (helpers/selector.py) — but only on the validated services.yaml
            # path. async_set_service_schema skips that, so a bare-string domain
            # reaches _AutomationComponentLookupData.create unchanged, where
            # `set(config.get("domain", []))` turns "alarm_control_panel" into a
            # set of single characters and the filter then matches no entity.
            for filt in entity:
                if "domain" in filt:
                    domain = filt["domain"]
                    assert isinstance(domain, list) and all(
                        isinstance(d, str) for d in domain
                    ), (
                        f"{service_name}: entity filter 'domain' must be a list "
                        f"of strings so it survives async_set_service_schema's "
                        f"unvalidated copy; got {domain!r}"
                    )


# ===========================================================================
# TestSetupRefreshRefusals
# ===========================================================================


class _Clock:
    """The time ``datetime.now()`` reports in setup and the client, moved by hand.

    Real time is kept in UTC; the local wall clock is Lisbon's, so moving
    across 01:00 UTC on 2026-10-25 sets it back an hour as daylight saving
    ends.
    """

    def __init__(self) -> None:
        self.utc = datetime(2026, 10, 16, 14, 44, tzinfo=UTC)

    def advance(self, **kwargs: float) -> None:
        self.utc += timedelta(**kwargs)


@pytest.fixture
def clock(monkeypatch):
    saved_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Lisbon"
    time.tzset()
    fake = _Clock()

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fake.utc.astimezone().replace(tzinfo=None)
            return fake.utc.astimezone(tz)

    monkeypatch.setattr(securitas_init, "datetime", _FakeDatetime)
    monkeypatch.setattr(client_base, "datetime", _FakeDatetime)
    yield fake
    if saved_tz is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved_tz
    time.tzset()


def _keep_another_account_loaded(hass, username="other@example.com") -> None:
    hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})[username] = {
        "hub": MagicMock(),
        "holders": {"other-account-entry-id"},
    }


_REFUSALS = pytest.mark.parametrize(
    "make_refusal",
    [
        refresh_token_rejected_error,
        refresh_token_rejected_err7_error,
        refresh_login_crash_error,
    ],
    ids=["err4", "err7", "crash"],
)

_ALERT_LOG = "Verisure has refused to renew the saved sign-in"


class TestSetupRefreshRefusals:
    """Verisure refusing the stored token at setup (err 4 or err 7, or the #568
    refresh-login crash) is retried for as long as it lasts, never turned into
    a reauth prompt.

    Once refusals have lasted 15 minutes a Repairs notice says how to sign in
    again. The tracking is per account and lives in hass.data, because each
    retry builds a fresh hub and entries on one account alternate as session
    creator.
    """

    @pytest.fixture
    def mock_hub(self):
        """Create a mock VerisureHub for setup tests."""
        hub = make_securitas_hub_mock()
        hub.client.list_installations = AsyncMock(return_value=[make_installation()])
        return hub

    async def _attempt(self, hass, entry, mock_hub):
        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            return await async_setup_entry(hass, entry)

    @_REFUSALS
    async def test_refusals_keep_retrying_and_never_prompt_reauth(
        self, hass, mock_hub, clock, make_refusal
    ):
        mock_hub.login = AsyncMock(side_effect=make_refusal())
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        for _ in range(8):
            with pytest.raises(ConfigEntryNotReady):
                await self._attempt(hass, entry, mock_hub)
            clock.advance(minutes=10)

        assert mock_hub.login.await_count == 8
        assert _sign_in_issues(hass) == {}

    async def test_setup_kept_password_login_failing_still_counts_the_refusal(
        self, hass, mock_hub, clock
    ):
        """A refusal answered by a kept-password sign-in that then fails
        transiently is still a refusal: the notice appears 15 minutes in."""

        async def refused_then_login_fails():
            mock_hub.last_login_refusal = "err 4"
            raise APIConnectionError("connection reset")

        mock_hub.login = AsyncMock(side_effect=refused_then_login_fails)
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        for _ in range(2):  # t=0, t=10
            with pytest.raises(ConfigEntryNotReady):
                await self._attempt(hass, entry, mock_hub)
            clock.advance(minutes=10)
        assert _renewal_refused_issues(hass) == {}

        with pytest.raises(ConfigEntryNotReady):  # t=20
            await self._attempt(hass, entry, mock_hub)
        assert list(_renewal_refused_issues(hass)) == [_RENEWAL_REFUSED_ISSUE_ID]

    @_REFUSALS
    async def test_the_notice_appears_at_the_first_refusal_15_minutes_in(
        self, hass, mock_hub, clock, caplog, make_refusal
    ):
        mock_hub.login = AsyncMock(side_effect=make_refusal())
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        for _ in range(3):
            with pytest.raises(ConfigEntryNotReady):
                await self._attempt(hass, entry, mock_hub)
            clock.advance(minutes=7)
        assert _renewal_refused_issues(hass) == {}
        assert _ALERT_LOG not in caplog.text

        # 21 minutes after the first refusal; then later ones.
        for _ in range(3):
            with pytest.raises(ConfigEntryNotReady):
                await self._attempt(hass, entry, mock_hub)
            clock.advance(minutes=10)

        issues = _renewal_refused_issues(hass)
        assert list(issues) == [_RENEWAL_REFUSED_ISSUE_ID]
        assert issues[_RENEWAL_REFUSED_ISSUE_ID].translation_placeholders == {
            "username": "test@example.com"
        }
        alerts = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and _ALERT_LOG in r.getMessage()
        ]
        assert len(alerts) == 1
        assert _sign_in_issues(hass) == {}

    async def test_a_cleared_notice_is_not_raised_again_in_the_same_period(
        self, hass, mock_hub, clock
    ):
        """Raised once per period: dismissing it does not bring it back on
        the next refusal."""
        mock_hub.login = AsyncMock(side_effect=refresh_token_rejected_error())
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)
        clock.advance(minutes=15)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)
        ir.async_delete_issue(hass, DOMAIN, _RENEWAL_REFUSED_ISSUE_ID)

        clock.advance(minutes=10)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)

        assert _renewal_refused_issues(hass) == {}

    async def test_tracking_is_per_account(self, hass, mock_hub, clock):
        """Entries on different accounts retry different tokens: a refusal on
        one account does not start the other's period."""
        mock_hub.login = AsyncMock(side_effect=refresh_login_crash_error())
        entry1 = MockConfigEntry(
            domain=DOMAIN, data=make_config_entry_data(username="one@example.com")
        )
        entry2 = MockConfigEntry(
            domain=DOMAIN, data=make_config_entry_data(username="two@example.com")
        )
        entry1.add_to_hass(hass)
        entry2.add_to_hass(hass)

        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry1, mock_hub)
        clock.advance(minutes=15)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry2, mock_hub)

        assert _renewal_refused_issues(hass) == {}

    async def test_entries_on_one_account_share_the_tracking(
        self, hass, mock_hub, clock
    ):
        """Two installations on one account retry the same stored token, and
        alternate as session creator; tracking per entry would restart the
        period at every switch."""
        mock_hub.login = AsyncMock(side_effect=refresh_login_crash_error())
        data1 = make_config_entry_data()
        data1[CONF_INSTALLATION] = "111"
        data2 = make_config_entry_data()
        data2[CONF_INSTALLATION] = "222"
        entry1 = MockConfigEntry(domain=DOMAIN, data=data1)
        entry2 = MockConfigEntry(domain=DOMAIN, data=data2)
        entry1.add_to_hass(hass)
        entry2.add_to_hass(hass)

        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry1, mock_hub)
        clock.advance(minutes=15)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry2, mock_hub)

        assert list(_renewal_refused_issues(hass)) == [_RENEWAL_REFUSED_ISSUE_ID]

    async def test_setup_via_a_shared_session_resets_the_tracking(
        self, hass, mock_hub, clock
    ):
        """A refusal, then setup succeeding on a co-tenant's session (the reuse
        branch), must end the period: any session handed back resets it.

        Another account stays loaded so the unload does not tear down
        hass.data[DOMAIN] wholesale, which would hide a missing reset.
        """
        mock_hub.login = AsyncMock(side_effect=refresh_login_crash_error())
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        _keep_another_account_loaded(hass)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)

        # A config-flow hub for the same account is registered detached.
        username = entry.data[CONF_USERNAME]
        mock_hub.config_entry = None
        hass.data[DOMAIN].setdefault("sessions", {})[username] = {
            "hub": mock_hub,
            "holders": {"config_flow:flow-id"},
        }
        assert await self._attempt(hass, entry, mock_hub) is True
        # HA removes the flow once its entry is set up, releasing its hold.
        hass.data[DOMAIN]["sessions"][username]["holders"].discard(
            "config_flow:flow-id"
        )
        await async_unload_entry(hass, entry)

        clock.advance(minutes=15)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)
        assert _renewal_refused_issues(hass) == {}

    async def test_successful_login_resets_the_tracking(self, hass, mock_hub, clock):
        """Refusal, success, refusal 15 minutes later: the later refusal
        starts a fresh period, so no notice.

        Another account stays loaded throughout so the unload in the middle
        does not tear down hass.data[DOMAIN] wholesale, which would hide a
        missing reset.
        """
        mock_hub.login = AsyncMock(
            side_effect=[
                refresh_login_crash_error(),
                None,
                refresh_login_crash_error(),
            ]
        )
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        _keep_another_account_loaded(hass)

        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)
        assert await self._attempt(hass, entry, mock_hub) is True
        await async_unload_entry(hass, entry)
        clock.advance(minutes=15)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)

        assert _renewal_refused_issues(hass) == {}

    async def test_other_transient_failures_never_escalate(self, hass, mock_hub):
        """A 5xx is not a refusal: it retries forever, as before."""
        mock_hub.login = AsyncMock(
            side_effect=VerisureOwaError("boom", http_status=500)
        )
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        for _ in range(3):
            with pytest.raises(ConfigEntryNotReady):
                await self._attempt(hass, entry, mock_hub)

    async def test_other_transient_failures_neither_start_nor_reset_the_period(
        self, hass, mock_hub, clock
    ):
        """Timeout, refusal, timeout, refusal 15 minutes after the first
        refusal: still no successful renewal, so the notice appears."""
        mock_hub.login = AsyncMock(
            side_effect=[
                APIConnectionError("timeout"),
                refresh_login_crash_error(),
                APIConnectionError("timeout"),
                refresh_login_crash_error(),
            ]
        )
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        for _ in range(3):
            with pytest.raises(ConfigEntryNotReady):
                await self._attempt(hass, entry, mock_hub)
            assert _renewal_refused_issues(hass) == {}
            clock.advance(minutes=10)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)

        assert list(_renewal_refused_issues(hass)) == [_RENEWAL_REFUSED_ISSUE_ID]

    @pytest.mark.parametrize(
        ("persisting", "cleared"),
        [(False, True), (True, False)],
        ids=["accepted-session-clears", "still-refused-session-keeps"],
    )
    async def test_a_handed_back_session_clears_the_notice_unless_still_refused(
        self, hass, mock_hub, persisting, cleared
    ):
        """Setup reusing a co-tenant's session clears the notice when that
        session's renewals are not being refused."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        raise_renewal_refused_issue(hass, "test@example.com")
        mock_hub.refresh_refusals_persisting = persisting
        mock_hub.config_entry = entry
        hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})[
            "test@example.com"
        ] = {"hub": mock_hub, "holders": {"co-tenant-entry-id"}}

        assert await self._attempt(hass, entry, mock_hub) is True

        mock_hub.login.assert_not_awaited()
        assert (_renewal_refused_issues(hass) == {}) is cleared

    async def test_a_handed_back_session_keeps_the_notice_while_its_alert_stands(
        self, hass, mock_hub
    ):
        """Adopting a token ends the client's refusal period but not its
        alert: until a renewal succeeds, Verisure may still be refusing, and
        the client clears its own notice when one does."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        raise_renewal_refused_issue(hass, "test@example.com")
        mock_hub.refresh_refusals_persisting = False
        mock_hub.refresh_refusal_alert_raised = True
        mock_hub.config_entry = entry
        hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})[
            "test@example.com"
        ] = {"hub": mock_hub, "holders": {"co-tenant-entry-id"}}

        assert await self._attempt(hass, entry, mock_hub) is True

        assert list(_renewal_refused_issues(hass)) == [_RENEWAL_REFUSED_ISSUE_ID]

    async def test_clock_set_back_does_not_delay_the_notice(
        self, hass, mock_hub, clock
    ):
        clock.utc = datetime(2026, 10, 25, 0, 50, tzinfo=UTC)  # 01:50 local
        mock_hub.login = AsyncMock(side_effect=refresh_token_rejected_error())
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)

        clock.advance(minutes=15)  # 01:05 local, after the clocks went back
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)

        assert list(_renewal_refused_issues(hass)) == [_RENEWAL_REFUSED_ISSUE_ID]

    @pytest.mark.parametrize(
        ("second_entry", "kept"),
        [(False, False), (True, True)],
        ids=["last-entry-drops-it", "entry-left-keeps-it"],
    )
    async def test_deleting_an_entry_drops_tracking_no_entry_uses(
        self, hass, mock_hub, second_entry, kept
    ):
        mock_hub.login = AsyncMock(side_effect=refresh_token_rejected_error())
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        if second_entry:
            data = make_config_entry_data()
            data[CONF_INSTALLATION] = "222"
            MockConfigEntry(domain=DOMAIN, data=data).add_to_hass(hass)
        other = MockConfigEntry(
            domain=DOMAIN, data=make_config_entry_data(username="other@example.com")
        )
        other.add_to_hass(hass)
        _keep_another_account_loaded(hass, "third@example.com")
        for refused in (entry, other):
            with pytest.raises(ConfigEntryNotReady):
                await self._attempt(hass, refused, mock_hub)

        await async_remove_entry(hass, entry)

        refusals = hass.data[DOMAIN]["refresh_refusals"]
        assert ("test@example.com" in refusals) is kept
        assert "other@example.com" in refusals


def _unreachable_issues(hass):
    return {
        issue_id: issue
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue_id.startswith("cannot_reach_verisure_")
    }


_UNREACHABLE_ISSUE_ID = (
    "cannot_reach_verisure_" + hashlib.sha256(b"test@example.com").hexdigest()[:12]
)


class TestSetupUnreachable:
    """Setup that cannot reach Verisure for an hour raises the "can't reach
    Verisure" notice. Each retry builds a fresh hub, so setup tracks the
    period per account in hass.data, as it does refusals."""

    @pytest.fixture
    def mock_hub(self):
        hub = make_securitas_hub_mock()
        hub.client.list_installations = AsyncMock(return_value=[make_installation()])
        return hub

    _attempt = TestSetupRefreshRefusals._attempt

    async def test_setup_unreachable_for_an_hour_raises_the_notice(
        self, hass, mock_hub, clock
    ):
        mock_hub.login = AsyncMock(side_effect=APIConnectionError("timeout"))
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)
        clock.advance(minutes=59)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)
        assert _unreachable_issues(hass) == {}

        clock.advance(minutes=1)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)

        issues = _unreachable_issues(hass)
        assert list(issues) == [_UNREACHABLE_ISSUE_ID]
        assert issues[_UNREACHABLE_ISSUE_ID].translation_placeholders == {
            "username": "test@example.com",
            "url": "https://github.com/guerrerotook/securitas-direct-new-api/issues",
        }
        assert _sign_in_issues(hass) == {}

        # Raised once per period: dismissed, it does not come back.
        ir.async_delete_issue(hass, DOMAIN, _UNREACHABLE_ISSUE_ID)
        clock.advance(minutes=10)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)
        assert _unreachable_issues(hass) == {}

    async def test_session_handed_back_clears_the_unreachable_notice(
        self, hass, mock_hub, clock
    ):
        """A sign-in made at setup is a request that worked: the notice goes
        and the next failure starts a fresh period."""
        mock_hub.login = AsyncMock(side_effect=[APIConnectionError("timeout"), None])
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)
        clock.advance(minutes=60)
        raise_unreachable_issue(hass, "test@example.com")
        assert list(_unreachable_issues(hass)) == [_UNREACHABLE_ISSUE_ID]

        assert await self._attempt(hass, entry, mock_hub) is True

        assert _unreachable_issues(hass) == {}
        assert "test@example.com" not in hass.data[DOMAIN].get("unreachable", {})

    @pytest.mark.parametrize(
        ("alert_raised", "kept"),
        [(True, True), (False, False)],
        ids=["alert-raised-keeps", "no-alert-clears"],
    )
    async def test_reused_session_keeps_the_unreachable_notice_while_alert_raised(
        self, hass, mock_hub, alert_raised, kept
    ):
        """Reusing a co-tenant's session makes no request, so it proves
        nothing while that session's client still cannot reach Verisure."""
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        raise_unreachable_issue(hass, "test@example.com")
        mock_hub.unreachable_alert_raised = alert_raised
        mock_hub.config_entry = entry
        hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})[
            "test@example.com"
        ] = {"hub": mock_hub, "holders": {"co-tenant-entry-id"}}
        hass.data[DOMAIN].setdefault("unreachable", {})["test@example.com"] = {
            "since": datetime.now(UTC),
            "alerted": True,
        }

        assert await self._attempt(hass, entry, mock_hub) is True

        mock_hub.login.assert_not_awaited()
        assert (list(_unreachable_issues(hass)) == [_UNREACHABLE_ISSUE_ID]) is kept
        assert "test@example.com" not in hass.data[DOMAIN]["unreachable"]

    async def test_removing_the_last_entry_clears_the_unreachable_notice(
        self, hass, mock_hub
    ):
        mock_hub.login = AsyncMock(side_effect=APIConnectionError("timeout"))
        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)
        other = MockConfigEntry(
            domain=DOMAIN, data=make_config_entry_data(username="other@example.com")
        )
        other.add_to_hass(hass)
        _keep_another_account_loaded(hass, "third@example.com")
        for failing in (entry, other):
            with pytest.raises(ConfigEntryNotReady):
                await self._attempt(hass, failing, mock_hub)
        raise_unreachable_issue(hass, "test@example.com")
        raise_unreachable_issue(hass, "other@example.com")

        await async_remove_entry(hass, entry)

        assert [
            i.translation_placeholders["username"]
            for i in _unreachable_issues(hass).values()
        ] == ["other@example.com"]
        tracking = hass.data[DOMAIN]["unreachable"]
        assert "test@example.com" not in tracking
        assert "other@example.com" in tracking


# ===========================================================================
# TestCoTenantStoredTokenRecovery
# ===========================================================================


class TestCoTenantStoredTokenRecovery:
    """Two installations share one hub whose token Verisure keeps refusing.

    A reloaded entry whose own stored token differs from the refused one
    lands on the reuse branch while the co-tenant still holds the session, and
    tries its stored token on the shared client: adopt it and log in with it.
    """

    @pytest.fixture
    def mock_hub(self):
        """Create a mock VerisureHub for setup tests."""
        hub = make_securitas_hub_mock()
        hub.client.list_installations = AsyncMock(return_value=[make_installation()])
        return hub

    async def _attempt(self, hass, entry, mock_hub):
        with (
            _patch_hub(mock_hub),
            patch("custom_components.securitas.async_get_clientsession"),
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                new_callable=AsyncMock,
            ),
        ):
            return await async_setup_entry(hass, entry)

    def _shared_session(self, hass, mock_hub, entry):
        username = entry.data[CONF_USERNAME]
        hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})[username] = {
            "hub": mock_hub,
            "holders": {"co-tenant-entry-id"},  # the co-tenant still holds it
        }
        mock_hub.config_entry = entry

    async def test_reload_with_a_different_stored_token_adopts_it(self, hass, mock_hub):
        data = make_config_entry_data()
        data[CONF_REFRESH_TOKEN] = "own-stored-token"
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)
        _raise_sign_in_issue(hass, entry.data[CONF_USERNAME])
        self._shared_session(hass, mock_hub, entry)
        mock_hub.refresh_refusals_persisting = True
        mock_hub.get_refresh_token.return_value = "dead-token"
        assert _sign_in_issues(hass) != {}

        assert await self._attempt(hass, entry, mock_hub) is True

        mock_hub.adopt_refresh_token.assert_called_once_with("own-stored-token")
        mock_hub.login.assert_awaited_once()
        assert _sign_in_issues(hass) == {}

    async def test_reload_with_the_refused_token_itself_does_not_relogin(
        self, hass, mock_hub
    ):
        """A co-tenant reloading with the very token being refused has nothing
        new to offer: reuse as before; the client keeps retrying it."""
        data = make_config_entry_data()
        data[CONF_REFRESH_TOKEN] = "dead-token"
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)
        self._shared_session(hass, mock_hub, entry)
        mock_hub.refresh_refusals_persisting = True
        mock_hub.get_refresh_token.return_value = "dead-token"

        assert await self._attempt(hass, entry, mock_hub) is True

        mock_hub.adopt_refresh_token.assert_not_called()
        mock_hub.login.assert_not_awaited()

    async def test_live_shared_client_is_reused_untouched(self, hass, mock_hub):
        data = make_config_entry_data()
        data[CONF_REFRESH_TOKEN] = "older-on-disk"
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)
        self._shared_session(hass, mock_hub, entry)
        mock_hub.refresh_refusals_persisting = False
        mock_hub.get_refresh_token.return_value = "live-token"

        assert await self._attempt(hass, entry, mock_hub) is True

        mock_hub.adopt_refresh_token.assert_not_called()
        mock_hub.login.assert_not_awaited()

    async def test_failed_relogin_on_the_adopted_token_maps_like_a_fresh_login(
        self, hass, mock_hub
    ):
        data = make_config_entry_data()
        data[CONF_REFRESH_TOKEN] = "fresh-but-also-bad"
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)
        self._shared_session(hass, mock_hub, entry)
        mock_hub.refresh_refusals_persisting = True
        mock_hub.get_refresh_token.return_value = "dead-token"
        mock_hub.login = AsyncMock(
            side_effect=VerisureOwaError("boom", http_status=500)
        )

        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)

    async def test_a_single_refusal_does_not_adopt_but_persisting_does(
        self, hass, clock
    ):
        """One refusal may be a passing fault at Verisure: the shared client's
        token keeps its chance. Once refusals have lasted 15 minutes, a joining
        entry's own stored token is tried instead."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_USERNAME: "test@example.com", CONF_REFRESH_TOKEN: "own"},
        )
        entry.add_to_hass(hass)
        co_tenant = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_USERNAME: "test@example.com", CONF_REFRESH_TOKEN: "shared"},
        )
        co_tenant.add_to_hass(hass)
        hub = make_hub(mock_client=False)
        hub.hass = hass
        hub.config_entry = co_tenant
        hub.client.password = ""
        hub.client.refresh_token_value = "shared"
        hub.client.refresh_token = AsyncMock(side_effect=refresh_token_rejected_error())
        session = _new_session_record(hub)
        session["holders"].add(co_tenant.entry_id)
        hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})[
            "test@example.com"
        ] = session

        with pytest.raises(VerisureOwaError):
            await hub.client._check_authentication_token()
        await _get_or_create_session(hass, dict(entry.data), entry)

        assert hub.get_refresh_token() == "shared"
        assert hub.client.refresh_token.await_count == 1

        clock.advance(minutes=15)
        with pytest.raises(VerisureOwaError):
            await hub.client._check_authentication_token()
        assert hub.client.refresh_refusals_persisting
        hub.client.refresh_token = AsyncMock(return_value=True)

        await _get_or_create_session(hass, dict(entry.data), entry)

        assert hub.get_refresh_token() == "own"
        hub.client.refresh_token.assert_awaited_once()

    async def _persisting_shared_hub(self, hass, clock):
        """A real shared hub whose own token Verisure has refused for 15
        minutes, held by a running co-tenant entry; its notice is up."""
        co_tenant = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_USERNAME: "test@example.com", CONF_REFRESH_TOKEN: "shared"},
        )
        co_tenant.add_to_hass(hass)
        hub = make_hub(mock_client=False)
        hub.hass = hass
        hub.config_entry = co_tenant
        hub.client.password = ""
        hub.client.refresh_token_value = "shared"
        hub.client.refresh_token = AsyncMock(side_effect=refresh_token_rejected_error())
        session = _new_session_record(hub)
        session["holders"].add(co_tenant.entry_id)
        hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})[
            "test@example.com"
        ] = session
        with pytest.raises(VerisureOwaError):
            await hub.client._check_authentication_token()
        clock.advance(minutes=15)
        with pytest.raises(VerisureOwaError):
            await hub.client._check_authentication_token()
        assert hub.refresh_refusals_persisting
        assert list(_renewal_refused_issues(hass)) == [_RENEWAL_REFUSED_ISSUE_ID]
        return hub

    def _joining_entry(self, hass):
        data = make_config_entry_data()
        data[CONF_REFRESH_TOKEN] = "own"
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)
        return entry

    async def _assert_shared_token_and_period_kept(self, hub, clock):
        assert hub.get_refresh_token() == "shared"
        assert hub.refresh_refusals_persisting
        assert hub.refresh_refusal_alert_raised
        # Still paced from the shared client's own last attempt.
        hub.client.refresh_token = AsyncMock(return_value=True)
        clock.advance(minutes=1)
        with pytest.raises(VerisureOwaError, match="next try after"):
            await hub.client._check_authentication_token()
        hub.client.refresh_token.assert_not_awaited()

    async def test_a_genuinely_rejected_adopted_token_is_handed_back(
        self, hass, mock_hub, clock
    ):
        hub = await self._persisting_shared_hub(hass, clock)
        entry = self._joining_entry(hass)
        rejected = SessionExpiredError("Invalid Session", http_status=403)
        rejected.response_body = {"errors": [{"data": {"err": "60067"}}]}
        hub.client.refresh_token = AsyncMock(side_effect=rejected)

        with pytest.raises(ConfigEntryAuthFailed):
            await self._attempt(hass, entry, mock_hub)

        hub.client.refresh_token.assert_awaited_once()
        await self._assert_shared_token_and_period_kept(hub, clock)

    async def test_a_refused_adopted_token_is_handed_back(self, hass, mock_hub, clock):
        hub = await self._persisting_shared_hub(hass, clock)
        entry = self._joining_entry(hass)
        hub.client.refresh_token = AsyncMock(side_effect=refresh_token_rejected_error())

        with pytest.raises(ConfigEntryNotReady):
            await self._attempt(hass, entry, mock_hub)

        hub.client.refresh_token.assert_awaited_once()
        assert list(_renewal_refused_issues(hass)) == [_RENEWAL_REFUSED_ISSUE_ID]
        await self._assert_shared_token_and_period_kept(hub, clock)

    async def test_a_renewal_in_flight_is_never_undone_by_an_adoption(
        self, hass, clock
    ):
        """A running renewal of the shared token and a joining entry's setup
        overlap. The renewal succeeds and rotates the token; the joining
        entry must not then put back the token the renewal replaced, nor
        reopen the refusal period the renewal ended."""
        hub = await self._persisting_shared_hub(hass, clock)
        entry = self._joining_entry(hass)
        clock.advance(minutes=5)  # a paced renewal is due
        renewing = asyncio.Event()
        release_renewal = asyncio.Event()
        renewal_done = asyncio.Event()
        presented: list[str] = []

        async def execute(content, operation, **kwargs):
            token = content["variables"]["refreshToken"]
            presented.append(token)
            if token == "shared":
                renewing.set()
                await asyncio.wait_for(release_renewal.wait(), 2)
                return refresh_response(refresh_token="rotated-and-valid")
            await asyncio.wait_for(renewal_done.wait(), 2)
            raise refresh_token_rejected_error()

        del hub.client.refresh_token  # the real refresh, rotation and callbacks
        hub.client._execute_raw = execute

        async def renew():
            try:
                await hub.client._check_authentication_token()
            finally:
                renewal_done.set()

        renewal = asyncio.create_task(renew())
        await asyncio.wait_for(renewing.wait(), 2)
        joining = asyncio.create_task(
            _get_or_create_session(hass, dict(entry.data), entry)
        )
        try:
            for _ in range(5):
                await asyncio.sleep(0)
            release_renewal.set()
            results = await asyncio.wait_for(
                asyncio.gather(renewal, joining, return_exceptions=True), 2
            )
        finally:
            for task in (renewal, joining):
                task.cancel()
            await asyncio.gather(renewal, joining, return_exceptions=True)

        assert hub.get_refresh_token() == "rotated-and-valid"
        assert results == [None, hub]
        assert presented == ["shared"]
        assert hub.config_entry.data[CONF_REFRESH_TOKEN] == "rotated-and-valid"
        assert not hub.refresh_refusals_persisting
        assert not hub.refresh_refusal_alert_raised
        assert _renewal_refused_issues(hass) == {}

    async def test_an_adopted_token_signs_in_through_the_real_refresh(
        self, hass, clock
    ):
        """The adoption holds the renewal lock while it signs in, so the
        sign-in must not wait for that lock itself."""
        hub = await self._persisting_shared_hub(hass, clock)
        entry = self._joining_entry(hass)

        async def execute(content, operation, **kwargs):
            assert content["variables"]["refreshToken"] == "own"
            return refresh_response(refresh_token="own-rotated")

        del hub.client.refresh_token
        hub.client._execute_raw = execute

        session = await asyncio.wait_for(
            _get_or_create_session(hass, dict(entry.data), entry), 2
        )

        assert session is hub
        assert hub.get_refresh_token() == "own-rotated"
        assert not hub.renewal_lock.locked()
        assert _renewal_refused_issues(hass) == {}

    async def test_a_cancelled_adoption_hands_the_shared_token_back(self, hass, clock):
        hub = await self._persisting_shared_hub(hass, clock)
        entry = self._joining_entry(hass)
        signing_in = asyncio.Event()

        async def never_answers():
            signing_in.set()
            await asyncio.Event().wait()

        hub.client.refresh_token = never_answers
        joining = asyncio.create_task(
            _get_or_create_session(hass, dict(entry.data), entry)
        )
        await asyncio.wait_for(signing_in.wait(), 2)
        assert hub.get_refresh_token() == "own"
        joining.cancel()
        with pytest.raises(asyncio.CancelledError):
            await joining

        await self._assert_shared_token_and_period_kept(hub, clock)

    async def test_a_notice_due_while_detached_appears_on_reattach(self, hass, clock):
        """Refusals that reach 15 minutes while the hub has no entry (only a
        setup dialog holds the session) raise no notice then, and the client
        will not ask again this refusal period: attaching an entry raises it."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_USERNAME: "test@example.com", CONF_REFRESH_TOKEN: "own"},
        )
        entry.add_to_hass(hass)
        hub = make_hub(mock_client=False)
        hub.hass = hass
        hub.config_entry = None
        hub.client.password = ""
        hub.client.refresh_token_value = "shared"
        hub.client.refresh_token = AsyncMock(side_effect=refresh_token_rejected_error())
        with pytest.raises(VerisureOwaError):
            await hub.client._check_authentication_token()
        clock.advance(minutes=15)
        with pytest.raises(VerisureOwaError):
            await hub.client._check_authentication_token()
        assert hub.client.refresh_refusals_persisting
        assert _renewal_refused_issues(hass) == {}

        _attach_token_persistence(hub, entry)

        assert list(_renewal_refused_issues(hass)) == [_RENEWAL_REFUSED_ISSUE_ID]
        assert entry.data[CONF_REFRESH_TOKEN] == "own"

    async def test_an_unreachable_notice_due_while_detached_appears_on_reattach(
        self, hass, clock
    ):
        """The client alerts once per unreachable period; an alert that came
        while the hub had no entry is raised when one attaches."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_USERNAME: "test@example.com", CONF_REFRESH_TOKEN: "own"},
        )
        entry.add_to_hass(hass)
        hub = make_hub(mock_client=False)
        hub.hass = hass
        hub.config_entry = None
        hub.client.refresh_token_value = "shared"
        hub.client._transport.execute = AsyncMock(
            side_effect=APIConnectionError("no route")
        )
        for _ in range(2):
            with pytest.raises(APIConnectionError):
                await hub.client._execute_raw({}, "Status")
            clock.advance(minutes=60)
        assert hub.unreachable_alert_raised
        assert _unreachable_issues(hass) == {}

        _attach_token_persistence(hub, entry)

        assert list(_unreachable_issues(hass)) == [_UNREACHABLE_ISSUE_ID]


class TestKeptPasswordSync:
    """The account's shared client uses a kept password only while one of the
    account's enabled entries has the box ticked."""

    USERNAME = "test@example.com"

    def _entry(self, hass, *, kept, password="test-password", **kwargs):
        data = make_config_entry_data(password=password)
        data[CONF_KEEP_PASSWORD] = kept
        if not kept:
            data.pop(CONF_PASSWORD, None)
        entry = MockConfigEntry(domain=DOMAIN, data=data, **kwargs)
        entry.add_to_hass(hass)
        return entry

    def _session(self, hass, hub, *holders):
        session = _new_session_record(hub)
        session["holders"].update(holders)
        hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})[self.USERNAME] = (
            session
        )
        log_filter = SensitiveDataFilter()
        hass.data[DOMAIN]["log_filter"] = log_filter
        return log_filter

    def _register(self, log_filter, password):
        log_filter.update_secret(
            f"password:{_hashed_issue_id('', self.USERNAME)}",
            password,
            label="[PASSWORD]",
        )

    async def test_ticked_entry_joining_a_refused_session_signs_in_with_its_password(
        self, hass, clock
    ):
        holder = self._entry(hass, kept=False)
        hub = make_hub(mock_client=False)
        hub.hass = hass
        hub.config_entry = holder
        hub.client.password = ""
        hub.client.refresh_token_value = "shared"
        hub.client.refresh_token = AsyncMock(side_effect=refresh_token_rejected_error())
        hub.client.login = AsyncMock()
        self._session(hass, hub, holder.entry_id)
        with pytest.raises(VerisureOwaError):
            await hub.client._check_authentication_token()
        clock.advance(minutes=15)
        with pytest.raises(VerisureOwaError):
            await hub.client._check_authentication_token()
        assert hub.refresh_refusals_persisting

        joining = self._entry(hass, kept=True, password="joiner-password")
        data = dict(joining.data)
        data[CONF_REFRESH_TOKEN] = "own"

        session = await _get_or_create_session(hass, data, joining)

        assert session is hub
        hub.client.login.assert_awaited_once()
        assert hub.client.password == "joiner-password"
        assert hub.client.password_kept is True

    @pytest.mark.parametrize("joins", [True, False])
    async def test_sync_takes_password_from_ticked_entry_on_join(self, hass, joins):
        hub = make_securitas_hub_mock()
        hub.client.list_installations = AsyncMock(return_value=[make_installation()])
        self._entry(hass, kept=True, password="kept-password")
        if joins:
            log_filter = self._session(hass, hub, "unticked-entry-id")
        else:
            hass.data.setdefault(DOMAIN, {})["log_filter"] = SensitiveDataFilter()
            log_filter = hass.data[DOMAIN]["log_filter"]
        unticked = self._entry(hass, kept=False)

        with (
            _patch_hub(hub),
            patch("custom_components.securitas.async_get_clientsession"),
        ):
            await _get_or_create_session(hass, dict(unticked.data), unticked)

        assert hub.client.password == "kept-password"
        assert hub.client.password_kept is True
        assert log_filter._redact("kept-password") == "[PASSWORD]"

    async def test_sync_clears_password_when_last_ticked_entry_goes(self, hass):
        hub = make_securitas_hub_mock()
        hub.client.password = "kept-password"
        hub.client.password_kept = True
        unticked = self._entry(hass, kept=False)
        ticked = self._entry(hass, kept=True, password="kept-password")
        log_filter = self._session(hass, hub, unticked.entry_id, ticked.entry_id)
        self._register(log_filter, "kept-password")

        await async_remove_entry(hass, ticked)

        assert hub.client.password == ""
        assert hub.client.password_kept is False
        assert log_filter._redact("kept-password") == "kept-password"

    async def test_sync_ignores_disabled_entries(self, hass):
        hub = make_securitas_hub_mock()
        hub.client.password = "kept-password"
        hub.client.password_kept = True
        unticked = self._entry(hass, kept=False)
        self._entry(
            hass,
            kept=True,
            password="other-kept-password",
            disabled_by=ConfigEntryDisabler.USER,
        )
        disabling = self._entry(hass, kept=True, password="kept-password")
        log_filter = self._session(hass, hub, unticked.entry_id, disabling.entry_id)
        self._register(log_filter, "kept-password")
        hass.data[DOMAIN][disabling.entry_id] = {"hub": hub, "devices": []}
        # ConfigEntry blocks plain attribute assignment.
        object.__setattr__(disabling, "disabled_by", ConfigEntryDisabler.USER)

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            assert await async_unload_entry(hass, disabling) is True

        assert hub.client.password == ""
        assert hub.client.password_kept is False

    def _refused_hub(self, hass, holder, login_error):
        """The account's shared hub: Verisure refuses its saved sign-in and
        answers a sign-in with the kept password with ``login_error``."""
        hub = make_hub(mock_client=False)
        hub.hass = hass
        hub.config_entry = holder
        hub.client.password = "kept-password"
        hub.client.password_kept = True
        hub.client.refresh_token_value = "shared"
        hub.client.refresh_token = AsyncMock(side_effect=refresh_token_rejected_error())
        if login_error is not None:
            hub.client.login = AsyncMock(side_effect=login_error)
        return hub

    def _ticked_pair_and_other_account(self, hass):
        home = self._entry(hass, kept=True, password="kept-password")
        office = self._entry(hass, kept=True, password="kept-password")
        other_data = make_config_entry_data(
            username="other@example.com", password="other-password"
        )
        other_data[CONF_KEEP_PASSWORD] = True
        other = MockConfigEntry(domain=DOMAIN, data=other_data)
        other.add_to_hass(hass)
        return home, office, other

    def _assert_forgotten_but_ticked(self, *entries):
        for entry in entries:
            assert CONF_PASSWORD not in entry.data
            assert entry.data[CONF_KEEP_PASSWORD] is True

    async def test_rejected_kept_password_is_forgotten_by_the_entries(self, hass):
        """Runtime: the kept password Verisure rejects goes from every entry
        of the account, so no restart or joining entry tries it again; the box
        stays ticked, so the sign-in that follows keeps the new password."""
        home, office, other = self._ticked_pair_and_other_account(hass)
        hub = self._refused_hub(hass, home, login_rejected_error())

        with pytest.raises(AuthenticationError):
            await hub.client._check_authentication_token()

        self._assert_forgotten_but_ticked(home, office)
        assert other.data[CONF_PASSWORD] == "other-password"

    async def test_rejected_kept_password_is_forgotten_at_setup(self, hass):
        home, office, other = self._ticked_pair_and_other_account(hass)
        hub = self._refused_hub(hass, None, AccountBlockedError("blocked"))

        with pytest.raises(AccountBlockedError):
            await hub.login()

        self._assert_forgotten_but_ticked(home, office)
        assert other.data[CONF_PASSWORD] == "other-password"

    @pytest.mark.parametrize("fault", list(LOGIN_SERVER_FAULTS))
    async def test_server_fault_at_sign_in_keeps_the_password_on_disk(
        self, hass, fault
    ):
        """Verisure failing to answer a sign-in is not a verdict on the
        password: it stays in memory and in the entries."""
        home, office, _ = self._ticked_pair_and_other_account(hass)
        # The real login, answered by the transport.
        hub = self._refused_hub(hass, home, None)
        hub.client._transport.execute = AsyncMock(
            return_value=login_error_reply(LOGIN_SERVER_FAULTS[fault])
        )

        with pytest.raises(AuthenticationError):
            await hub.client._check_authentication_token()

        assert hub.client.password == "kept-password"
        assert home.data[CONF_PASSWORD] == "kept-password"
        assert office.data[CONF_PASSWORD] == "kept-password"

    async def test_wrong_password_reply_at_sign_in_forgets_it_on_disk(self, hass):
        home, office, _ = self._ticked_pair_and_other_account(hass)
        hub = self._refused_hub(hass, home, None)
        hub.client._transport.execute = AsyncMock(
            return_value=login_error_reply(LOGIN_WRONG_PASSWORD)
        )

        with pytest.raises(AuthenticationError):
            await hub.client._check_authentication_token()

        self._assert_forgotten_but_ticked(home, office)

    async def test_only_the_rejected_password_is_forgotten(self, hass):
        """A password saved meanwhile, say by Reconfigure while an old
        sign-in was still running, is not the one Verisure rejected."""
        home = self._entry(hass, kept=True, password="kept-password")
        office = self._entry(hass, kept=True, password="new-password")
        hub = self._refused_hub(hass, home, login_rejected_error())

        with pytest.raises(AuthenticationError):
            await hub.client._check_authentication_token()

        self._assert_forgotten_but_ticked(home)
        assert office.data[CONF_PASSWORD] == "new-password"

    async def test_ticked_entries_setting_up_together_spend_one_sign_in(self, hass):
        """Each entry's setup reads its data before waiting for the account:
        the second must not sign in with the copy it read before the first
        found the password rejected."""
        home, office, _ = self._ticked_pair_and_other_account(hass)
        hass.data.setdefault(DOMAIN, {})
        login = AsyncMock(side_effect=login_rejected_error())

        def build(config, entry, *_args):
            hub = VerisureHub(config, entry, MagicMock(), hass)
            hub.client.refresh_token_value = "refused"
            hub.client.refresh_token = AsyncMock(
                side_effect=refresh_token_rejected_error()
            )
            hub.client.login = login
            return hub

        with (
            patch("custom_components.securitas.VerisureHub", side_effect=build),
            patch("custom_components.securitas.async_get_clientsession"),
        ):
            results = await asyncio.gather(
                _get_or_create_session(hass, dict(home.data), home),
                _get_or_create_session(hass, dict(office.data), office),
                return_exceptions=True,
            )

        assert all(isinstance(r, Exception) for r in results)
        login.assert_awaited_once()
        self._assert_forgotten_but_ticked(home, office)

    async def test_kept_password_failing_transiently_stays_in_the_entries(self, hass):
        home, office, _ = self._ticked_pair_and_other_account(hass)
        hub = self._refused_hub(hass, home, APIConnectionError("reset"))

        with pytest.raises(APIConnectionError):
            await hub.client._check_authentication_token()

        assert home.data[CONF_PASSWORD] == "kept-password"
        assert office.data[CONF_PASSWORD] == "kept-password"

    async def test_ticked_entry_joining_after_a_rejection_does_not_sign_in(
        self, hass, clock
    ):
        """The other ticked entry joining the session afterwards brings no
        password, so trying its own token, refused too, makes no sign-in."""
        home, office, _ = self._ticked_pair_and_other_account(hass)
        hub = self._refused_hub(hass, home, login_rejected_error())
        self._session(hass, hub, home.entry_id)
        with pytest.raises(AuthenticationError):
            await hub.client._check_authentication_token()
        clock.advance(minutes=15)
        hub.client.authentication_token_exp = datetime.min
        with pytest.raises(VerisureOwaError):
            await hub.client._check_authentication_token()
        assert hub.refresh_refusals_persisting
        data = dict(office.data)
        data[CONF_REFRESH_TOKEN] = "own"

        with pytest.raises(ConfigEntryNotReady):
            await _get_or_create_session(hass, data, office)

        hub.client.login.assert_awaited_once()
        assert hub.client.password == ""
        assert hub.client.password_kept is False

    async def test_plain_unload_and_reload_keep_the_kept_password(self, hass):
        """A reload, or Home Assistant stopping, is not the user saying no:
        the shared client keeps the ticked entry's password, and the log
        filter keeps hiding it."""
        hub = make_securitas_hub_mock()
        hub.client.list_installations = AsyncMock(return_value=[make_installation()])
        hub.client.password = "kept-password"
        hub.client.password_kept = True
        unticked = self._entry(hass, kept=False)
        ticked = self._entry(hass, kept=True, password="kept-password")
        log_filter = self._session(hass, hub, unticked.entry_id, ticked.entry_id)
        self._register(log_filter, "kept-password")
        hass.data[DOMAIN][ticked.entry_id] = {"hub": hub, "devices": []}

        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            assert await async_unload_entry(hass, ticked) is True

        assert hub.client.password == "kept-password"
        assert hub.client.password_kept is True
        assert log_filter._redact("kept-password") == "[PASSWORD]"

        await _get_or_create_session(hass, dict(ticked.data), ticked)

        assert hub.client.password == "kept-password"
        assert hub.client.password_kept is True
        assert log_filter._redact("kept-password") == "[PASSWORD]"

    async def test_sync_leaves_in_memory_password_alone(self, hass):
        hub = make_securitas_hub_mock()
        hub.client.password = "just-typed"
        hub.client.password_kept = False
        holder = self._entry(hass, kept=False)
        self._session(hass, hub, holder.entry_id)
        joining = self._entry(hass, kept=False)

        await _get_or_create_session(hass, dict(joining.data), joining)

        assert hub.client.password == "just-typed"
        assert hub.client.password_kept is False
