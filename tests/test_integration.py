"""Integration tests for the Securitas Direct HA integration.

These tests exercise the full stack — from HA config-entry setup through to
entities in the state machine — using a MockGraphQLServer that intercepts
aiohttp POST calls at the HTTP transport level.  The real _execute_request()
runs (header construction, JSON parsing, error handling), unlike the unit tests
which patch _execute_request directly.
"""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from custom_components.securitas import DOMAIN, async_setup_entry, async_unload_entry
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
)

from .conftest import make_config_entry_data
from .mock_graphql import (
    FAKE_JWT,
    MockGraphQLServer,
    graphql_alarm_status,
    graphql_arm,
    graphql_arm_status,
    graphql_check_alarm,
    graphql_disarm,
    graphql_disarm_status,
    graphql_installations,
    graphql_login,
    graphql_login_error,
    graphql_services,
    graphql_sentinel,
    make_doorlock_service,
    make_jwt,
    make_sentinel_service,
    queue_standard_setup,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_entry(hass: HomeAssistant, **overrides) -> MockConfigEntry:
    """Create and register a MockConfigEntry with delay_check_operation=0."""
    data = make_config_entry_data(delay_check_operation=0, **overrides)
    entry = MockConfigEntry(domain=DOMAIN, data=data, unique_id="test-entry")
    entry.add_to_hass(hass)
    return entry


async def _setup(
    hass: HomeAssistant, server: MockGraphQLServer
) -> tuple[MockConfigEntry, bool]:
    """Create an entry and run full async_setup_entry with the mock server."""
    entry = _make_entry(hass)
    mock_http = server.make_http_client()
    with patch(
        "custom_components.securitas.async_get_clientsession",
        return_value=mock_http,
    ):
        with patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        ) as mock_fwd:
            mock_fwd.return_value = True
            result = await async_setup_entry(hass, entry)
    return entry, result


# ── Setup & entity creation ───────────────────────────────────────────────────


async def test_setup_returns_true(hass: HomeAssistant, mock_server: MockGraphQLServer):
    """async_setup_entry returns True on success."""
    queue_standard_setup(mock_server)
    _, result = await _setup(hass, mock_server)
    assert result is True


async def test_setup_calls_login(hass: HomeAssistant, mock_server: MockGraphQLServer):
    """Setup calls mkLoginToken exactly once."""
    queue_standard_setup(mock_server)
    await _setup(hass, mock_server)
    assert mock_server.call_count("mkLoginToken") == 1


async def test_setup_calls_list_installations(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Setup calls mkInstallationList to discover installations."""
    queue_standard_setup(mock_server)
    await _setup(hass, mock_server)
    assert mock_server.call_count("mkInstallationList") == 1


async def test_setup_makes_only_expected_api_calls(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Setup phase must only call login, list_installations, and get_all_services.

    This is a guardrail: if a new API call is added to async_setup_entry or
    synchronous platform setup, this test will fail — forcing the developer to
    either move the call to the background discovery task or explicitly update
    the allowed list.

    The AlarmCoordinator fires a background refresh (Status) immediately after
    setup via async_create_background_task.  This may or may not have executed
    by the time we inspect the call log, so Status is allowed but not required.
    """
    queue_standard_setup(mock_server)

    # Run setup but capture calls before background tasks execute.
    entry = _make_entry(hass)
    mock_http = mock_server.make_http_client()
    with (
        patch(
            "custom_components.securitas.async_get_clientsession",
            return_value=mock_http,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
        ) as mock_fwd,
        patch(
            "custom_components.securitas._async_discover_devices",
        ),
    ):
        mock_fwd.return_value = True
        await async_setup_entry(hass, entry)

    operations = [op for op, _, _ in mock_server.calls]
    # The first three calls are the synchronous setup path.
    # "Status" / "ActV2Timeline" may appear if the AlarmCoordinator /
    # ActivityCoordinator background refreshes have fired.
    required = ["mkLoginToken", "mkInstallationList", "Srv"]
    background_allowed = {"Status", "ActV2Timeline"}
    assert operations[:3] == required, (
        f"Unexpected API calls during setup: {operations}. "
        "New calls should run in _async_discover_devices, not during setup."
    )
    extra = set(operations[3:]) - background_allowed
    assert not extra, (
        f"Unexpected extra API calls during setup: {extra}. "
        "New calls should run in _async_discover_devices, not during setup."
    )


async def test_login_sets_auth_token(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """After login, SecuritasClient.authentication_token is set from the JWT."""
    queue_standard_setup(mock_server, proto="D")
    entry, _ = await _setup(hass, mock_server)

    hub = hass.data[DOMAIN][entry.entry_id]["hub"]
    assert hub.client.authentication_token == FAKE_JWT


async def test_login_token_stored(hass: HomeAssistant, mock_server: MockGraphQLServer):
    """setup_entry stores the hub in per-entry data."""
    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    assert entry.entry_id in hass.data[DOMAIN]
    assert "hub" in hass.data[DOMAIN][entry.entry_id]


async def test_installations_stored(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Discovered installations are stored in per-entry data."""
    queue_standard_setup(mock_server, numinst="999")
    entry, _ = await _setup(hass, mock_server)

    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    assert devices is not None
    assert len(devices) == 1
    assert devices[0].installation.number == "999"


async def test_multiple_installations_stored(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Multiple installations all become devices."""
    caps = make_jwt(exp_minutes=60)
    mock_server.add_response("mkLoginToken", graphql_login())
    mock_server.add_response(
        "mkInstallationList",
        graphql_installations(
            installations=[
                {
                    "numinst": "111",
                    "alias": "Home",
                    "panel": "SDVFAST",
                    "type": "PLUS",
                    "name": "A",
                    "surname": "B",
                    "address": "1 St",
                    "city": "Madrid",
                    "postcode": "28001",
                    "province": "Madrid",
                    "email": "a@b.com",
                    "phone": "1",
                },
                {
                    "numinst": "222",
                    "alias": "Office",
                    "panel": "SDVFAST",
                    "type": "PLUS",
                    "name": "C",
                    "surname": "D",
                    "address": "2 St",
                    "city": "Barcelona",
                    "postcode": "08001",
                    "province": "Barcelona",
                    "email": "c@d.com",
                    "phone": "2",
                },
            ]
        ),
    )
    srv = graphql_services(capabilities_jwt=caps, numinst="111")
    srv2 = graphql_services(capabilities_jwt=caps, numinst="222")
    mock_server.add_response("Srv", srv)
    mock_server.add_response("Srv", srv2)
    mock_server.set_default_response("Srv", srv)
    mock_server.add_response("CheckAlarm", graphql_check_alarm())
    mock_server.add_response("CheckAlarm", graphql_check_alarm())
    mock_server.add_response("CheckAlarmStatus", graphql_alarm_status(numinst="111"))
    mock_server.add_response("CheckAlarmStatus", graphql_alarm_status(numinst="222"))
    mock_server.set_default_response("CheckAlarmStatus", graphql_alarm_status())

    entry, result = await _setup(hass, mock_server)
    assert result is True
    devices = hass.data[DOMAIN][entry.entry_id]["devices"]
    assert len(devices) == 2


# ── Header & request verification ────────────────────────────────────────────


async def test_login_sends_auth_header(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """mkLoginToken request must NOT include auth header (no token yet)."""
    queue_standard_setup(mock_server)
    await _setup(hass, mock_server)

    _, headers, _ = mock_server.get_calls("mkLoginToken")[0]
    # At login time there is no token, so auth header should be absent or empty hash
    if "auth" in headers:
        import json as _json

        auth = _json.loads(headers["auth"])
        assert auth.get("hash", "") == ""


async def test_installation_scoped_requests_carry_numinst(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Requests scoped to an installation include numinst/panel headers."""
    queue_standard_setup(mock_server, numinst="123456", panel="SDVFAST")
    entry, _ = await _setup(hass, mock_server)

    entry_data = hass.data[DOMAIN][entry.entry_id]
    hub = entry_data["hub"]
    devices = entry_data["devices"]

    # Trigger a scoped call by calling check_alarm directly
    await hub.client.check_alarm(devices[0].installation)

    calls = mock_server.get_calls("CheckAlarm")
    assert calls, "CheckAlarm was never called"
    _, headers, _ = calls[0]
    assert headers.get("numinst") == "123456"
    assert headers.get("panel") == "SDVFAST"


async def test_check_alarm_sends_operation_name(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """X-APOLLO-OPERATION-NAME header must be set for every request."""
    queue_standard_setup(mock_server)
    await _setup(hass, mock_server)

    for operation, headers, _ in mock_server.calls:
        assert headers.get("X-APOLLO-OPERATION-NAME") == operation


# ── Error handling during setup ───────────────────────────────────────────────


async def test_setup_login_error_raises_auth_failed(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """AuthenticationError during setup raises ConfigEntryAuthFailed."""
    mock_server.add_response("mkLoginToken", graphql_login_error("Invalid credentials"))

    entry = _make_entry(hass)
    mock_http = mock_server.make_http_client()
    with (
        patch(
            "custom_components.securitas.async_get_clientsession",
            return_value=mock_http,
        ),
        patch.object(hass, "async_create_task"),
        pytest.raises(ConfigEntryAuthFailed, match="Authentication failed"),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_2fa_error_raises_auth_failed(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """TwoFactorRequiredError during setup raises ConfigEntryAuthFailed."""
    # Response that sets needDeviceAuthorization=True triggers TwoFactorRequiredError
    mock_server.add_response(
        "mkLoginToken",
        {
            "data": {
                "xSLoginToken": {
                    "__typename": "LoginToken",
                    "res": "OK",
                    "msg": "",
                    "hash": FAKE_JWT,
                    "refreshToken": "token",
                    "legals": None,
                    "changePassword": False,
                    "needDeviceAuthorization": True,
                    "mainUser": True,
                }
            }
        },
    )
    entry = _make_entry(hass)
    mock_http = mock_server.make_http_client()
    with (
        patch(
            "custom_components.securitas.async_get_clientsession",
            return_value=mock_http,
        ),
        patch.object(hass, "async_create_task"),
        pytest.raises(ConfigEntryAuthFailed, match="2FA required"),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_connection_error_raises_not_ready(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Network error during setup raises ConfigEntryNotReady."""
    from aiohttp import ClientConnectorError
    from aiohttp.client_reqrep import ConnectionKey

    entry = _make_entry(hass)

    # Use a proper ClientConnectorError-raising mock
    _conn_key = ConnectionKey("example.com", 443, False, True, None, None, None)

    class _FailPost:
        def post(self, url, **kwargs):
            raise ClientConnectorError(_conn_key, OSError("connection refused"))

    with patch(
        "custom_components.securitas.async_get_clientsession",
        return_value=_FailPost(),
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)


# ── Services create correct entities ─────────────────────────────────────────


async def test_services_with_doorlock(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """When a DOORLOCK service exists, get_services returns it."""
    doorlock = make_doorlock_service()
    queue_standard_setup(mock_server, extra_services=[doorlock])
    entry, result = await _setup(hass, mock_server)
    assert result is True

    entry_data = hass.data[DOMAIN][entry.entry_id]
    hub = entry_data["hub"]
    devices = entry_data["devices"]
    services = await hub.get_services(devices[0].installation)
    doorlock_services = [s for s in services if s.request == "DOORLOCK"]
    assert len(doorlock_services) == 1


async def test_services_without_doorlock(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Without a DOORLOCK service, no lock services are returned."""
    queue_standard_setup(mock_server, extra_services=[])
    entry, result = await _setup(hass, mock_server)
    assert result is True

    entry_data = hass.data[DOMAIN][entry.entry_id]
    hub = entry_data["hub"]
    devices = entry_data["devices"]
    services = await hub.get_services(devices[0].installation)
    assert all(s.request != "DOORLOCK" for s in services)


async def test_services_with_sentinel(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """When a CONFORT service exists, get_services returns it."""
    sentinel = make_sentinel_service(zone="1")
    queue_standard_setup(mock_server, extra_services=[sentinel])
    entry, result = await _setup(hass, mock_server)
    assert result is True

    entry_data = hass.data[DOMAIN][entry.entry_id]
    hub = entry_data["hub"]
    devices = entry_data["devices"]
    services = await hub.get_services(devices[0].installation)
    sentinel_services = [s for s in services if s.request == "CONFORT"]
    assert len(sentinel_services) == 1


# ── Arm / Disarm via SecuritasClient ───────────────────────────────────────────────


async def test_arm_away_api_call(hass: HomeAssistant, mock_server: MockGraphQLServer):
    """arm_alarm() sends xSArmPanel and polls ArmStatus until non-WAIT."""
    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    entry_data = hass.data[DOMAIN][entry.entry_id]
    hub = entry_data["hub"]
    devices = entry_data["devices"]
    installation = devices[0].installation

    # Queue arm sequence: submit + poll
    mock_server.add_response("xSArmPanel", graphql_arm())
    mock_server.add_response("ArmStatus", graphql_arm_status(proto="T"))

    status = await hub.arm_alarm(installation, "ARM1")
    assert status.protom_response == "T"
    assert mock_server.call_count("xSArmPanel") == 1
    assert mock_server.call_count("ArmStatus") >= 1


async def test_disarm_api_call(hass: HomeAssistant, mock_server: MockGraphQLServer):
    """disarm_alarm() sends xSDisarmPanel and polls DisarmStatus."""
    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    entry_data = hass.data[DOMAIN][entry.entry_id]
    hub = entry_data["hub"]
    devices = entry_data["devices"]
    installation = devices[0].installation

    # Queue disarm sequence: submit + poll
    mock_server.add_response("xSDisarmPanel", graphql_disarm())
    mock_server.add_response("DisarmStatus", graphql_disarm_status(proto="D"))

    status = await hub.disarm_alarm(installation, "DARM1")
    assert status.protom_response == "D"
    assert mock_server.call_count("xSDisarmPanel") == 1


async def test_arm_poll_waits_for_ok(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """ArmStatus WAIT responses are retried until a non-WAIT result arrives."""
    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    entry_data = hass.data[DOMAIN][entry.entry_id]
    hub = entry_data["hub"]
    devices = entry_data["devices"]
    installation = devices[0].installation

    # Queue arm sequence: submit + 3 polls (2 WAIT, then OK)
    mock_server.add_response("xSArmPanel", graphql_arm())
    mock_server.add_response("ArmStatus", graphql_arm_status(res="WAIT", proto=""))
    mock_server.add_response("ArmStatus", graphql_arm_status(res="WAIT", proto=""))
    mock_server.add_response("ArmStatus", graphql_arm_status(res="OK", proto="T"))

    status = await hub.arm_alarm(installation, "ARM1")
    assert status.protom_response == "T"
    assert mock_server.call_count("ArmStatus") == 3


# ── Sentinel data ─────────────────────────────────────────────────────────────


async def test_sentinel_data_returned(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """get_sentinel_data() parses temperature and humidity."""
    sentinel_svc = make_sentinel_service(zone="1")
    queue_standard_setup(mock_server, extra_services=[sentinel_svc])
    entry, _ = await _setup(hass, mock_server)

    entry_data = hass.data[DOMAIN][entry.entry_id]
    hub = entry_data["hub"]
    devices = entry_data["devices"]
    installation = devices[0].installation
    services = await hub.get_services(installation)
    svc = next(s for s in services if s.request == "CONFORT")

    mock_server.add_response("Srv", graphql_services(capabilities_jwt=make_jwt(60)))
    mock_server.add_response("CheckAlarm", graphql_check_alarm())
    mock_server.add_response("CheckAlarmStatus", graphql_alarm_status())
    mock_server.add_response(
        "Sentinel", graphql_sentinel(temperature=23, humidity=60, zone="1")
    )

    sentinel = await hub.client.get_sentinel_data(installation, svc)
    assert sentinel.temperature == 23
    assert sentinel.humidity == 60


# ── Unload ────────────────────────────────────────────────────────────────────


async def test_unload_cleans_hass_data(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """async_unload_entry removes the entry from hass.data[DOMAIN]."""
    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    assert entry.entry_id in hass.data[DOMAIN]

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=True,
    ):
        ok = await async_unload_entry(hass, entry)

    assert ok is True
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_unload_removes_entry_id(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """async_unload_entry removes the entry_id from hass.data[DOMAIN]."""
    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    assert entry.entry_id in hass.data[DOMAIN]

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=True,
    ):
        ok = await async_unload_entry(hass, entry)

    assert ok is True
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


# ── JSON error handling ───────────────────────────────────────────────────────


async def test_graphql_error_response_raises(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """A GraphQL errors:{data:{reason:...}} response raises SecuritasDirectError."""
    from .mock_graphql import graphql_error

    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    entry_data = hass.data[DOMAIN][entry.entry_id]
    hub = entry_data["hub"]
    devices = entry_data["devices"]
    installation = devices[0].installation

    # Queue an error for the next CheckAlarm call (overrides the default)
    mock_server.add_response("CheckAlarm", graphql_error("Some API error"))

    with pytest.raises(SecuritasDirectError):
        await hub.client.check_alarm(installation)


async def test_malformed_json_raises(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Malformed JSON response raises SecuritasDirectError."""
    from tests.mock_graphql import MockContextManager, MockResponse

    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    entry_data = hass.data[DOMAIN][entry.entry_id]
    hub = entry_data["hub"]
    devices = entry_data["devices"]
    installation = devices[0].installation

    # Patch transport session.post to return invalid JSON
    bad_response = MockContextManager(MockResponse("not-valid-json"))
    hub.client._transport._session.post = lambda *a, **kw: bad_response

    with pytest.raises(SecuritasDirectError):
        await hub.client.check_alarm(installation)
