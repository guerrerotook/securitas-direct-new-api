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
from homeassistant.exceptions import ConfigEntryNotReady

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
    graphql_air_quality,
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


async def _setup(hass: HomeAssistant, server: MockGraphQLServer) -> MockConfigEntry:
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


async def test_setup_calls_get_services(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Setup calls Srv to get installation services."""
    queue_standard_setup(mock_server)
    await _setup(hass, mock_server)
    assert mock_server.call_count("Srv") >= 1


async def test_setup_check_alarm_via_update_overview(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """update_overview() triggers CheckAlarm when check_alarm_panel=True."""
    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]

    # update_overview drives the full check_alarm → check_alarm_status flow
    status = await hub.update_overview(devices[0].installation)
    assert mock_server.call_count("CheckAlarm") >= 1
    assert status.protomResponse is not None


async def test_login_sets_auth_token(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """After login, ApiManager.authentication_token is set from the JWT."""
    queue_standard_setup(mock_server, proto="D")
    entry, _ = await _setup(hass, mock_server)

    from custom_components.securitas import SecuritasHub

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    assert hub.session.authentication_token == FAKE_JWT


async def test_login_token_stored(hass: HomeAssistant, mock_server: MockGraphQLServer):
    """setup_entry stores the hub in hass.data[DOMAIN]."""
    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    from custom_components.securitas import SecuritasHub

    assert SecuritasHub.__name__ in hass.data[DOMAIN]


async def test_installations_stored(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Discovered installations are stored in hass.data[DOMAIN]."""
    from custom_components.securitas import CONF_INSTALLATION_KEY

    queue_standard_setup(mock_server, numinst="999")
    entry, _ = await _setup(hass, mock_server)

    devices = hass.data[DOMAIN].get(CONF_INSTALLATION_KEY)
    assert devices is not None
    assert len(devices) == 1
    assert devices[0].installation.number == "999"


async def test_multiple_installations_stored(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Multiple installations all become devices."""
    from custom_components.securitas import CONF_INSTALLATION_KEY

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
    devices = hass.data[DOMAIN].get(CONF_INSTALLATION_KEY)
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

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]

    # Trigger a scoped call by calling check_alarm directly
    await hub.session.check_alarm(devices[0].installation)

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


async def test_setup_login_error_returns_false(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """LoginError during setup causes async_setup_entry to return False."""
    mock_server.add_response("mkLoginToken", graphql_login_error("Invalid credentials"))

    entry = _make_entry(hass)
    mock_http = mock_server.make_http_client()
    with patch(
        "custom_components.securitas.async_get_clientsession",
        return_value=mock_http,
    ):
        # Suppress background flow.async_init that fails because 'securitas'
        # is not registered in the test HA loader
        with patch.object(hass, "async_create_task"):
            result = await async_setup_entry(hass, entry)

    assert result is False


async def test_setup_2fa_error_returns_false(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Login2FAError during setup causes async_setup_entry to return False."""
    # Response that sets needDeviceAuthorization=True triggers Login2FAError
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
    with patch(
        "custom_components.securitas.async_get_clientsession",
        return_value=mock_http,
    ):
        # Suppress background flow.async_init that fails in test loader
        with patch.object(hass, "async_create_task"):
            result = await async_setup_entry(hass, entry)
    assert result is False


async def test_setup_connection_error_raises_not_ready(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Network error during setup raises ConfigEntryNotReady."""
    from aiohttp import ClientConnectorError

    entry = _make_entry(hass)
    mock_http = mock_server.make_http_client()
    mock_http.post = None  # will cause AttributeError / TypeError

    # Use a proper ClientConnectorError-raising mock

    class _FailPost:
        def post(self, url, **kwargs):
            raise ClientConnectorError(None, OSError("connection refused"))

    with patch(
        "custom_components.securitas.async_get_clientsession",
        return_value=_FailPost(),
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)


# ── Alarm state from API response ─────────────────────────────────────────────


async def test_initial_state_disarmed(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Proto 'D' from CheckAlarmStatus → alarm state is disarmed."""
    queue_standard_setup(mock_server, proto="D")
    entry, _ = await _setup(hass, mock_server)

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
    assert len(devices) == 1

    # update_overview was called with proto D

    status = await hub.update_overview(devices[0].installation)
    assert status.protomResponse == "D"


async def test_initial_state_armed_away(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Proto 'T' from CheckAlarmStatus → total armed."""
    queue_standard_setup(mock_server, proto="T")
    _, result = await _setup(hass, mock_server)
    assert result is True

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]

    mock_server.add_response("CheckAlarm", graphql_check_alarm())
    mock_server.add_response("CheckAlarmStatus", graphql_alarm_status(proto="T"))
    status = await hub.update_overview(devices[0].installation)
    assert status.protomResponse == "T"


async def test_general_status_used_when_check_alarm_disabled(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """When check_alarm_panel=False, update_overview() uses Status, not CheckAlarm."""
    from .mock_graphql import graphql_general_status

    caps = make_jwt(exp_minutes=60)
    mock_server.add_response("mkLoginToken", graphql_login())
    mock_server.add_response("mkInstallationList", graphql_installations())
    srv = graphql_services(capabilities_jwt=caps)
    mock_server.add_response("Srv", srv)
    mock_server.set_default_response("Srv", srv)
    mock_server.set_default_response("Status", graphql_general_status(status="T"))

    entry = _make_entry(hass, check_alarm_panel=False)
    mock_http = mock_server.make_http_client()
    with patch(
        "custom_components.securitas.async_get_clientsession",
        return_value=mock_http,
    ):
        with patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            return_value=True,
        ):
            result = await async_setup_entry(hass, entry)

    assert result is True

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]

    # Directly call update_overview — with check_alarm=False it should use Status
    status = await hub.update_overview(devices[0].installation)
    assert mock_server.call_count("Status") >= 1
    assert mock_server.call_count("CheckAlarm") == 0
    assert status.protomResponse == "T"


# ── Services create correct entities ─────────────────────────────────────────


async def test_services_with_doorlock(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """When a DOORLOCK service exists, get_services returns it."""
    doorlock = make_doorlock_service()
    queue_standard_setup(mock_server, extra_services=[doorlock])
    entry, result = await _setup(hass, mock_server)
    assert result is True

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
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

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
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

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
    services = await hub.get_services(devices[0].installation)
    sentinel_services = [s for s in services if s.request == "CONFORT"]
    assert len(sentinel_services) == 1


# ── Arm / Disarm via ApiManager ───────────────────────────────────────────────


async def test_arm_away_api_call(hass: HomeAssistant, mock_server: MockGraphQLServer):
    """arm_alarm() sends xSArmPanel and polls ArmStatus until non-WAIT."""
    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
    installation = devices[0].installation

    # Queue arm sequence
    mock_server.add_response("Srv", graphql_services(capabilities_jwt=make_jwt(60)))
    mock_server.add_response("CheckAlarm", graphql_check_alarm())
    mock_server.add_response("CheckAlarmStatus", graphql_alarm_status(proto="T"))
    mock_server.add_response("xSArmPanel", graphql_arm())
    mock_server.add_response("ArmStatus", graphql_arm_status(proto="T"))

    status = await hub.session.arm_alarm(installation, "ARM1")
    assert status.protomResponse == "T"
    assert mock_server.call_count("xSArmPanel") == 1
    assert mock_server.call_count("ArmStatus") >= 1


async def test_disarm_api_call(hass: HomeAssistant, mock_server: MockGraphQLServer):
    """disarm_alarm() sends xSDisarmPanel and polls DisarmStatus."""
    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
    installation = devices[0].installation

    mock_server.add_response("Srv", graphql_services(capabilities_jwt=make_jwt(60)))
    mock_server.add_response("CheckAlarm", graphql_check_alarm())
    mock_server.add_response("CheckAlarmStatus", graphql_alarm_status(proto="D"))
    mock_server.add_response("xSDisarmPanel", graphql_disarm())
    mock_server.add_response("DisarmStatus", graphql_disarm_status(proto="D"))

    status = await hub.session.disarm_alarm(installation, "DARM1")
    assert status.protomResponse == "D"
    assert mock_server.call_count("xSDisarmPanel") == 1


async def test_arm_poll_waits_for_ok(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """ArmStatus WAIT responses are retried until a non-WAIT result arrives."""
    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
    installation = devices[0].installation

    mock_server.add_response("Srv", graphql_services(capabilities_jwt=make_jwt(60)))
    mock_server.add_response("CheckAlarm", graphql_check_alarm())
    mock_server.add_response("CheckAlarmStatus", graphql_alarm_status(proto="T"))
    mock_server.add_response("xSArmPanel", graphql_arm())
    # First two polls return WAIT, third returns OK
    mock_server.add_response("ArmStatus", graphql_arm_status(res="WAIT", proto=""))
    mock_server.add_response("ArmStatus", graphql_arm_status(res="WAIT", proto=""))
    mock_server.add_response("ArmStatus", graphql_arm_status(res="OK", proto="T"))

    status = await hub.session.arm_alarm(installation, "ARM1")
    assert status.protomResponse == "T"
    assert mock_server.call_count("ArmStatus") == 3


# ── Sentinel data ─────────────────────────────────────────────────────────────


async def test_sentinel_data_returned(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """get_sentinel_data() parses temperature and humidity."""
    sentinel_svc = make_sentinel_service(zone="1")
    queue_standard_setup(mock_server, extra_services=[sentinel_svc])
    entry, _ = await _setup(hass, mock_server)

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
    installation = devices[0].installation
    services = await hub.get_services(installation)
    svc = next(s for s in services if s.request == "CONFORT")

    mock_server.add_response("Srv", graphql_services(capabilities_jwt=make_jwt(60)))
    mock_server.add_response("CheckAlarm", graphql_check_alarm())
    mock_server.add_response("CheckAlarmStatus", graphql_alarm_status())
    mock_server.add_response(
        "Sentinel", graphql_sentinel(temperature=23, humidity=60, zone="1")
    )

    sentinel = await hub.session.get_sentinel_data(installation, svc)
    assert sentinel.temperature == 23
    assert sentinel.humidity == 60


async def test_air_quality_data_returned(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """get_air_quality_data() parses current AQI value."""
    sentinel_svc = make_sentinel_service(zone="1")
    queue_standard_setup(mock_server, extra_services=[sentinel_svc])
    entry, _ = await _setup(hass, mock_server)

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
    installation = devices[0].installation
    services = await hub.get_services(installation)
    svc = next(s for s in services if s.request == "CONFORT")

    mock_server.add_response("Srv", graphql_services(capabilities_jwt=make_jwt(60)))
    mock_server.add_response("CheckAlarm", graphql_check_alarm())
    mock_server.add_response("CheckAlarmStatus", graphql_alarm_status())
    mock_server.add_response(
        "AirQualityGraph", graphql_air_quality(current=75, message="Moderate")
    )

    aq = await hub.session.get_air_quality_data(installation, svc)
    assert aq.value == 75
    assert aq.message == "Moderate"


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

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
    installation = devices[0].installation

    # Queue an error for the next CheckAlarm call (overrides the default)
    mock_server.add_response("CheckAlarm", graphql_error("Some API error"))

    with pytest.raises(SecuritasDirectError):
        await hub.session.check_alarm(installation)


async def test_malformed_json_raises(
    hass: HomeAssistant, mock_server: MockGraphQLServer
):
    """Malformed JSON response raises SecuritasDirectError."""
    from tests.mock_graphql import MockContextManager, MockResponse

    queue_standard_setup(mock_server)
    entry, _ = await _setup(hass, mock_server)

    from custom_components.securitas import SecuritasHub, CONF_INSTALLATION_KEY

    hub = hass.data[DOMAIN][SecuritasHub.__name__]
    devices = hass.data[DOMAIN][CONF_INSTALLATION_KEY]
    installation = devices[0].installation

    # Patch http_client.post to return invalid JSON
    bad_response = MockContextManager(MockResponse("not-valid-json"))
    hub.session.http_client.post = lambda *a, **kw: bad_response

    with pytest.raises(SecuritasDirectError):
        await hub.session.check_alarm(installation)
