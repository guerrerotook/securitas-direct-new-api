"""Tests for the Verisure OWA config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.verisure_owa import (
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
from custom_components.verisure_owa.const import (
    CONF_ENABLE_ANNEX_PANEL,
    CONF_ENABLE_INTERIOR_PANEL,
    CONF_ENABLE_PERIMETER_PANEL,
    CONF_REFRESH_TOKEN,
)
from custom_components.verisure_owa.verisure_owa_api import (
    AccountBlockedError,
    Attribute,
    AuthenticationError,
    OtpPhone,
    PERI_DEFAULTS,
    STD_DEFAULTS,
    VerisureOwaError,
    VerisureOwaState,
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
    FAKE_REFRESH_TOKEN,
    make_config_entry_data,
    make_installation,
    make_securitas_hub_mock,
)

from pytest_homeassistant_custom_component.common import MockConfigEntry


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

PATCH_HUB = "custom_components.verisure_owa.config_flow.VerisureHub"
PATCH_SESSION = "custom_components.verisure_owa.config_flow.async_get_clientsession"
PATCH_UUID = "custom_components.verisure_owa.config_flow.generate_uuid"


def _hub_factory(*, two_fa: bool = False, **overrides):
    """Create a mock VerisureHub for config flow tests.

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
    """Create a mock class that mimics VerisureHub but returns hub_instance.

    MagicMock does not have a proper __name__ attribute, so we set it
    to make the mock behave like a real class.
    """
    mock_cls = MagicMock(return_value=hub_instance)
    mock_cls.__name__ = "VerisureHub"
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
    mock_hub.login.side_effect = VerisureOwaError("connection failed")

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
    from custom_components.verisure_owa.config_flow import FlowHandler

    mock_hub = _hub_factory()
    flow = FlowHandler()
    flow.hass = hass
    flow.hub = mock_hub
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

    mock_hub.send_sms_code = AsyncMock(side_effect=VerisureOwaError("API error"))

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_CODE: "123456"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "otp_challenge"
    assert result["errors"] == {"base": "invalid_otp"}


async def test_otp_challenge_expired_code_shows_otp_expired_error(hass):
    """OTP expired (auth-code 10002) re-shows phone list with otp_expired error.

    The API surfaces expiry as a GraphQL error with auth-code 10002 in the
    response body. The flow should restart 2FA so a fresh code can be sent,
    not re-show the OTP form with the misleading invalid_otp error.
    """
    mock_hub = _hub_factory(two_fa=True)
    flow_id = await _get_to_otp_step(hass, mock_hub)

    err = VerisureOwaError("OTP expired")
    err.response_body = {"errors": [{"data": {"auth-code": "10002"}}]}
    mock_hub.send_sms_code = AsyncMock(side_effect=err)

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_CODE: "123456"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "otp_expired"}


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


async def test_finish_setup_logs_in_advances_to_options(hass):
    """finish_setup should login (when no token yet) and advance to options."""
    mock_hub = _hub_factory()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    mock_hub.login.assert_awaited_once()
    mock_hub.get_authentication_token.assert_called_once()  # is None guard only


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
    """_create_client with real VerisureHub.__init__ — catches missing config keys."""
    from custom_components.verisure_owa.config_flow import FlowHandler

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
    from custom_components.verisure_owa.config_flow import FlowHandler

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
            map_home=VerisureOwaState.TOTAL_PERI.value,
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
            CONF_MAP_HOME: VerisureOwaState.TOTAL.value,
            CONF_MAP_AWAY: VerisureOwaState.TOTAL.value,
            CONF_MAP_NIGHT: VerisureOwaState.PARTIAL_NIGHT.value,
            CONF_MAP_CUSTOM: VerisureOwaState.NOT_USED.value,
            CONF_MAP_VACATION: VerisureOwaState.NOT_USED.value,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    # General data should be present
    assert CONF_CODE in result["data"]
    assert CONF_SCAN_INTERVAL in result["data"]
    # Mapping data should be present
    assert result["data"][CONF_MAP_HOME] == VerisureOwaState.TOTAL.value


# ===================================================================
# TestOptionsFlowGet (~2 tests)
# ===================================================================


async def test_options_get_reads_from_options_first(hass):
    """_get should return from options when key exists there."""
    from custom_components.verisure_owa.config_flow import VerisureOptionsFlowHandler

    handler = VerisureOptionsFlowHandler()
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
    from custom_components.verisure_owa.config_flow import VerisureOptionsFlowHandler

    handler = VerisureOptionsFlowHandler()
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
# TestInitialFlowPanelToggles
#
# When peri/annex is detected during the initial config flow, the
# user should be able to enable the corresponding sub-panels right
# there — without having to dig through Configure after CREATE_ENTRY.
# ===================================================================


def _hub_with_peri_capability():
    """Mock hub that returns capabilities including PERI."""
    mock_hub = _hub_factory()
    mock_hub.client.get_supported_commands = MagicMock(return_value=frozenset({"PERI"}))
    return mock_hub


def _initial_options_form_keys(result) -> set[str]:
    """Return the unwrapped key names of the rendered initial options form."""
    keys: set[str] = set()
    for key in result["data_schema"].schema:
        name = getattr(key, "schema", key)
        keys.add(name)
    return keys


async def test_initial_options_step_shows_perimeter_toggle_when_peri_detected(
    hass,
):
    """The initial flow's options page must render the panel-enable toggles
    when the underlying installation has the corresponding capability — same
    surface as the post-setup Configure dialog.
    """
    mock_hub = _hub_with_peri_capability()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    keys = _initial_options_form_keys(result)
    assert CONF_ENABLE_PERIMETER_PANEL in keys
    assert CONF_ENABLE_INTERIOR_PANEL in keys


async def test_initial_options_step_omits_toggles_when_no_capability(hass):
    """Without peri/annex detected, the initial flow's options page must
    NOT render the panel-enable toggles (matches Configure dialog behaviour).
    """
    mock_hub = _hub_factory()  # no PERI in capabilities

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_CREDENTIALS
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    keys = _initial_options_form_keys(result)
    assert CONF_ENABLE_PERIMETER_PANEL not in keys
    assert CONF_ENABLE_INTERIOR_PANEL not in keys
    assert CONF_ENABLE_ANNEX_PANEL not in keys


async def test_initial_flow_persists_panel_toggles_to_entry_options(hass):
    """When user enables the panel toggles during initial setup, the
    created entry's options dict must carry them — so the post-setup
    OptionsFlow opens with them already enabled rather than defaulting
    back to off.
    """
    mock_hub = _hub_with_peri_capability()

    options_with_toggles = {
        **USER_INPUT_OPTIONS,
        CONF_ENABLE_PERIMETER_PANEL: True,
        CONF_ENABLE_INTERIOR_PANEL: True,
    }

    result = await _complete_full_flow(hass, mock_hub, options=options_with_toggles)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_ENABLE_PERIMETER_PANEL] is True
    assert result["options"][CONF_ENABLE_INTERIOR_PANEL] is True
    # And they should NOT pollute entry.data, where the OptionsFlow
    # doesn't expect to find them.
    assert CONF_ENABLE_PERIMETER_PANEL not in result["data"]
    assert CONF_ENABLE_INTERIOR_PANEL not in result["data"]


# ===================================================================
# TestFlowCapabilitiesPublishResolve
#
# Race fix: when async_setup_entry hasn't yet stored the alarm
# coordinator under entry.entry_id (still inside its `await get_services`),
# the options flow can't read coordinator.has_peri.  The config flow's
# _select_installation already detected the capability values, so we
# publish them to hass.data[DOMAIN]["flow_capabilities"][installation]
# and the options flow falls back to that.
# ===================================================================


async def test_resolve_flow_capabilities_uses_coordinator_when_populated(hass):
    """When the coordinator has populated capabilities, prefer it."""
    from custom_components.verisure_owa import _resolve_flow_capabilities

    coord = MagicMock()
    coord.capabilities_populated = True
    coord.has_peri = True
    coord.has_annex = False

    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {CONF_INSTALLATION: "111"}

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"alarm_coordinator": coord}
    # Stale opposite values in the cache must NOT win over a populated coord.
    hass.data[DOMAIN]["flow_capabilities"] = {
        "111": {"has_peri": False, "has_annex": True}
    }

    has_peri, has_annex = _resolve_flow_capabilities(hass, entry)

    assert (has_peri, has_annex) == (True, False)


async def test_resolve_flow_capabilities_falls_back_to_cache_when_coord_missing(hass):
    """When entry.entry_id isn't yet in hass.data, fall back to the cache."""
    from custom_components.verisure_owa import _resolve_flow_capabilities

    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {CONF_INSTALLATION: "111"}
    # Note: no entry-id-keyed dict in hass.data — this is the race window.
    hass.data.setdefault(DOMAIN, {})["flow_capabilities"] = {
        "111": {"has_peri": True, "has_annex": False}
    }

    has_peri, has_annex = _resolve_flow_capabilities(hass, entry)

    assert (has_peri, has_annex) == (True, False)


async def test_resolve_flow_capabilities_falls_back_when_coord_unpopulated(hass):
    """A coordinator that hasn't run yet has has_peri=False as the
    default — that's not authoritative.  Fall back to the cache."""
    from custom_components.verisure_owa import _resolve_flow_capabilities

    coord = MagicMock()
    coord.capabilities_populated = False
    coord.has_peri = False
    coord.has_annex = False

    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {CONF_INSTALLATION: "111"}

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"alarm_coordinator": coord}
    hass.data[DOMAIN]["flow_capabilities"] = {
        "111": {"has_peri": True, "has_annex": True}
    }

    has_peri, has_annex = _resolve_flow_capabilities(hass, entry)

    assert (has_peri, has_annex) == (True, True)


async def test_resolve_flow_capabilities_returns_false_when_nothing_known(hass):
    """No coordinator and no cache → (False, False) — current behaviour."""
    from custom_components.verisure_owa import _resolve_flow_capabilities

    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {CONF_INSTALLATION: "111"}
    hass.data.setdefault(DOMAIN, {})

    has_peri, has_annex = _resolve_flow_capabilities(hass, entry)

    assert (has_peri, has_annex) == (False, False)


def _form_has_field(result, field_name: str) -> bool:
    """Return True if the rendered form schema contains a key with this name."""
    schema = result["data_schema"].schema
    for key in schema:
        # vol.Required / vol.Optional wrap the key — unwrap with `.schema`.
        name = getattr(key, "schema", key)
        if name == field_name:
            return True
    return False


async def test_options_init_renders_peri_toggle_via_published_cache(hass):
    """Race fix: options init shows the perimeter toggle even if the
    coordinator dict isn't in hass.data yet, by reading the published
    capability cache."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**make_config_entry_data(has_peri=True), CONF_INSTALLATION: "111"},
        options={},
    )
    entry.add_to_hass(hass)

    # Simulate the race: published cache exists, but no alarm_coordinator
    # under entry.entry_id yet.
    hass.data.setdefault(DOMAIN, {})["flow_capabilities"] = {
        "111": {"has_peri": True, "has_annex": False}
    }

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    assert _form_has_field(result, CONF_ENABLE_PERIMETER_PANEL)


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


async def test_full_flow_does_not_persist_auth_token(hass):
    """Auth tokens are short-lived and must never be written to entry.data."""
    mock_hub = _hub_factory()

    result = await _complete_full_flow(hass, mock_hub)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert CONF_TOKEN not in result["data"]


async def test_full_flow_persists_refresh_token_not_password(hass):
    """Entry data must hold the refresh token, not the long-term password.

    The integration uses the refresh token on reload to obtain a fresh auth
    token without ever needing the password again.
    """
    mock_hub = _hub_factory()

    result = await _complete_full_flow(hass, mock_hub)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_REFRESH_TOKEN] == FAKE_REFRESH_TOKEN
    assert CONF_PASSWORD not in result["data"]


async def test_full_flow_aborts_when_no_refresh_token_returned(hass):
    """If login succeeds but no refresh token comes back, abort instead of persisting
    a passwordless+refreshless entry that cannot authenticate on restart.
    """
    mock_hub = _hub_factory()
    mock_hub.get_refresh_token = MagicMock(return_value="")

    result = await _complete_full_flow(hass, mock_hub)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_refresh_token"


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


async def test_existing_session_reused_regardless_of_password(hass):
    """Existing session is reused on second-add even if the supplied password differs.

    Re-checking the password is security theatre — anyone with HA admin access
    can already drive the running session. After dropping password persistence
    there's also nothing to compare against.
    """
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

    # If session reuse fails and a fresh hub gets constructed, the patch will
    # surface it via new_hub.login being awaited — the assertion below catches that.
    new_hub = _hub_factory()
    with _patches(new_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={**USER_INPUT_CREDENTIALS, CONF_PASSWORD: "different-password"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "options"
    new_hub.login.assert_not_awaited()
    existing_hub.login.assert_not_awaited()


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
    """Valid reauth captures a fresh refresh token; password is never persisted."""
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
    assert entry.data[CONF_REFRESH_TOKEN] == FAKE_REFRESH_TOKEN
    assert CONF_PASSWORD not in entry.data
    mock_reload.assert_awaited_once_with(entry.entry_id)


async def test_reauth_aborts_when_no_refresh_token_returned(hass):
    """If reauth login succeeds but no refresh token is captured, abort and leave the
    existing entry untouched — never overwrite a working password with empty data.
    """
    entry = _make_reauth_entry(hass)
    original_data = dict(entry.data)
    result = await _start_reauth_flow(hass, entry)
    flow_id = result["flow_id"]

    mock_hub = _hub_factory()
    mock_hub.get_refresh_token = MagicMock(return_value="")

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
    assert result["reason"] == "no_refresh_token"
    assert dict(entry.data) == original_data
    mock_reload.assert_not_awaited()


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
    mock_hub.login.side_effect = VerisureOwaError("connection failed")

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
    assert entry.data[CONF_REFRESH_TOKEN] == FAKE_REFRESH_TOKEN
    assert CONF_PASSWORD not in entry.data
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


# ===================================================================
# TestSubPanelToggleVisibility (~6 tests)
# ===================================================================


def _schema_keys(data_schema) -> set[str]:
    """Extract the string keys from a voluptuous Schema's top-level dict."""
    keys = set()
    for marker in data_schema.schema.keys():
        if hasattr(marker, "schema"):
            keys.add(marker.schema)
        else:
            keys.add(marker)
    return keys


def _make_entry_with_coordinator(
    hass, *, has_peri: bool, has_annex: bool, options: dict | None = None
):
    """Create a MockConfigEntry and inject a mock coordinator into hass.data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(),
        options=options or {},
    )
    entry.add_to_hass(hass)
    mock_coordinator = MagicMock()
    mock_coordinator.has_peri = has_peri
    mock_coordinator.has_annex = has_annex
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "alarm_coordinator": mock_coordinator
    }
    return entry


async def test_subpanel_perimeter_toggle_hidden_when_no_peri(hass):
    """No toggles in init schema when has_peri=False and has_annex=False."""
    entry = _make_entry_with_coordinator(hass, has_peri=False, has_annex=False)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    keys = _schema_keys(result["data_schema"])
    assert CONF_ENABLE_PERIMETER_PANEL not in keys
    assert CONF_ENABLE_ANNEX_PANEL not in keys
    assert CONF_ENABLE_INTERIOR_PANEL not in keys


async def test_subpanel_perimeter_toggle_shown_when_has_peri(hass):
    """PERIMETER + INTERIOR toggles shown when has_peri=True regardless of toggle state."""
    entry = _make_entry_with_coordinator(hass, has_peri=True, has_annex=False)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    keys = _schema_keys(result["data_schema"])
    assert CONF_ENABLE_PERIMETER_PANEL in keys
    assert CONF_ENABLE_ANNEX_PANEL not in keys
    assert CONF_ENABLE_INTERIOR_PANEL in keys


async def test_subpanel_interior_toggle_visible_when_has_annex_only(hass):
    """INTERIOR toggle shown when has_annex=True (sibling capability present)."""
    entry = _make_entry_with_coordinator(
        hass, has_peri=False, has_annex=True, options={}
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    keys = _schema_keys(result["data_schema"])
    assert CONF_ENABLE_INTERIOR_PANEL in keys


async def test_subpanel_all_toggles_visible_with_full_caps(hass):
    """All three toggles shown when has_peri=True and has_annex=True, regardless of toggle state."""
    entry = _make_entry_with_coordinator(
        hass,
        has_peri=True,
        has_annex=True,
        options={},
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    keys = _schema_keys(result["data_schema"])
    assert CONF_ENABLE_PERIMETER_PANEL in keys
    assert CONF_ENABLE_ANNEX_PANEL in keys
    assert CONF_ENABLE_INTERIOR_PANEL in keys


# ===================================================================
# TestLockAutomationsOptionsStep (~5 tests)
# ===================================================================


def _make_entry_with_locks(
    hass,
    *,
    registered_locks: list[dict],
    enabled_circuits: set[str] | None = None,
    entry_options: dict | None = None,
):
    """Create MockConfigEntry and inject registered_locks + circuit options into hass.data."""
    from custom_components.verisure_owa.const import (
        CONF_ENABLE_ANNEX_PANEL,
        CONF_ENABLE_INTERIOR_PANEL,
        CONF_ENABLE_PERIMETER_PANEL,
    )

    circuits = enabled_circuits if enabled_circuits is not None else {"interior"}
    options = dict(entry_options) if entry_options else {}
    # Map circuit names to option keys
    options.setdefault(CONF_ENABLE_INTERIOR_PANEL, "interior" in circuits)
    options.setdefault(CONF_ENABLE_PERIMETER_PANEL, "perimeter" in circuits)
    options.setdefault(CONF_ENABLE_ANNEX_PANEL, "annex" in circuits)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(),
        options=options,
    )
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "registered_locks": registered_locks,
    }
    return entry


async def _advance_to_lock_automations(hass, entry):
    """Navigate init -> mappings -> lock_automations and return flow_id."""
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
    assert result["step_id"] == "lock_automations", (
        f"Expected lock_automations step, got {result['step_id']}"
    )
    return result["flow_id"]


async def test_lock_automations_renders_one_section_per_lock(hass):
    """Form should have two fields per registered lock (lock_on_arm, unlock_disarms)."""
    entry = _make_entry_with_locks(
        hass,
        registered_locks=[
            {"device_id": "lockA", "alias": "Front Door"},
            {"device_id": "lockB", "alias": "Back Door"},
        ],
        enabled_circuits={"interior", "perimeter", "annex"},
    )
    flow_id = await _advance_to_lock_automations(hass, entry)

    result = await hass.config_entries.options.async_configure(flow_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "lock_automations"
    keys = {str(k) for k in result["data_schema"].schema.keys()}
    assert any("lockA" in k for k in keys)
    assert any("lockB" in k for k in keys)


def _circuit_options_from_schema(schema) -> set[str]:
    """Extract circuit labels from all multi_select values in a lock-automations schema."""
    circuits: set[str] = set()
    for v in schema.schema.values():
        if hasattr(v, "options"):
            circuits.update(v.options.keys())
    return circuits


async def test_lock_automations_disabled_circuits_excluded(hass):
    """Circuits not enabled on this installation should not appear as options."""
    entry = _make_entry_with_locks(
        hass,
        registered_locks=[{"device_id": "lockA", "alias": "Front Door"}],
        enabled_circuits={"interior"},
    )
    flow_id = await _advance_to_lock_automations(hass, entry)

    result = await hass.config_entries.options.async_configure(flow_id)

    circuits = _circuit_options_from_schema(result["data_schema"])
    assert "interior" in circuits
    assert "perimeter" not in circuits
    assert "annex" not in circuits


async def test_lock_automations_interior_always_present_even_when_panel_disabled(hass):
    """Interior is always available on the combined panel; the lock-automations
    UI should always offer it as a circuit option, regardless of whether the
    interior sub-panel entity is enabled."""
    entry = _make_entry_with_locks(
        hass,
        registered_locks=[{"device_id": "lockA", "alias": "Front Door"}],
        # Explicitly disable all sub-panels including interior.
        enabled_circuits=set(),
    )
    flow_id = await _advance_to_lock_automations(hass, entry)

    result = await hass.config_entries.options.async_configure(flow_id)

    circuits = _circuit_options_from_schema(result["data_schema"])
    assert "interior" in circuits
    assert "perimeter" not in circuits
    assert "annex" not in circuits


async def test_lock_automations_submission_persists_per_lock_config(hass):
    """Submitting the form should save per-lock config in CONF_LOCK_AUTOMATIONS."""
    from custom_components.verisure_owa.const import CONF_LOCK_AUTOMATIONS

    entry = _make_entry_with_locks(
        hass,
        registered_locks=[{"device_id": "lockA", "alias": "Front Door"}],
        enabled_circuits={"interior", "perimeter", "annex"},
    )
    flow_id = await _advance_to_lock_automations(hass, entry)

    result = await hass.config_entries.options.async_configure(
        flow_id,
        user_input={
            "lockA__lock_on_arm": ["interior", "perimeter"],
            "lockA__unlock_disarms": ["interior"],
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert CONF_LOCK_AUTOMATIONS in result["data"]
    assert result["data"][CONF_LOCK_AUTOMATIONS]["lockA"] == {
        "lock_on_arm": ["interior", "perimeter"],
        "unlock_disarms": ["interior"],
    }


async def test_lock_automations_re_edit_prefills_existing_values(hass):
    """Re-opening options flow should prefill previously saved lock automation values."""
    from custom_components.verisure_owa.const import CONF_LOCK_AUTOMATIONS

    entry = _make_entry_with_locks(
        hass,
        registered_locks=[{"device_id": "lockA", "alias": "Front Door"}],
        enabled_circuits={"interior", "perimeter", "annex"},
        entry_options={
            CONF_LOCK_AUTOMATIONS: {
                "lockA": {
                    "lock_on_arm": ["perimeter"],
                    "unlock_disarms": ["interior", "annex"],
                }
            }
        },
    )
    flow_id = await _advance_to_lock_automations(hass, entry)

    result = await hass.config_entries.options.async_configure(flow_id)

    assert result["type"] == FlowResultType.FORM
    schema = result["data_schema"].schema
    for k, _v in schema.items():
        key_str = str(k)
        if "lockA__lock_on_arm" in key_str:
            assert k.default() == ["perimeter"]
        if "lockA__unlock_disarms" in key_str:
            assert k.default() == ["interior", "annex"]


async def test_lock_automations_skipped_when_no_locks_discovered(hass):
    """When no locks are registered, the step should be skipped (CREATE_ENTRY)."""
    entry = _make_entry_with_locks(
        hass,
        registered_locks=[],
        enabled_circuits={"interior"},
    )
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
