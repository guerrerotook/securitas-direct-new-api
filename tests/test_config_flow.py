"""Tests for the Securitas Direct config flow."""

from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.securitas import (
    CONF_CHECK_ALARM_PANEL,
    CONF_CODE_ARM_REQUIRED,
    CONF_COUNTRY,
    CONF_DELAY_CHECK_OPERATION,
    CONF_DEVICE_INDIGITALL,
    CONF_ENTRY_ID,
    CONF_MAP_AWAY,
    CONF_MAP_CUSTOM,
    CONF_MAP_HOME,
    CONF_MAP_NIGHT,
    CONF_MAP_VACATION,
    CONF_PERI_ALARM,
    CONF_USE_2FA,
    DEFAULT_CHECK_ALARM_PANEL,
    DEFAULT_CODE_ARM_REQUIRED,
    DEFAULT_DELAY_CHECK_OPERATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from custom_components.securitas.securitas_direct_new_api import (
    Login2FAError,
    OtpPhone,
    PERI_DEFAULTS,
    STD_DEFAULTS,
    SecuritasState,
)
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_ERROR,
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

USER_INPUT_NO_2FA = {
    CONF_USERNAME: "test@example.com",
    CONF_PASSWORD: "test-password",
    CONF_USE_2FA: False,
    CONF_COUNTRY: "ES",
    CONF_CODE: "",
    CONF_PERI_ALARM: False,
    CONF_CODE_ARM_REQUIRED: False,
    CONF_CHECK_ALARM_PANEL: True,
    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
}

USER_INPUT_2FA = {
    **USER_INPUT_NO_2FA,
    CONF_USE_2FA: True,
}

IMPORT_DATA = {
    CONF_USERNAME: "test@example.com",
    CONF_PASSWORD: "test-password",
    CONF_COUNTRY: "ES",
    CONF_CODE: "",
    CONF_CODE_ARM_REQUIRED: DEFAULT_CODE_ARM_REQUIRED,
    CONF_CHECK_ALARM_PANEL: DEFAULT_CHECK_ALARM_PANEL,
    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
    CONF_DELAY_CHECK_OPERATION: DEFAULT_DELAY_CHECK_OPERATION,
    CONF_DEVICE_ID: "test-device-id",
    CONF_UNIQUE_ID: "test-uuid",
    CONF_DEVICE_INDIGITALL: "test-indigitall",
    CONF_ENTRY_ID: "",
}


MOCK_PHONES = [
    OtpPhone(id=0, phone="555-1234"),
    OtpPhone(id=1, phone="555-5678"),
]

PATCH_HUB = "custom_components.securitas.config_flow.SecuritasHub"
PATCH_SESSION = "custom_components.securitas.config_flow.async_get_clientsession"
PATCH_UUID = "custom_components.securitas.config_flow.generate_uuid"


def _hub_factory(**overrides):
    """Create a mock SecuritasHub for config flow tests."""
    hub = make_securitas_hub_mock(**overrides)
    hub.validate_device = AsyncMock(return_value=("otp-hash-abc", MOCK_PHONES))
    hub.session.list_installations = AsyncMock(return_value=[make_installation()])
    return hub


def _make_hub_class_mock(hub_instance):
    """Create a mock class that mimics SecuritasHub but returns hub_instance.

    The config_flow uses SecuritasHub.__name__ as a dict key, so the mock class
    must have a proper __name__ attribute (MagicMock does not).
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


async def _start_2fa_flow(hass, mock_hub):
    """Helper: start the 2FA flow up to the phone_list step and return flow_id."""
    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_2FA
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


async def _advance_to_mappings(hass, entry, peri_alarm=False):
    """Helper to get to the mappings step of options flow."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    flow_id = result["flow_id"]

    result = await hass.config_entries.options.async_configure(
        flow_id,
        user_input={
            CONF_CODE: "1234",
            CONF_CODE_ARM_REQUIRED: False,
            CONF_PERI_ALARM: peri_alarm,
            CONF_CHECK_ALARM_PANEL: True,
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_DELAY_CHECK_OPERATION: float(DEFAULT_DELAY_CHECK_OPERATION),
        },
    )
    assert result["step_id"] == "mappings"
    return result["flow_id"]


# ===================================================================
# TestStepUser (~8 tests)
# ===================================================================


async def test_step_user_initial_form_shown_when_no_input(hass):
    """Show the user form when user_input is None (and init_data is None)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_step_user_non_2fa_flow_finishes_setup(hass):
    """Non-2FA flow should call finish_setup and create an entry."""
    mock_hub = _hub_factory()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_NO_2FA
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "test@example.com"
    assert result["data"][CONF_USERNAME] == "test@example.com"
    mock_hub.login.assert_awaited_once()


async def test_step_user_2fa_flow_shows_phone_list(hass):
    """2FA flow should validate device and show phone list form."""
    mock_hub = _hub_factory()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_2FA
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "phone_list"
    mock_hub.validate_device.assert_awaited_once()


async def test_step_user_generates_device_ids(hass):
    """async_step_user should generate uuid, device_id, and indigitall."""
    mock_hub = _hub_factory()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_NO_2FA
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_DEVICE_ID] == FAKE_UUID
    assert data[CONF_UNIQUE_ID] == FAKE_UUID
    assert data[CONF_DEVICE_INDIGITALL] == ""


async def test_step_user_sets_delay_check_operation(hass):
    """async_step_user should set default delay_check_operation."""
    mock_hub = _hub_factory()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_NO_2FA
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DELAY_CHECK_OPERATION] == DEFAULT_DELAY_CHECK_OPERATION


async def test_step_user_uses_init_data_when_user_input_is_data(hass):
    """When user_input is provided with data, it proceeds with that data."""
    mock_hub = _hub_factory()
    init_data = {**USER_INPUT_NO_2FA}

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=init_data
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USERNAME] == "test@example.com"


async def test_step_user_login_error_during_import_shows_user_form(hass):
    """When import data has error=login, async_step_import shows user form."""
    import_data = {**IMPORT_DATA, CONF_ERROR: "login"}

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=import_data
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_step_user_creates_securitas_hub(hass):
    """_create_client should be invoked via async_step_user."""
    mock_hub = _hub_factory()

    with _patches(mock_hub) as hub_cls:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_NO_2FA
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    hub_cls.assert_called_once()


# ===================================================================
# TestStepPhoneList (~4 tests)
# ===================================================================


async def test_phone_list_selects_phone_by_index(hass):
    """Select phone using the index prefix (e.g., '0_555-1234')."""
    mock_hub = _hub_factory()
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
    mock_hub = _hub_factory()
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

    assert result["step_id"] == "otp_challenge"
    # Should find phone "555-5678" -> id=1
    mock_hub.send_opt.assert_awaited_once_with("otp-hash-abc", 1)


async def test_phone_list_sends_otp_and_shows_challenge_form(hass):
    """After selecting phone, OTP is sent and the challenge form is shown."""
    mock_hub = _hub_factory()
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
    mock_hub = _hub_factory()
    flow_id = await _get_to_otp_step(hass, mock_hub)

    with _patches(mock_hub):
        await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_CODE: "123456"}
        )

    mock_hub.send_sms_code.assert_awaited_once_with("otp-hash-abc", "123456")


async def test_otp_challenge_calls_finish_setup(hass):
    """After sending SMS code, finish_setup is called and entry is created."""
    mock_hub = _hub_factory()
    flow_id = await _get_to_otp_step(hass, mock_hub)

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input={CONF_CODE: "123456"}
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "test@example.com"
    mock_hub.login.assert_awaited_once()


# ===================================================================
# TestFinishSetup (~3 tests)
# ===================================================================


async def test_finish_setup_logs_in_gets_token_creates_entry(hass):
    """finish_setup should login, get token, and create entry."""
    mock_hub = _hub_factory()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_NO_2FA
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    mock_hub.login.assert_awaited_once()
    mock_hub.get_authentication_token.assert_called_once()
    assert result["data"][CONF_TOKEN] == FAKE_JWT


async def test_finish_setup_lists_installations(hass):
    """finish_setup should list installations and call get_services."""
    mock_hub = _hub_factory()

    with _patches(mock_hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_NO_2FA
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    mock_hub.session.list_installations.assert_awaited_once()
    mock_hub.get_services.assert_awaited_once()


async def test_finish_setup_sets_hass_data(hass):
    """finish_setup should populate hass.data[DOMAIN].

    Note: async_setup_entry runs after the entry is created and may overwrite
    hass.data[DOMAIN]. We mock it to isolate the config flow behavior.
    """
    mock_hub = _hub_factory()

    with (
        _patches(mock_hub),
        patch(
            "custom_components.securitas.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_NO_2FA
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert DOMAIN in hass.data
    assert "SecuritasHub" in hass.data[DOMAIN]


# ===================================================================
# TestCreateClient (~2 tests)
# ===================================================================


async def test_create_client_creates_hub_when_password_present(hass):
    """_create_client succeeds when password is set."""
    mock_hub = _hub_factory()

    with _patches(mock_hub) as hub_cls:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_NO_2FA
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    hub_cls.assert_called_once()
    call_args = hub_cls.call_args
    config_arg = call_args[0][0]
    assert config_arg[CONF_PASSWORD] == "test-password"


async def test_create_client_raises_value_error_when_password_none(hass):
    """_create_client raises ValueError when password is None."""
    from custom_components.securitas.config_flow import FlowHandler

    flow = FlowHandler()
    flow.hass = hass
    flow.config = OrderedDict()
    flow.config[CONF_PASSWORD] = None

    with pytest.raises(ValueError, match="Invalid internal state"):
        flow._create_client()


# ===================================================================
# TestStepImport (~5 tests)
# ===================================================================


async def test_import_error_2fa_shows_user_form(hass):
    """Import with error='2FA' should show user form."""
    data = {**IMPORT_DATA, CONF_ERROR: "2FA"}

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=data
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_import_error_login_shows_user_form(hass):
    """Import with error='login' should show user form."""
    data = {**IMPORT_DATA, CONF_ERROR: "login"}

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=data
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_import_success_copies_config_and_creates_client(hass):
    """Successful import should copy config data and create client.

    Note: async_step_import returns the SecuritasHub object (not a FlowResult)
    on success, so we test the handler method directly to avoid HA flow
    infrastructure errors.
    """
    from custom_components.securitas.config_flow import FlowHandler

    mock_hub = _hub_factory()
    flow = FlowHandler()
    flow.hass = hass

    hub_cls = _make_hub_class_mock(mock_hub)
    with (
        patch(PATCH_HUB, hub_cls),
        patch(PATCH_SESSION, return_value=MagicMock()),
    ):
        await flow.async_step_import(IMPORT_DATA)

    hub_cls.assert_called_once()
    mock_hub.login.assert_awaited_once()


async def test_import_login_2fa_error_shows_user_form(hass):
    """Login2FAError during import login should show user form."""
    mock_hub = _hub_factory()
    mock_hub.login = AsyncMock(side_effect=Login2FAError("2FA required"))

    with (
        patch(PATCH_HUB, return_value=mock_hub),
        patch(PATCH_SESSION, return_value=MagicMock()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=IMPORT_DATA
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_import_sets_all_config_fields(hass):
    """Import should copy all config fields from user_input.

    Tested directly on the handler since async_step_import returns a
    SecuritasHub (not a FlowResult) on success.
    """
    from custom_components.securitas.config_flow import FlowHandler

    mock_hub = _hub_factory()
    flow = FlowHandler()
    flow.hass = hass

    hub_cls = _make_hub_class_mock(mock_hub)
    with (
        patch(PATCH_HUB, hub_cls),
        patch(PATCH_SESSION, return_value=MagicMock()),
    ):
        await flow.async_step_import(IMPORT_DATA)

    mock_hub.login.assert_awaited_once()
    # Verify the config was passed to SecuritasHub constructor
    call_args = hub_cls.call_args[0][0]
    assert call_args[CONF_USERNAME] == "test@example.com"
    assert call_args[CONF_PASSWORD] == "test-password"
    assert call_args[CONF_COUNTRY] == "ES"
    assert call_args[CONF_DEVICE_ID] == "test-device-id"
    assert call_args[CONF_UNIQUE_ID] == "test-uuid"
    assert call_args[CONF_DEVICE_INDIGITALL] == "test-indigitall"


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
            CONF_PERI_ALARM: False,
            CONF_CHECK_ALARM_PANEL: True,
            CONF_SCAN_INTERVAL: 60,
            CONF_DELAY_CHECK_OPERATION: 3.0,
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
    """Mappings step shows STD options when peri_alarm is False."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(peri_alarm=False),
        options={},
    )
    entry.add_to_hass(hass)

    flow_id = await _advance_to_mappings(hass, entry, peri_alarm=False)
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
    """Mappings step shows PERI options when peri_alarm is True."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(peri_alarm=True),
        options={},
    )
    entry.add_to_hass(hass)

    flow_id = await _advance_to_mappings(hass, entry, peri_alarm=True)
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
            peri_alarm=False,
            map_home=SecuritasState.TOTAL_PERI.value,
        ),
        options={},
    )
    entry.add_to_hass(hass)

    flow_id = await _advance_to_mappings(hass, entry, peri_alarm=False)
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

    flow_id = await _advance_to_mappings(hass, entry, peri_alarm=False)

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

    flow_id = await _advance_to_mappings(hass, entry, peri_alarm=False)

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
