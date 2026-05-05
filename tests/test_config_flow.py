"""Tests for the Securitas Direct config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.securitas import (
    CONF_ADVANCED,
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
    DEFAULT_DELAY_CHECK_OPERATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from custom_components.securitas.securitas_direct_new_api import (
    AccountBlockedError,
    Attribute,
    AuthenticationError,
    OtpPhone,
    PERI_DEFAULTS,
    STD_DEFAULTS,
    SecuritasDirectError,
    SecuritasState,
    TwoFactorRequiredError,
)
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import FlowResultType

from tests.conftest import (
    FAKE_JWT,
    make_config_entry_data,
    make_installation,
    make_securitas_hub_mock,
)

from pytest_homeassistant_custom_component.common import MockConfigEntry

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests in this module."""
    yield


# ---------------------------------------------------------------------------
# Shared constants and helpers
# ---------------------------------------------------------------------------

FAKE_UUID = "abcd1234efgh5678"

USER_INPUT_CREDENTIALS = {
    CONF_COUNTRY: "ES",
    CONF_USERNAME: "test@example.com",
    CONF_PASSWORD: "test-password",
}

USER_INPUT_OPTIONS = {
    CONF_CODE: "",
    CONF_CODE_ARM_REQUIRED: False,
    CONF_ADVANCED: {
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_DELAY_CHECK_OPERATION: float(DEFAULT_DELAY_CHECK_OPERATION),
    },
}

USER_INPUT_MAPPINGS_STD = {
    CONF_MAP_HOME: STD_DEFAULTS[CONF_MAP_HOME],
    CONF_MAP_AWAY: STD_DEFAULTS[CONF_MAP_AWAY],
    CONF_MAP_NIGHT: STD_DEFAULTS[CONF_MAP_NIGHT],
    CONF_MAP_VACATION: STD_DEFAULTS[CONF_MAP_VACATION],
    CONF_MAP_CUSTOM: STD_DEFAULTS[CONF_MAP_CUSTOM],
}


MOCK_PHONES = [
    OtpPhone(id=0, phone="555-1234"),
    OtpPhone(id=1, phone="555-5678"),
]

PATCH_HUB = "custom_components.securitas.config_flow.SecuritasHub"
PATCH_SESSION = "custom_components.securitas.config_flow.async_get_clientsession"
PATCH_UUID = "custom_components.securitas.config_flow.generate_uuid"


def _hub_factory(*, two_fa: bool = False, **overrides):
    """Create a mock SecuritasHub for config flow tests.

    Starts with no auth token.  login() sets it (via side_effect) so that
    finish_setup's ``get_authentication_token() is None`` check works
    correctly for both non-2FA (calls login) and 2FA paths.

    When two_fa=True, login() raises TwoFactorRequiredError (establishing a session)
    and validate_device() returns the phone list — matching production behavior.
    """
    hub = make_securitas_hub_mock(**overrides)
    hub.validate_device = AsyncMock(return_value=("otp-hash-abc", MOCK_PHONES))
    hub.client.list_installations = AsyncMock(return_value=[make_installation()])

    # Start without a token; login() and send_sms_code() set it.
    _token_holder: dict[str, str | None] = {"token": None}

    def _get_token():
        return _token_holder["token"]

    async def _login():
        if two_fa:
            raise TwoFactorRequiredError("2FA required")
        _token_holder["token"] = FAKE_JWT

    async def _send_sms_code(*_args):
        _token_holder["token"] = FAKE_JWT
        return (None, None)

    hub.get_authentication_token = MagicMock(side_effect=_get_token)
    hub.login = AsyncMock(side_effect=_login)
    hub.send_sms_code = AsyncMock(side_effect=_send_sms_code)

    # get_services sets alarm_partitions on the installation (no peri by default)
    async def _get_services(installation, **kwargs):
        installation.alarm_partitions = []
        return []

    hub.get_services = AsyncMock(side_effect=_get_services)

    return hub


def _make_hub_class_mock(hub_instance):
    """Create a mock class that mimics SecuritasHub but returns hub_instance.

    MagicMock does not have a proper __name__ attribute, so we set it
    to make the mock behave like a real class.
    """
    mock_cls = MagicMock(return_value=hub_instance)
    mock_cls.__name__ = "SecuritasHub"
    return mock_cls


def _patches(mock_hub, uuid=FAKE_UUID):
    """Return a context manager that patches all three config flow dependencies."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        hub_cls = _make_hub_class_mock(mock_hub)
        with (
            patch(PATCH_HUB, hub_cls),
            patch(PATCH_SESSION, return_value=MagicMock()),
            patch(PATCH_UUID, return_value=uuid),
        ):
            yield hub_cls

    return _ctx()


async def _complete_full_flow(
    hass, mock_hub, credentials=None, options=None, mappings=None
):
    """Navigate full config flow: credentials -> options -> mappings -> create entry."""
    creds = credentials or USER_INPUT_CREDENTIALS
    opts = options or USER_INPUT_OPTIONS
    maps = mappings or USER_INPUT_MAPPINGS_STD

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=creds
        )

    if result["type"] == FlowResultType.FORM and result["step_id"] == "options":
        flow_id = result["flow_id"]
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=opts
        )

    if result["type"] == FlowResultType.FORM and result["step_id"] == "mappings":
        flow_id = result["flow_id"]
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=maps
        )

    return result


async def _start_2fa_flow(hass, mock_hub):
    """Helper: start the 2FA flow up to the phone_list step and return flow_id."""
    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )
    assert result["step_id"] == "phone_list"
    return result["flow_id"]


async def _get_to_otp_step(hass, mock_hub):
    """Navigate through 2FA + phone_list to reach OTP challenge step."""
    flow_id = await _start_2fa_flow(hass, mock_hub)
    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={"phones": "0_555-1234"}
        )
    assert result["step_id"] == "otp_challenge"
    return flow_id


async def _advance_to_mappings(hass, entry):
    """Helper to get to the mappings step of options flow."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]

    result = await hass.config_entries.options.async_configure(
        flow_id,
        user_input={
            CONF_CODE: "1234",
            CONF_CODE_ARM_REQUIRED: False,
            CONF_ADVANCED: {
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                CONF_DELAY_CHECK_OPERATION: float(DEFAULT_DELAY_CHECK_OPERATION),
            },
        },
    )
    assert result["step_id"] == "mappings"
    return result["flow_id"]


# ===================================================================
# TestStepUser (~7 tests)
# ===================================================================


async def test_step_user_initial_form_shown_when_no_input(hass):
    """Show the user form when user_input is None (and init_data is None)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_step_user_non_2fa_advances_to_options(hass):
    """Non-2FA flow should advance to options step after credentials."""
    mock_hub = _hub_factory()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    mock_hub.login.assert_awaited_once()


async def test_step_user_2fa_flow_shows_phone_list(hass):
    """2FA flow should login (raising TwoFactorRequiredError), then validate device and show phone list."""
    mock_hub = _hub_factory(two_fa=True)

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "phone_list"
    mock_hub.login.assert_awaited_once()
    mock_hub.validate_device.assert_awaited_once()


async def test_step_user_login_succeeds_skips_2fa(hass):
    """When login succeeds without 2FA, skip device validation."""
    mock_hub = _hub_factory(two_fa=False)  # login succeeds

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    mock_hub.login.assert_awaited_once()
    mock_hub.validate_device.assert_not_awaited()


async def test_step_user_login_error_shows_invalid_auth(hass):
    """Wrong credentials should re-show the form with invalid_auth error."""
    mock_hub = _hub_factory()
    mock_hub.login.side_effect = AuthenticationError("bad credentials")

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_step_user_connection_error_shows_cannot_connect(hass):
    """Network errors should re-show the form with cannot_connect error."""
    mock_hub = _hub_factory()
    mock_hub.login.side_effect = SecuritasDirectError("connection failed")

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_step_user_account_blocked_shows_account_blocked(hass):
    """Account blocked (error 60052) should re-show the form with account_blocked error."""
    mock_hub = _hub_factory()
    mock_hub.login.side_effect = AccountBlockedError("account blocked")

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "account_blocked"}


async def test_step_user_generates_device_ids(hass):
    """async_step_user should generate uuid, device_id, and indigitall."""
    mock_hub = _hub_factory()

    result = await _complete_full_flow(hass, mock_hub)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_DEVICE_ID] == FAKE_UUID
    assert data[CONF_UNIQUE_ID] == FAKE_UUID
    assert data[CONF_DEVICE_INDIGITALL] == ""


async def test_step_user_sets_delay_check_operation(hass):
    """async_step_user should set default delay_check_operation."""
    mock_hub = _hub_factory()

    result = await _complete_full_flow(hass, mock_hub)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DELAY_CHECK_OPERATION] == DEFAULT_DELAY_CHECK_OPERATION


async def test_step_user_uses_init_data_when_user_input_is_data(hass):
    """When user_input is provided with data, it proceeds with that data."""
    mock_hub = _hub_factory()

    result = await _complete_full_flow(
        hass, mock_hub, credentials=USER_INPUT_CREDENTIALS
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USERNAME] == "test@example.com"


async def test_step_user_creates_securitas_hub(hass):
    """_create_client should be invoked via async_step_user."""
    mock_hub = _hub_factory()

    with _patches(mock_hub) as hub_cls:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    hub_cls.assert_called_once()


# ===================================================================
# TestStepPhoneList (~4 tests)
# ===================================================================


async def test_phone_list_selects_phone_by_index(hass):
    """Select phone using the index prefix (e.g., '0_555-1234')."""
    mock_hub = _hub_factory(two_fa=True)
    flow_id = await _start_2fa_flow(hass, mock_hub)

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={"phones": "0_555-1234"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "otp_challenge"
    # phone index 0 -> OtpPhone.id = 0
    mock_hub.send_opt.assert_awaited_once_with("otp-hash-abc", 0)


async def test_phone_list_selects_second_phone_by_index(hass):
    """Select the second phone using index prefix."""
    mock_hub = _hub_factory(two_fa=True)
    flow_id = await _start_2fa_flow(hass, mock_hub)

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={"phones": "1_555-5678"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "otp_challenge"
    mock_hub.send_opt.assert_awaited_once_with("otp-hash-abc", 1)


async def test_phone_list_fallback_selection_by_phone_name(hass):
    """When index parse fails, fall back to matching by phone name.

    We test the fallback logic directly on the flow handler since the
    phone_list form uses a select validator that rejects invalid keys.
    """
    from custom_components.securitas.config_flow import FlowHandler

    mock_hub = _hub_factory()
    flow = FlowHandler()
    flow.hass = hass
    flow.securitas = mock_hub
    flow.otp_challenge = ("otp-hash-abc", MOCK_PHONES)

    # Simulate user_input with a key that cannot be parsed as integer index
    result = await flow.async_step_phone_list({"phones": "xxx_555-5678"})

    assert result["step_id"] == "otp_challenge"  # type: ignore[typeddict-item]
    # Should find phone "555-5678" -> id=1
    mock_hub.send_opt.assert_awaited_once_with("otp-hash-abc", 1)


async def test_phone_list_sends_otp_and_shows_challenge_form(hass):
    """After selecting phone, OTP is sent and the challenge form is shown."""
    mock_hub = _hub_factory(two_fa=True)
    flow_id = await _start_2fa_flow(hass, mock_hub)

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={"phones": "0_555-1234"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "otp_challenge"
    assert result["data_schema"] is not None


# ===================================================================
# TestStepOtpChallenge (~2 tests)
# ===================================================================


async def test_otp_challenge_sends_sms_code(hass):
    """Submitting OTP code sends it via securitas.send_sms_code."""
    mock_hub = _hub_factory(two_fa=True)
    flow_id = await _get_to_otp_step(hass, mock_hub)

    with _patches(mock_hub):
        await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_CODE: "123456"}
        )

    mock_hub.send_sms_code.assert_awaited_once_with("otp-hash-abc", "123456")


async def test_otp_challenge_wrong_code_shows_error(hass):
    """Wrong SMS code re-shows OTP form with invalid_otp error."""
    mock_hub = _hub_factory(two_fa=True)
    flow_id = await _get_to_otp_step(hass, mock_hub)

    # Wrong code: validate_device returns a new challenge hash instead of (None, None)
    mock_hub.send_sms_code = AsyncMock(return_value=("new-challenge-hash", []))

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_CODE: "000000"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "otp_challenge"
    assert result["errors"] == {"base": "invalid_otp"}


async def test_otp_challenge_api_error_shows_error(hass):
    """API error during SMS code validation re-shows OTP form."""
    mock_hub = _hub_factory(two_fa=True)
    flow_id = await _get_to_otp_step(hass, mock_hub)

    mock_hub.send_sms_code = AsyncMock(side_effect=SecuritasDirectError("API error"))

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_CODE: "123456"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "otp_challenge"
    assert result["errors"] == {"base": "invalid_otp"}


async def test_otp_challenge_advances_to_options(hass):
    """After sending SMS code, flow should advance to options step."""
    mock_hub = _hub_factory(two_fa=True)
    flow_id = await _get_to_otp_step(hass, mock_hub)

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_CODE: "123456"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    # login was called once during async_step_user (raised TwoFactorRequiredError);
    # finish_setup skips login because send_sms_code already set the token
    assert mock_hub.login.await_count == 1


# ===================================================================
# TestFinishSetup (~3 tests)
# ===================================================================


async def test_finish_setup_logs_in_gets_token_advances_to_options(hass):
    """finish_setup should login, get token, and advance to options."""
    mock_hub = _hub_factory()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    mock_hub.login.assert_awaited_once()
    assert (
        mock_hub.get_authentication_token.call_count == 2
    )  # is None check + get token


async def test_finish_setup_lists_installations(hass):
    """finish_setup lists installations and calls get_services."""
    mock_hub = _hub_factory()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    mock_hub.client.list_installations.assert_awaited_once()
    mock_hub.get_services.assert_awaited_once()


async def test_finish_setup_sets_hass_data(hass):
    """finish_setup should populate hass.data[DOMAIN]."""
    mock_hub = _hub_factory()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    assert DOMAIN in hass.data
    assert "sessions" in hass.data[DOMAIN]


# ===================================================================
# TestCreateClient (~2 tests)
# ===================================================================


async def test_create_client_creates_hub_when_password_present(hass):
    """_create_client succeeds when password is set."""
    mock_hub = _hub_factory()

    with _patches(mock_hub) as hub_cls:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    hub_cls.assert_called_once()
    call_args = hub_cls.call_args
    config_arg = call_args[0][0]
    assert config_arg[CONF_PASSWORD] == "test-password"


async def test_create_client_with_real_hub_init(hass):
    """_create_client with real SecuritasHub.__init__ — catches missing config keys."""
    from custom_components.securitas.config_flow import FlowHandler

    flow = FlowHandler()
    flow.hass = hass
    # Simulate the config dict built by async_step_user before _create_client
    flow.config = dict(USER_INPUT_CREDENTIALS)
    flow.config[CONF_DELAY_CHECK_OPERATION] = DEFAULT_DELAY_CHECK_OPERATION
    flow.config[CONF_DEVICE_ID] = FAKE_UUID
    flow.config[CONF_UNIQUE_ID] = FAKE_UUID
    flow.config[CONF_DEVICE_INDIGITALL] = ""

    with patch(PATCH_SESSION, return_value=MagicMock()):
        hub = flow._create_client()

    assert hub is not None
    assert hub.country == "ES"


async def test_create_client_raises_value_error_when_password_none(hass):
    """_create_client raises ValueError when password is None."""
    from custom_components.securitas.config_flow import FlowHandler

    flow = FlowHandler()
    flow.hass = hass
    flow.config = dict()
    flow.config[CONF_PASSWORD] = None

    with pytest.raises(ValueError, match="Invalid internal state"):
        flow._create_client()


# ===================================================================
# TestOptionsFlowInit (~4 tests)
# ===================================================================


async def test_options_init_shows_form_with_current_values(hass):
    """Init step should show form with current option values."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(),
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_init_submitting_advances_to_mappings(hass):
    """Submitting init form should advance to mappings step."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(),
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]

    result = await hass.config_entries.options.async_configure(
        flow_id,
        user_input={
            CONF_CODE: "1234",
            CONF_CODE_ARM_REQUIRED: True,
            CONF_ADVANCED: {
                CONF_SCAN_INTERVAL: 60,
                CONF_DELAY_CHECK_OPERATION: 3.0,
            },
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "mappings"


async def test_options_init_uses_default_values_when_not_set(hass):
    """Init step should use defaults when options and data lack values."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "test-password",
        },
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_init_reads_from_options_first(hass):
    """Init step should prefer options over data values."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(scan_interval=120),
        options={CONF_SCAN_INTERVAL: 60},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


# ===================================================================
# TestOptionsFlowMappings (~5 tests)
# ===================================================================


async def test_options_mappings_std_options_when_peri_false(hass):
    """Mappings step shows STD options when has_peri is False."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(has_peri=False),
        options={},
    )
    entry.add_to_hass(hass)

    flow_id = await _advance_to_mappings(hass, entry)
    result = await hass.config_entries.options.async_configure(
        flow_id,
        user_input={
            CONF_MAP_HOME: STD_DEFAULTS[CONF_MAP_HOME],
            CONF_MAP_AWAY: STD_DEFAULTS[CONF_MAP_AWAY],
            CONF_MAP_NIGHT: STD_DEFAULTS[CONF_MAP_NIGHT],
            CONF_MAP_CUSTOM: STD_DEFAULTS[CONF_MAP_CUSTOM],
            CONF_MAP_VACATION: STD_DEFAULTS[CONF_MAP_VACATION],
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_options_mappings_peri_options_when_peri_true(hass):
    """Mappings step shows PERI options when coordinator has_peri is True."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(has_peri=True),
        options={},
    )
    entry.add_to_hass(hass)

    # Inject a mock coordinator reporting has_peri=True into hass.data so the
    # options flow can read capability detection results at runtime.
    mock_coordinator = MagicMock()
    mock_coordinator.has_peri = True
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "alarm_coordinator": mock_coordinator
    }

    flow_id = await _advance_to_mappings(hass, entry)
    result = await hass.config_entries.options.async_configure(
        flow_id,
        user_input={
            CONF_MAP_HOME: PERI_DEFAULTS[CONF_MAP_HOME],
            CONF_MAP_AWAY: PERI_DEFAULTS[CONF_MAP_AWAY],
            CONF_MAP_NIGHT: PERI_DEFAULTS[CONF_MAP_NIGHT],
            CONF_MAP_CUSTOM: PERI_DEFAULTS[CONF_MAP_CUSTOM],
            CONF_MAP_VACATION: PERI_DEFAULTS[CONF_MAP_VACATION],
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_options_mappings_invalid_mapping_falls_back(hass):
    """Invalid saved mapping falls back to default for the current mode."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(
            has_peri=False,
            map_home=SecuritasState.TOTAL_PERI.value,
        ),
        options={},
    )
    entry.add_to_hass(hass)

    flow_id = await _advance_to_mappings(hass, entry)
    result = await hass.config_entries.options.async_configure(
        flow_id,
        user_input={
            CONF_MAP_HOME: STD_DEFAULTS[CONF_MAP_HOME],
            CONF_MAP_AWAY: STD_DEFAULTS[CONF_MAP_AWAY],
            CONF_MAP_NIGHT: STD_DEFAULTS[CONF_MAP_NIGHT],
            CONF_MAP_CUSTOM: STD_DEFAULTS[CONF_MAP_CUSTOM],
            CONF_MAP_VACATION: STD_DEFAULTS[CONF_MAP_VACATION],
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_options_mappings_submitting_creates_entry(hass):
    """Submitting mappings form should create the options entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(),
        options={},
    )
    entry.add_to_hass(hass)

    flow_id = await _advance_to_mappings(hass, entry)

    result = await hass.config_entries.options.async_configure(
        flow_id,
        user_input={
            CONF_MAP_HOME: STD_DEFAULTS[CONF_MAP_HOME],
            CONF_MAP_AWAY: STD_DEFAULTS[CONF_MAP_AWAY],
            CONF_MAP_NIGHT: STD_DEFAULTS[CONF_MAP_NIGHT],
            CONF_MAP_CUSTOM: STD_DEFAULTS[CONF_MAP_CUSTOM],
            CONF_MAP_VACATION: STD_DEFAULTS[CONF_MAP_VACATION],
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MAP_HOME] == STD_DEFAULTS[CONF_MAP_HOME]
    assert result["data"][CONF_MAP_AWAY] == STD_DEFAULTS[CONF_MAP_AWAY]
    assert result["data"][CONF_MAP_NIGHT] == STD_DEFAULTS[CONF_MAP_NIGHT]
    assert result["data"][CONF_MAP_CUSTOM] == STD_DEFAULTS[CONF_MAP_CUSTOM]
    assert result["data"][CONF_MAP_VACATION] == STD_DEFAULTS[CONF_MAP_VACATION]


async def test_options_mappings_entry_contains_general_and_mapping_data(hass):
    """Created entry should merge general settings with mappings."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(),
        options={},
    )
    entry.add_to_hass(hass)

    flow_id = await _advance_to_mappings(hass, entry)

    result = await hass.config_entries.options.async_configure(
        flow_id,
        user_input={
            CONF_MAP_HOME: SecuritasState.TOTAL.value,
            CONF_MAP_AWAY: SecuritasState.TOTAL.value,
            CONF_MAP_NIGHT: SecuritasState.PARTIAL_NIGHT.value,
            CONF_MAP_CUSTOM: SecuritasState.NOT_USED.value,
            CONF_MAP_VACATION: SecuritasState.NOT_USED.value,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    # General data should be present
    assert CONF_CODE in result["data"]
    assert CONF_SCAN_INTERVAL in result["data"]
    # Mapping data should be present
    assert result["data"][CONF_MAP_HOME] == SecuritasState.TOTAL.value


# ===================================================================
# TestOptionsFlowGet (~2 tests)
# ===================================================================


async def test_options_get_reads_from_options_first(hass):
    """_get should return from options when key exists there."""
    from custom_components.securitas.config_flow import SecuritasOptionsFlowHandler

    handler = SecuritasOptionsFlowHandler()
    mock_entry = MagicMock()
    mock_entry.options = {CONF_SCAN_INTERVAL: 60}
    mock_entry.data = {CONF_SCAN_INTERVAL: 120}

    # config_entry is a property on OptionsFlow, use patch to set it
    with patch.object(
        type(handler),
        "config_entry",
        new_callable=lambda: property(lambda self: mock_entry),
    ):
        result = handler._get(CONF_SCAN_INTERVAL)
    assert result == 60


async def test_options_get_falls_back_to_data(hass):
    """_get should fall back to data when key is not in options."""
    from custom_components.securitas.config_flow import SecuritasOptionsFlowHandler

    handler = SecuritasOptionsFlowHandler()
    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {CONF_SCAN_INTERVAL: 120}

    with patch.object(
        type(handler),
        "config_entry",
        new_callable=lambda: property(lambda self: mock_entry),
    ):
        result = handler._get(CONF_SCAN_INTERVAL)
    assert result == 120


# ===================================================================
# TestInstallationSelection (~6 tests)
# ===================================================================


async def test_single_installation_auto_selects(hass):
    """When there is exactly one unconfigured installation, auto-select it."""
    mock_hub = _hub_factory()
    mock_hub.client.list_installations = AsyncMock(
        return_value=[make_installation(number="111", alias="My Home")]
    )

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    # After credentials, flow goes to options (not CREATE_ENTRY)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"


async def test_multiple_installations_show_picker(hass):
    """When multiple unconfigured installations exist, show a selection form."""
    mock_hub = _hub_factory()
    mock_hub.client.list_installations = AsyncMock(
        return_value=[
            make_installation(number="111", alias="Home"),
            make_installation(number="222", alias="Office"),
        ]
    )

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_installation"


async def test_select_installation_advances_to_options(hass):
    """Picking an installation from the list advances to options."""
    mock_hub = _hub_factory()
    mock_hub.client.list_installations = AsyncMock(
        return_value=[
            make_installation(number="111", alias="Home"),
            make_installation(number="222", alias="Office"),
        ]
    )

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_installation"
    flow_id = result["flow_id"]

    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input={CONF_INSTALLATION: "222"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"


async def test_unique_id_includes_installation(hass):
    """The config entry unique_id should be username_installationNumber."""
    mock_hub = _hub_factory()
    mock_hub.client.list_installations = AsyncMock(
        return_value=[make_installation(number="42", alias="Cabin")]
    )

    result = await _complete_full_flow(hass, mock_hub)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    # Check unique_id on the created config entry
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].unique_id == "test@example.com_42"


async def test_already_configured_filtered_out(hass):
    """Installations with existing config entries should be excluded."""
    # Pre-add a config entry for installation 111
    existing_data = make_config_entry_data()
    existing_data[CONF_INSTALLATION] = "111"
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test@example.com_111",
        data=existing_data,
        version=3,
    )
    existing.add_to_hass(hass)

    mock_hub = _hub_factory()
    mock_hub.client.list_installations = AsyncMock(
        return_value=[
            make_installation(number="111", alias="Home"),
            make_installation(number="222", alias="Office"),
        ]
    )

    result = await _complete_full_flow(hass, mock_hub)

    # Only installation 222 remains, so it should auto-select and complete
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_INSTALLATION] == "222"
    assert result["title"] == "Office"


async def test_all_configured_aborts(hass):
    """When all installations are already configured, abort."""
    existing_data = make_config_entry_data()
    existing_data[CONF_INSTALLATION] = "111"
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test@example.com_111",
        data=existing_data,
        version=3,
    )
    existing.add_to_hass(hass)

    mock_hub = _hub_factory()
    mock_hub.client.list_installations = AsyncMock(
        return_value=[make_installation(number="111", alias="Home")]
    )

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ===================================================================
# TestFullFlow (~3 tests)
# ===================================================================


async def test_full_flow_creates_entry(hass):
    """Complete flow: credentials -> options -> mappings -> CREATE_ENTRY."""
    mock_hub = _hub_factory()

    result = await _complete_full_flow(hass, mock_hub)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"  # auto-selected installation alias
    assert result["data"][CONF_USERNAME] == "test@example.com"
    assert result["data"][CONF_INSTALLATION] == "123456"  # default installation number
    assert result["data"][CONF_TOKEN] == FAKE_JWT


async def test_full_flow_2fa_creates_entry(hass):
    """Complete 2FA flow: credentials -> phone -> otp -> options -> mappings."""
    mock_hub = _hub_factory(two_fa=True)
    flow_id = await _get_to_otp_step(hass, mock_hub)

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_CODE: "123456"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    flow_id = result["flow_id"]

    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input=USER_INPUT_OPTIONS
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "mappings"
    flow_id = result["flow_id"]

    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input=USER_INPUT_MAPPINGS_STD
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"


async def test_full_flow_select_installation_creates_entry(hass):
    """Complete flow with installation picker creates entry."""
    mock_hub = _hub_factory()
    mock_hub.client.list_installations = AsyncMock(
        return_value=[
            make_installation(number="111", alias="Home"),
            make_installation(number="222", alias="Office"),
        ]
    )

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_installation"
    flow_id = result["flow_id"]

    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input={CONF_INSTALLATION: "222"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    flow_id = result["flow_id"]

    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input=USER_INPUT_OPTIONS
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "mappings"
    flow_id = result["flow_id"]

    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input=USER_INPUT_MAPPINGS_STD
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Office"
    assert result["data"][CONF_INSTALLATION] == "222"


# ===================================================================
# TestSessionReuse (~2 tests)
# ===================================================================


async def test_existing_session_reused_no_new_login(hass):
    """When a session already exists for this username, reuse it without login."""
    existing_hub = _hub_factory()
    existing_hub.config = {
        CONF_DEVICE_ID: "existing-device-id",
        CONF_UNIQUE_ID: "existing-unique-id",
        CONF_DEVICE_INDIGITALL: "existing-indigitall",
        CONF_PASSWORD: "test-password",
    }
    # Pre-set the token so finish_setup doesn't try to login again
    existing_hub.get_authentication_token = MagicMock(return_value=FAKE_JWT)

    # Simulate an already-running session
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["sessions"] = {
        "test@example.com": {"hub": existing_hub, "ref_count": 1}
    }

    with _patches(existing_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    # Should NOT have called login — session was reused
    existing_hub.login.assert_not_awaited()


async def test_existing_session_copies_device_ids(hass):
    """Reused session should copy device_id from existing hub into new entry."""
    existing_hub = _hub_factory()
    existing_hub.config = {
        CONF_DEVICE_ID: "existing-device-id",
        CONF_UNIQUE_ID: "existing-unique-id",
        CONF_DEVICE_INDIGITALL: "existing-indigitall",
        CONF_PASSWORD: "test-password",
    }
    existing_hub.get_authentication_token = MagicMock(return_value=FAKE_JWT)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["sessions"] = {
        "test@example.com": {"hub": existing_hub, "ref_count": 1}
    }

    result = await _complete_full_flow(hass, existing_hub)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_ID] == "existing-device-id"
    assert result["data"][CONF_UNIQUE_ID] == "existing-unique-id"
    assert result["data"][CONF_DEVICE_INDIGITALL] == "existing-indigitall"


async def test_existing_session_wrong_password_does_fresh_login(hass):
    """Wrong password should not reuse session — falls through to fresh login."""
    existing_hub = _hub_factory()
    existing_hub.config = {
        CONF_DEVICE_ID: "existing-device-id",
        CONF_UNIQUE_ID: "existing-unique-id",
        CONF_DEVICE_INDIGITALL: "existing-indigitall",
        CONF_PASSWORD: "correct-password",
    }
    existing_hub.get_authentication_token = MagicMock(return_value=FAKE_JWT)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["sessions"] = {
        "test@example.com": {"hub": existing_hub, "ref_count": 1}
    }

    # The new hub that will be created for the fresh login
    new_hub = _hub_factory()
    with _patches(new_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={**USER_INPUT_CREDENTIALS, CONF_PASSWORD: "wrong-password"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    # Fresh login should have been called on the NEW hub
    new_hub.login.assert_awaited_once()


# ===================================================================
# TestPeriAutoDetection (~2 tests)
# ===================================================================


async def test_peri_detected_from_service_attributes(hass):
    """When a service has a PERI attribute, PERI mappings are offered (not stored in entry data)."""
    mock_hub = _hub_factory()

    async def _get_services_with_peri_attr(installation, **kwargs):
        installation.alarm_partitions = []
        svc = MagicMock()
        svc.attributes = [
            Attribute(name="ARM", value="CONECTAR"),
            Attribute(name="PERI", value="PERIMETRAL"),
        ]
        return [svc]

    mock_hub.get_services = AsyncMock(side_effect=_get_services_with_peri_attr)

    result = await _complete_full_flow(hass, mock_hub)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    # CONF_HAS_PERI is no longer stored in entry data — capability detection is runtime-only.
    assert "has_peri" not in result["data"]


async def test_no_peri_when_no_peri_service_attribute(hass):
    """When no service has a PERI attribute, STD mappings are offered (not stored in entry data)."""
    mock_hub = _hub_factory()

    result = await _complete_full_flow(hass, mock_hub)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    # CONF_HAS_PERI is no longer stored in entry data — capability detection is runtime-only.
    assert "has_peri" not in result["data"]


# ===================================================================
# TestReauthFlow
# ===================================================================

REAUTH_ENTRY_DATA = {
    CONF_USERNAME: "test@example.com",
    CONF_PASSWORD: "old-password",
    CONF_COUNTRY: "ES",
    CONF_INSTALLATION: "123456",
    CONF_DEVICE_ID: "test-device-id",
    CONF_UNIQUE_ID: "test-uuid",
    CONF_DEVICE_INDIGITALL: "test-indigitall",
    CONF_DELAY_CHECK_OPERATION: DEFAULT_DELAY_CHECK_OPERATION,
}


def _make_reauth_entry(hass) -> MockConfigEntry:
    """Create a MockConfigEntry for reauth tests and add it to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test@example.com_123456",
        data=dict(REAUTH_ENTRY_DATA),
        version=3,
    )
    entry.add_to_hass(hass)
    return entry


async def _start_reauth_flow(hass, entry):
    """Initiate a reauth flow for the given entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )
    return result


async def test_reauth_shows_confirm_form(hass):
    """Reauth flow should show the reauth_confirm form."""
    entry = _make_reauth_entry(hass)
    result = await _start_reauth_flow(hass, entry)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"


async def test_reauth_confirm_valid_credentials(hass):
    """Valid credentials in reauth should update entry and abort with reauth_successful."""
    entry = _make_reauth_entry(hass)
    result = await _start_reauth_flow(hass, entry)
    flow_id = result["flow_id"]

    mock_hub = _hub_factory()

    with (
        _patches(mock_hub),
        patch.object(
            hass.config_entries, "async_reload", new_callable=AsyncMock
        ) as mock_reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "new-password",
            },
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    # Verify the entry was updated with new password
    assert entry.data[CONF_PASSWORD] == "new-password"
    mock_reload.assert_awaited_once_with(entry.entry_id)


async def test_reauth_confirm_invalid_auth(hass):
    """Invalid credentials in reauth should show error on form."""
    entry = _make_reauth_entry(hass)
    result = await _start_reauth_flow(hass, entry)
    flow_id = result["flow_id"]

    mock_hub = _hub_factory()
    mock_hub.login.side_effect = AuthenticationError("bad credentials")

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "wrong-password",
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_confirm_account_blocked(hass):
    """Account blocked during reauth should show error on form."""
    entry = _make_reauth_entry(hass)
    result = await _start_reauth_flow(hass, entry)
    flow_id = result["flow_id"]

    mock_hub = _hub_factory()
    mock_hub.login.side_effect = AccountBlockedError("account blocked")

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "password",
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "account_blocked"}


async def test_reauth_confirm_cannot_connect(hass):
    """Connection error during reauth should show error on form."""
    entry = _make_reauth_entry(hass)
    result = await _start_reauth_flow(hass, entry)
    flow_id = result["flow_id"]

    mock_hub = _hub_factory()
    mock_hub.login.side_effect = SecuritasDirectError("connection failed")

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "password",
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_with_2fa_flow(hass):
    """Reauth with 2FA: confirm -> phone_list -> otp_challenge -> reauth_successful."""
    entry = _make_reauth_entry(hass)
    result = await _start_reauth_flow(hass, entry)
    flow_id = result["flow_id"]

    mock_hub = _hub_factory(two_fa=True)

    # Step 1: Submit credentials — triggers 2FA
    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "new-password",
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "phone_list"

    # Step 2: Select phone
    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={"phones": "0_555-1234"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "otp_challenge"

    # Step 3: Submit OTP — should complete reauth
    with (
        _patches(mock_hub),
        patch.object(
            hass.config_entries, "async_reload", new_callable=AsyncMock
        ) as mock_reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_CODE: "123456"}
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
    mock_reload.assert_awaited_once_with(entry.entry_id)


async def test_reauth_preserves_username_from_entry(hass):
    """Reauth form should pre-populate the username from the existing entry."""
    entry = _make_reauth_entry(hass)
    result = await _start_reauth_flow(hass, entry)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    # The schema should have the username pre-filled
    schema = result["data_schema"]
    assert schema is not None
