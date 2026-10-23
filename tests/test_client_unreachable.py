"""Tests for the client's "can't reach Verisure" tracking."""

import os
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.securitas.verisure_owa_api.client import (
    VerisureOwaClient,
    _base,
)
from custom_components.securitas.verisure_owa_api.exceptions import (
    APIConnectionError,
    VerisureOwaError,
)

from .conftest import FAKE_JWT, refresh_token_rejected_response

STATUS_POLL = {"operationName": "CheckAlarmStatus", "variables": {}, "query": ""}
OK_REPLY = {"data": {"xSCheckAlarmStatus": {"res": "OK"}}}


class _Clock:
    def __init__(self) -> None:
        self.utc = datetime(2026, 10, 16, 14, 44, tzinfo=UTC)

    @property
    def now(self) -> datetime:
        return self.utc.astimezone().replace(tzinfo=None)

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
            return fake.now if tz is None else fake.utc.astimezone(tz)

    monkeypatch.setattr(_base, "datetime", _FakeDatetime)
    yield fake
    if saved_tz is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved_tz
    time.tzset()


def _client(mock_transport, alerts: list[bool] | None = None, **kwargs):
    callback = None if alerts is None else alerts.append
    client = VerisureOwaClient(
        transport=mock_transport,
        country="PT",
        language="pt",
        username="test@example.com",
        password=kwargs.pop("password", ""),
        device_id="test-device-id",
        uuid="test-uuid",
        id_device_indigitall="test-indigitall",
        refresh_token="has-refresh-token",
        on_unreachable_alert=kwargs.pop("on_unreachable_alert", callback),
        **kwargs,
    )
    client.authentication_token = FAKE_JWT
    client.authentication_token_exp = datetime.max
    return client


def _null_data_reply(err: str, name: str = "ApiError") -> dict:
    return {
        "errors": [
            {
                "message": "something went wrong",
                "name": name,
                "data": {"err": err},
                "path": ["xSCheckAlarmStatus"],
            }
        ],
        "data": {"xSCheckAlarmStatus": None},
    }


async def _status_poll(client) -> Exception | None:
    try:
        await client._execute_raw(STATUS_POLL, "CheckAlarmStatus")
    except Exception as err:  # pylint: disable=broad-exception-caught
        return err
    return None


async def _fail_at(
    client, clock, alerts: list[bool], minutes: list[int]
) -> dict[int, list[bool]]:
    """Status polls at the given minutes from now; the alerts seen after each."""
    start = clock.utc
    seen: dict[int, list[bool]] = {}
    for minute in minutes:
        clock.utc = start + timedelta(minutes=minute)
        await _status_poll(client)
        seen[minute] = list(alerts)
    return seen


def test_alert_after_is_one_hour():
    assert timedelta(hours=1) == _base.UNREACHABLE_ALERT_AFTER


async def test_alert_raised_once_after_an_hour_of_failures(
    mock_transport, clock, caplog
):
    alerts: list[bool] = []
    client = _client(mock_transport, alerts)
    mock_transport.execute.side_effect = APIConnectionError("down")

    with caplog.at_level("WARNING"):
        seen = await _fail_at(client, clock, alerts, [0, 30, 59, 60, 61])

    assert seen == {0: [], 30: [], 59: [], 60: [True], 61: [True]}
    assert client.unreachable_alert_raised is True
    assert caplog.text.count("No request to Verisure has worked") == 1


async def test_success_clears_the_alert(mock_transport, clock):
    alerts: list[bool] = []
    client = _client(mock_transport, alerts)
    mock_transport.execute.side_effect = APIConnectionError("down")
    await _fail_at(client, clock, alerts, [0, 60])
    assert alerts == [True]

    mock_transport.execute.side_effect = None
    mock_transport.execute.return_value = OK_REPLY
    assert await _status_poll(client) is None

    assert alerts == [True, False]
    assert client.unreachable_alert_raised is False


async def test_success_without_an_alert_does_not_call_back(mock_transport, clock):
    alerts: list[bool] = []
    client = _client(mock_transport, alerts)
    mock_transport.execute.return_value = OK_REPLY

    await _status_poll(client)

    assert alerts == []


async def test_success_before_an_hour_restarts_the_clock(mock_transport, clock):
    alerts: list[bool] = []
    client = _client(mock_transport, alerts)
    start = clock.utc
    for minute, outcome in [(0, "fail"), (50, "ok"), (55, "fail"), (100, "fail")]:
        clock.utc = start + timedelta(minutes=minute)
        if outcome == "fail":
            mock_transport.execute.side_effect = APIConnectionError("down")
        else:
            mock_transport.execute.side_effect = None
            mock_transport.execute.return_value = OK_REPLY
        await _status_poll(client)

    assert alerts == []
    assert client.unreachable_alert_raised is False


async def test_transport_timeout_counts_as_a_failure(mock_transport, clock):
    alerts: list[bool] = []
    client = _client(mock_transport, alerts)
    mock_transport.execute.side_effect = TimeoutError()

    seen = await _fail_at(client, clock, alerts, [0, 60])

    assert seen[60] == [True]


async def test_refused_renewal_reply_counts_as_a_failure(mock_transport, clock):
    alerts: list[bool] = []
    client = _client(mock_transport, alerts)
    mock_transport.execute.side_effect = lambda *a, **kw: (
        refresh_token_rejected_response()
    )
    start = clock.utc
    alerted_at: list[int] = []

    for minute in range(61):
        clock.utc = start + timedelta(minutes=minute)
        client.authentication_token_exp = datetime.min
        with pytest.raises(VerisureOwaError):
            await client._check_authentication_token()
        if alerts and not alerted_at:
            alerted_at.append(minute)

    assert alerted_at == [60]
    assert alerts == [True]


async def test_verisure_timeout_reply_on_a_status_poll_counts_as_a_failure(
    mock_transport, clock
):
    alerts: list[bool] = []
    client = _client(mock_transport, alerts)
    mock_transport.execute.return_value = _null_data_reply(
        "TimeoutError", name="TimeoutError"
    )

    seen = await _fail_at(client, clock, alerts, [0, 59, 60])

    assert seen == {0: [], 59: [], 60: [True]}


async def test_genuine_rejection_reply_is_not_a_failure(mock_transport, clock):
    alerts: list[bool] = []
    client = _client(mock_transport, alerts)
    mock_transport.execute.return_value = _null_data_reply("60067")

    seen = await _fail_at(client, clock, alerts, [0, 60, 120])

    assert seen == {0: [], 60: [], 120: []}
    assert client._unreachable_since is None


async def test_error_reply_with_some_data_is_not_a_failure(mock_transport, clock):
    alerts: list[bool] = []
    client = _client(mock_transport, alerts)
    reply = _null_data_reply("500")
    reply["data"]["xSOther"] = {"res": "OK"}
    mock_transport.execute.return_value = reply

    await _fail_at(client, clock, alerts, [0, 60])

    assert client._unreachable_since is None


async def test_error_reply_with_null_data_is_a_failure(mock_transport, clock):
    client = _client(mock_transport, [])
    reply = _null_data_reply("500")
    reply["data"] = None
    mock_transport.execute.return_value = reply

    await _status_poll(client)

    assert client._unreachable_since == clock.utc


async def test_pacing_error_is_not_a_failure(mock_transport, clock):
    alerts: list[bool] = []
    client = _client(mock_transport, alerts)
    client.authentication_token_exp = datetime.min
    client._refusals_persisting = True
    client._last_renewal_attempt = clock.utc

    with pytest.raises(VerisureOwaError, match="still refusing"):
        await client._check_authentication_token()

    mock_transport.execute.assert_not_called()
    assert client._unreachable_since is None


async def test_failing_callback_does_not_break_requests(mock_transport, clock):
    callback = MagicMock(side_effect=RuntimeError("host broke"))
    client = _client(mock_transport, on_unreachable_alert=callback)
    down = APIConnectionError("down")
    mock_transport.execute.side_effect = down

    assert await _status_poll(client) is down
    clock.advance(minutes=60)
    assert await _status_poll(client) is down
    assert client.unreachable_alert_raised is True

    mock_transport.execute.side_effect = None
    mock_transport.execute.return_value = OK_REPLY
    assert await _status_poll(client) is None
    assert client.unreachable_alert_raised is False
