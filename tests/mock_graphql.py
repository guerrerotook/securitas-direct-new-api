"""Mock GraphQL server for Securitas Direct integration tests.

Intercepts aiohttp POST calls at the HTTP transport level so that
_execute_request() runs fully — header construction, JSON parsing,
error handling — while returning canned responses.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt


# ── JWT helper ────────────────────────────────────────────────────────────────

_JWT_SECRET = "test-secret"


def make_jwt(exp_minutes: int = 60, **extra_claims) -> str:
    """Create a real HS256 JWT with a known expiry."""
    exp = datetime.now(tz=timezone.utc) + timedelta(minutes=exp_minutes)
    payload = {"exp": exp, "sub": "test-user", **extra_claims}
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


# Module-level constants reused by both the server and tests
FAKE_JWT = make_jwt(exp_minutes=60)
FAKE_REFRESH_TOKEN = make_jwt(exp_minutes=180 * 24 * 60)
FAKE_CAPABILITIES_JWT = make_jwt(exp_minutes=60)


# ── Mock HTTP plumbing ────────────────────────────────────────────────────────


class MockResponse:
    """Fake aiohttp response."""

    def __init__(self, text: str, status: int = 200) -> None:
        self._text = text
        self.status = status

    async def text(self) -> str:
        return self._text


class MockContextManager:
    """Async context manager wrapping MockResponse."""

    def __init__(self, response: MockResponse) -> None:
        self.response = response

    async def __aenter__(self) -> MockResponse:
        return self.response

    async def __aexit__(self, *args) -> None:
        pass


# ── Mock GraphQL server ───────────────────────────────────────────────────────


class MockGraphQLServer:
    """Intercepts aiohttp POST calls and dispatches by X-APOLLO-OPERATION-NAME.

    Usage::

        server = MockGraphQLServer()
        server.add_response("mkLoginToken", graphql_login())
        server.add_response("mkInstallationList", graphql_installations())
        # …queue more responses…

        mock_http = MagicMock()
        mock_http.post = server.post

        with patch("custom_components.securitas.async_get_clientsession",
                   return_value=mock_http):
            await hass.config_entries.async_setup(entry.entry_id)

        assert server.call_count("mkLoginToken") == 1
    """

    def __init__(self) -> None:
        self.responses: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, dict, dict]] = []
        self._default_responses: dict[str, dict] = {}

    # ── Response queue management ────────────────────────────────────────────

    def add_response(self, operation: str, response: dict) -> None:
        """Queue a response for the given operation (consumed in FIFO order)."""
        self.responses.setdefault(operation, []).append(response)

    def set_default_response(self, operation: str, response: dict) -> None:
        """Set a response used when the queue for *operation* is empty."""
        self._default_responses[operation] = response

    def add_responses(self, responses: dict[str, list[dict]]) -> None:
        """Bulk-queue multiple operations at once."""
        for operation, items in responses.items():
            for item in items:
                self.add_response(operation, item)

    # ── HTTP interception ─────────────────────────────────────────────────────

    def post(self, url: str, **kwargs) -> MockContextManager:
        """Drop-in replacement for aiohttp.ClientSession.post."""
        headers: dict = kwargs.get("headers", {})
        json_body: dict = kwargs.get("json", {})
        operation: str = headers.get(
            "X-APOLLO-OPERATION-NAME",
            json_body.get("operationName", "unknown"),
        )

        self.calls.append((operation, dict(headers), json_body))

        queue = self.responses.get(operation, [])
        if queue:
            response_data = queue.pop(0)
        elif operation in self._default_responses:
            response_data = self._default_responses[operation]
        else:
            raise ValueError(
                f"MockGraphQLServer: no queued or default response for "
                f"operation '{operation}'. Queued: {list(self.responses.keys())}"
            )

        return MockContextManager(MockResponse(json.dumps(response_data)))

    # ── Introspection helpers ─────────────────────────────────────────────────

    def get_calls(self, operation: str) -> list[tuple[str, dict, dict]]:
        """Return all recorded calls for a specific operation."""
        return [(op, h, b) for op, h, b in self.calls if op == operation]

    def call_count(self, operation: str) -> int:
        """Return how many times *operation* was called."""
        return len(self.get_calls(operation))

    def last_call(self, operation: str) -> tuple[str, dict, dict] | None:
        """Return the most recent call for *operation*, or None."""
        calls = self.get_calls(operation)
        return calls[-1] if calls else None

    def reset(self) -> None:
        """Clear all recorded calls (but keep queued responses)."""
        self.calls.clear()

    def clear_queue(self, operation: str) -> None:
        """Discard any queued (unconsumed) responses for *operation*."""
        self.responses.pop(operation, None)

    def make_http_client(self) -> MagicMock:
        """Return a MagicMock ClientSession wired to this server."""
        mock = MagicMock()
        mock.post = self.post
        return mock


# ── Response factories ────────────────────────────────────────────────────────


def graphql_login(
    *,
    hash_token: str = FAKE_JWT,
    refresh_token: str = FAKE_REFRESH_TOKEN,
    need_2fa: bool = False,
    res: str = "OK",
) -> dict:
    """Successful mkLoginToken response."""
    return {
        "data": {
            "xSLoginToken": {
                "__typename": "LoginToken",
                "res": res,
                "msg": "",
                "hash": hash_token,
                "refreshToken": refresh_token,
                "legals": None,
                "changePassword": False,
                "needDeviceAuthorization": need_2fa,
                "mainUser": True,
            }
        }
    }


def graphql_login_2fa(
    *,
    hash_token: str = FAKE_JWT,
    refresh_token: str = FAKE_REFRESH_TOKEN,
) -> dict:
    """Login response that requires 2FA (needDeviceAuthorization=True)."""
    return graphql_login(
        hash_token=hash_token,
        refresh_token=refresh_token,
        need_2fa=True,
    )


def graphql_login_error(message: str = "Invalid credentials") -> dict:
    """Login response containing an error."""
    return {"errors": [{"message": message}]}


def graphql_installations(
    *,
    installations: list[dict] | None = None,
    numinst: str = "123456",
    alias: str = "Home",
    panel: str = "SDVFAST",
) -> dict:
    """mkInstallationList response with one installation by default."""
    if installations is None:
        installations = [
            {
                "numinst": numinst,
                "alias": alias,
                "panel": panel,
                "type": "PLUS",
                "name": "John",
                "surname": "Doe",
                "address": "123 Test St",
                "city": "Madrid",
                "postcode": "28001",
                "province": "Madrid",
                "email": "test@example.com",
                "phone": "555-1234",
            }
        ]
    return {"data": {"xSInstallations": {"installations": installations}}}


def _make_service_dict(
    *,
    id_service: int = 1,
    request: str = "ALARM",
    active: bool = True,
    description: str = "",
    attributes: list[dict] | None = None,
) -> dict:
    """Return a single service dict compatible with the Srv response."""
    return {
        "idService": id_service,
        "active": active,
        "visible": True,
        "bde": False,
        "isPremium": False,
        "codOper": False,
        "totalDevice": 0,
        "request": request,
        "minWrapperVersion": None,
        "unprotectActive": False,
        "unprotectDeviceStatus": False,
        "instDate": None,
        "genericConfig": {"total": 0, "attributes": []},
        "attributes": {"attributes": attributes if attributes is not None else []},
        "description": description,
    }


def graphql_services(
    *,
    capabilities_jwt: str | None = None,
    services: list[dict] | None = None,
    numinst: str = "123456",
    alias: str = "Home",
) -> dict:
    """Srv (get_all_services) response."""
    if capabilities_jwt is None:
        capabilities_jwt = make_jwt(exp_minutes=60)
    if services is None:
        services = []
    return {
        "data": {
            "xSSrv": {
                "res": "OK",
                "msg": "",
                "language": "es",
                "installation": {
                    "numinst": numinst,
                    "role": "OWNER",
                    "alias": alias,
                    "status": "ACTIVE",
                    "panel": "SDVFAST",
                    "sim": "",
                    "instIbs": False,
                    "services": services,
                    "configRepoUser": {"alarmPartitions": []},
                    "capabilities": capabilities_jwt,
                },
            }
        }
    }


def graphql_check_alarm(*, reference_id: str = "ref-check-123") -> dict:
    """CheckAlarm response."""
    return {
        "data": {
            "xSCheckAlarm": {
                "res": "OK",
                "msg": "",
                "referenceId": reference_id,
            }
        }
    }


def graphql_alarm_status(
    *,
    proto: str = "D",
    numinst: str = "123456",
    res: str = "OK",
) -> dict:
    """CheckAlarmStatus response."""
    return {
        "data": {
            "xSCheckAlarmStatus": {
                "res": res,
                "msg": "",
                "status": "",
                "numinst": numinst,
                "protomResponse": proto,
                "protomResponseDate": "2024-01-01 12:00:00",
            }
        }
    }


def graphql_general_status(
    *,
    status: str = "D",
    timestamp: str = "2024-01-01 12:00:00",
) -> dict:
    """Status (check_general_status) response."""
    return {
        "data": {
            "xSStatus": {
                "status": status,
                "timestampUpdate": timestamp,
            }
        }
    }


def graphql_arm(*, reference_id: str = "ref-arm-123") -> dict:
    """xSArmPanel response."""
    return {
        "data": {
            "xSArmPanel": {
                "res": "OK",
                "msg": "",
                "referenceId": reference_id,
            }
        }
    }


def graphql_arm_status(
    *,
    proto: str = "T",
    numinst: str = "123456",
    res: str = "OK",
) -> dict:
    """ArmStatus polling response."""
    return {
        "data": {
            "xSArmStatus": {
                "res": res,
                "msg": "",
                "status": "",
                "protomResponse": proto,
                "protomResponseDate": "2024-01-01 12:00:00",
                "numinst": numinst,
                "requestId": "req-arm-123",
                "error": "",
            }
        }
    }


def graphql_disarm(*, reference_id: str = "ref-disarm-123") -> dict:
    """xSDisarmPanel response."""
    return {
        "data": {
            "xSDisarmPanel": {
                "res": "OK",
                "msg": "",
                "referenceId": reference_id,
            }
        }
    }


def graphql_disarm_status(
    *,
    proto: str = "D",
    numinst: str = "123456",
    res: str = "OK",
) -> dict:
    """DisarmStatus polling response."""
    return {
        "data": {
            "xSDisarmStatus": {
                "res": res,
                "msg": "",
                "status": "",
                "protomResponse": proto,
                "protomResponseDate": "2024-01-01 12:00:00",
                "numinst": numinst,
                "requestId": "req-disarm-123",
                "error": None,
            }
        }
    }


def graphql_sentinel(
    *,
    alias: str = "Sentinel1",
    temperature: int = 22,
    humidity: int = 55,
    zone: str = "1",
) -> dict:
    """Sentinel (get_sentinel_data) response."""
    return {
        "data": {
            "xSComfort": {
                "res": "OK",
                "devices": [
                    {
                        "alias": alias,
                        "status": {
                            "temperature": temperature,
                            "humidity": humidity,
                            "airQualityCode": "GOOD",
                        },
                        "zone": zone,
                    }
                ],
                "forecast": None,
            }
        }
    }


def graphql_air_quality(
    *,
    current: int = 42,
    message: str = "Good",
) -> dict:
    """AirQualityGraph response."""
    return {
        "data": {
            "xSAirQ": {
                "res": "OK",
                "msg": "",
                "graphData": {
                    "status": {
                        "current": current,
                        "currentMsg": message,
                        "avg6h": 40,
                        "avg6hMsg": "Good",
                        "avg24h": 38,
                        "avg24hMsg": "Good",
                        "avg7d": 35,
                        "avg7dMsg": "Good",
                        "avg4w": 33,
                        "avg4wMsg": "Good",
                    },
                    "daysTotal": 7,
                    "days": [],
                    "hoursTotal": 24,
                    "hours": [],
                    "weeksTotal": 4,
                    "weeks": [],
                },
            }
        }
    }


def graphql_lock_current_mode(*, lock_status: str = "2") -> dict:
    """xSGetLockCurrentMode response."""
    return {
        "data": {
            "xSGetLockCurrentMode": {
                "res": "OK",
                "smartlockInfo": [{"lockStatus": lock_status, "deviceId": "01"}],
            }
        }
    }


def graphql_change_lock_mode(*, reference_id: str = "ref-lock-123") -> dict:
    """xSChangeSmartlockMode response."""
    return {
        "data": {
            "xSChangeSmartlockMode": {
                "res": "OK",
                "msg": "",
                "referenceId": reference_id,
            }
        }
    }


def graphql_change_lock_mode_status(
    *,
    res: str = "OK",
    proto: str = "D",
) -> dict:
    """xSChangeSmartlockModeStatus polling response."""
    return {
        "data": {
            "xSChangeSmartlockModeStatus": {
                "res": res,
                "msg": "",
                "protomResponse": proto,
                "status": "",
            }
        }
    }


def graphql_logout() -> dict:
    """Logout response."""
    return {"data": {"xSLogout": True}}


def graphql_error(reason: str = "Unexpected error") -> dict:
    """Generic GraphQL error response (triggers SecuritasDirectError)."""
    return {"errors": {"data": {"reason": reason}}}


# ── Convenience: standard setup sequence ─────────────────────────────────────


def queue_standard_setup(
    server: MockGraphQLServer,
    *,
    proto: str = "D",
    numinst: str = "123456",
    alias: str = "Home",
    panel: str = "SDVFAST",
    extra_services: list[dict] | None = None,
) -> None:
    """Queue the minimal response sequence needed to bring up a single installation.

    Order: login → list_installations → services → check_alarm → alarm_status.
    Also sets persistent defaults for Srv and CheckAlarmStatus so repeated
    calls (e.g. during platform setup) always succeed.
    """
    capabilities_jwt = make_jwt(exp_minutes=60)
    services = extra_services or []

    server.add_response("mkLoginToken", graphql_login())
    server.add_response(
        "mkInstallationList",
        graphql_installations(numinst=numinst, alias=alias, panel=panel),
    )

    # Srv is called once during __init__.async_setup_entry, then again by
    # each platform (sensor.py, lock.py) — set a default so they all succeed.
    srv_response = graphql_services(
        capabilities_jwt=capabilities_jwt,
        services=services,
        numinst=numinst,
        alias=alias,
    )
    server.add_response("Srv", srv_response)
    server.set_default_response("Srv", srv_response)

    # Set defaults for CheckAlarm/CheckAlarmStatus so periodic refresh calls
    # (and manual test calls) succeed without explicit queueing.
    # NOTE: we do NOT add_response here — alarm_control_panel setup is patched
    # in _setup(), so queued entries would sit unused and shadow test-specific
    # responses added afterwards.
    server.set_default_response("CheckAlarm", graphql_check_alarm())
    server.set_default_response(
        "CheckAlarmStatus", graphql_alarm_status(proto=proto, numinst=numinst)
    )


def make_doorlock_service() -> dict:
    """Return a DOORLOCK service dict for use in graphql_services."""
    return _make_service_dict(
        id_service=10,
        request="DOORLOCK",
        description="Smart Lock",
    )


def make_sentinel_service(zone: str = "1") -> dict:
    """Return a CONFORT (sentinel) service dict for use in graphql_services."""
    return _make_service_dict(
        id_service=20,
        request="CONFORT",
        description="Sentinel",
        attributes=[{"name": "zone", "value": zone, "active": True}],
    )
