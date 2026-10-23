"""Tests for VerisureOwaClient authentication flow."""

import asyncio
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from pydantic import BaseModel

from custom_components.securitas.log_filter import SensitiveDataFilter
from custom_components.securitas.verisure_owa_api.client import (
    VerisureOwaClient,
    _base,
)
from custom_components.securitas.verisure_owa_api.exceptions import (
    AccountBlockedError,
    APIConnectionError,
    AuthenticationError,
    SessionExpiredError,
    TwoFactorRequiredError,
    VerisureOwaError,
    dead_refresh_token_signal,
    is_genuine_auth_failure,
)

from .conftest import (
    FAKE_JWT,
    FAKE_REFRESH_TOKEN,
    login_response,
    make_jwt,
    refresh_login_crash_error,
    refresh_response,
    refresh_token_rejected_err7_error,
    refresh_token_rejected_error,
    validate_device_response,
)

# ── login() ──────────────────────────────────────────────────────────────────


class TestLogin:
    async def test_stores_auth_token_and_expiry(self, api, mock_execute):
        mock_execute.return_value = login_response()

        await api.login()

        assert api.authentication_token == FAKE_JWT
        # Expiry should be ~15 min in the future (matching FAKE_JWT)
        assert api.authentication_token_exp > datetime.now()
        assert api.authentication_token_exp < datetime.now() + timedelta(minutes=20)

    async def test_stores_refresh_token(self, api, mock_execute):
        mock_execute.return_value = login_response()

        await api.login()

        assert api.refresh_token_value == FAKE_REFRESH_TOKEN

    async def test_sets_login_timestamp(self, api, mock_execute):
        mock_execute.return_value = login_response()
        before = int(datetime.now().timestamp() * 1000)

        await api.login()

        after = int(datetime.now().timestamp() * 1000)
        assert before <= api.login_timestamp <= after

    async def test_2fa_required_raises_two_factor_required_error(
        self, api, mock_execute
    ):
        mock_execute.return_value = login_response(need_2fa=True)

        with pytest.raises(TwoFactorRequiredError):
            await api.login()

    async def test_error_response_raises_authentication_error(self, api, mock_execute):
        mock_execute.return_value = {
            "errors": [{"message": "Invalid credentials"}],
        }

        with pytest.raises(AuthenticationError):
            await api.login()

    async def test_transport_error_raises_securitas_error(self, api, mock_execute):
        """Connection error (no response data) re-raises VerisureOwaError."""
        mock_execute.side_effect = VerisureOwaError("Connection failed")

        with pytest.raises(VerisureOwaError):
            await api.login()

    async def test_null_hash_sets_timestamp_for_2fa(self, api, mock_execute):
        mock_execute.return_value = login_response(hash_token=None)  # type: ignore[arg-type]

        await api.login()

        assert api.login_timestamp > 0
        assert api.authentication_token is None  # unchanged from init

    async def test_invalid_jwt_raises_error(self, api, mock_execute):
        mock_execute.return_value = login_response(hash_token="not-a-jwt")

        with pytest.raises(VerisureOwaError, match="Failed to decode"):
            await api.login()


# ── refresh_token() ──────────────────────────────────────────────────────────


class TestRefreshToken:
    async def test_success_stores_new_tokens(self, api, mock_execute):
        new_jwt = make_jwt(exp_minutes=15)
        new_refresh = make_jwt(exp_minutes=180 * 24 * 60)
        mock_execute.return_value = refresh_response(
            hash_token=new_jwt, refresh_token=new_refresh
        )

        result = await api.refresh_token()

        assert result is True
        assert api.authentication_token == new_jwt
        assert api.refresh_token_value == new_refresh

    async def test_success_updates_expiry(self, api, mock_execute):
        mock_execute.return_value = refresh_response()

        await api.refresh_token()

        assert api.authentication_token_exp > datetime.now()
        assert api.authentication_token_exp < datetime.now() + timedelta(minutes=20)

    async def test_success_updates_login_timestamp(self, api, mock_execute):
        mock_execute.return_value = refresh_response()
        before = int(datetime.now().timestamp() * 1000)

        await api.refresh_token()

        after = int(datetime.now().timestamp() * 1000)
        assert before <= api.login_timestamp <= after

    async def test_non_ok_res_returns_false(self, api, mock_execute):
        mock_execute.return_value = refresh_response(res="ERROR")

        result = await api.refresh_token()

        assert result is False

    async def test_missing_hash_returns_false(self, api, mock_execute):
        resp = refresh_response()
        resp["data"]["xSRefreshLogin"]["hash"] = ""
        mock_execute.return_value = resp

        result = await api.refresh_token()

        assert result is False

    async def test_null_hash_returns_false(self, api, mock_execute):
        resp = refresh_response()
        resp["data"]["xSRefreshLogin"]["hash"] = None
        mock_execute.return_value = resp

        result = await api.refresh_token()

        assert result is False

    async def test_jwt_decode_failure_returns_false(self, api, mock_execute):
        mock_execute.return_value = refresh_response(hash_token="not-a-jwt")

        result = await api.refresh_token()

        assert result is False

    async def test_none_response_raises_error(self, api, mock_execute):
        mock_execute.return_value = {"data": {"xSRefreshLogin": None}}

        with pytest.raises(VerisureOwaError, match="xSRefreshLogin response is None"):
            await api.refresh_token()

    async def test_does_not_store_tokens_on_failure(self, api, mock_execute):
        api.authentication_token = "old-token"
        api.refresh_token_value = "old-refresh"
        mock_execute.return_value = refresh_response(res="ERROR")

        await api.refresh_token()

        assert api.authentication_token == "old-token"
        assert api.refresh_token_value == "old-refresh"


# ── _check_authentication_token() ───────────────────────────────────────────


class TestCheckAuthenticationToken:
    async def test_valid_token_does_nothing(self, api):
        """When token is valid and not expiring soon, no action taken."""
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.now() + timedelta(hours=1)
        api.login = AsyncMock()
        api.refresh_token = AsyncMock()

        await api._check_authentication_token()

        api.login.assert_not_called()
        api.refresh_token.assert_not_called()

    async def test_expired_token_with_refresh_tries_refresh_first(self, api):
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min  # expired
        api.refresh_token_value = "has-refresh-token"
        api.refresh_token = AsyncMock(return_value=True)
        api.login = AsyncMock()

        await api._check_authentication_token()

        api.refresh_token.assert_awaited_once()
        api.login.assert_not_called()

    async def test_expired_token_refresh_fails_falls_back_to_login(self, api):
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min
        api.refresh_token_value = "has-refresh-token"
        api.refresh_token = AsyncMock(return_value=False)
        api.login = AsyncMock()

        await api._check_authentication_token()

        api.refresh_token.assert_awaited_once()
        api.login.assert_awaited_once()

    async def test_transient_refresh_exception_propagates_no_login(self, api):
        """A transient server error during refresh must NOT fall back to login
        (which would launder it into a 'no password' credential failure).
        It propagates so the coordinator retries next poll."""
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min
        api.refresh_token_value = "has-refresh-token"
        api.refresh_token = AsyncMock(
            side_effect=VerisureOwaError("boom", http_status=500)
        )
        api.login = AsyncMock()

        with pytest.raises(VerisureOwaError):
            await api._check_authentication_token()

        api.login.assert_not_called()
        assert api.consecutive_auth_recovery_failures == 1

    async def test_genuine_refresh_exception_falls_back_to_login(self, api):
        """A genuine token rejection (err 60067) falls back to login so a dead
        token surfaces as a clean reauth signal."""
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min
        api.refresh_token_value = "has-refresh-token"
        genuine = SessionExpiredError("Invalid Session", http_status=403)
        genuine.response_body = {"errors": [{"data": {"err": "60067"}}]}
        api.refresh_token = AsyncMock(side_effect=genuine)
        api.login = AsyncMock()

        await api._check_authentication_token()

        api.login.assert_awaited_once()
        assert api.consecutive_auth_recovery_failures == 0

    async def test_timeout_refresh_exception_propagates_as_owa_error(self, api):
        """A raw asyncio.TimeoutError during refresh is wrapped as a
        VerisureOwaError and propagated (transient), not funneled into login."""
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min
        api.refresh_token_value = "has-refresh-token"
        api.refresh_token = AsyncMock(side_effect=TimeoutError())
        api.login = AsyncMock()

        with pytest.raises(VerisureOwaError):
            await api._check_authentication_token()

        api.login.assert_not_called()
        assert api.consecutive_auth_recovery_failures == 1

    async def test_timeout_wrapped_with_descriptive_message(self, api):
        """A bare asyncio.TimeoutError is wrapped with a non-empty, descriptive
        message so the propagated error and streak log are actionable."""
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min
        api.refresh_token_value = "has-refresh-token"
        api.refresh_token = AsyncMock(side_effect=TimeoutError())
        api.login = AsyncMock()

        with pytest.raises(VerisureOwaError) as exc_info:
            await api._check_authentication_token()

        assert str(exc_info.value)  # non-empty
        assert "TimeoutError" in str(exc_info.value)

    async def test_expired_token_no_refresh_value_calls_login(self, api):
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min
        api.refresh_token_value = ""  # no refresh token
        api.login = AsyncMock()

        await api._check_authentication_token()

        api.login.assert_awaited_once()

    async def test_none_token_calls_login(self, api):
        api.authentication_token = None
        api.login = AsyncMock()

        await api._check_authentication_token()

        api.login.assert_awaited_once()


# ── validate_device() ────────────────────────────────────────────────────────


class TestValidateDevice:
    async def test_success_stores_hash_and_refresh_token(self, api, mock_execute):
        mock_execute.return_value = validate_device_response()

        result = await api.validate_device(
            otp_succeed=True, auth_otp_hash="otp-hash", sms_code="123456"
        )

        assert result == (None, None)
        assert api.authentication_token == FAKE_JWT
        assert api.refresh_token_value == FAKE_REFRESH_TOKEN

    async def test_success_decodes_jwt_expiry(self, api, mock_execute):
        mock_execute.return_value = validate_device_response()

        await api.validate_device(
            otp_succeed=True, auth_otp_hash="otp-hash", sms_code="123456"
        )

        assert api.authentication_token_exp > datetime.now()
        assert api.authentication_token_exp < datetime.now() + timedelta(minutes=20)

    async def test_jwt_decode_failure_logs_warning_doesnt_crash(
        self, api, mock_execute, caplog
    ):
        mock_execute.return_value = validate_device_response(hash_token="not-a-jwt")

        result = await api.validate_device(
            otp_succeed=True, auth_otp_hash="otp-hash", sms_code="123456"
        )

        assert result == (None, None)
        assert api.authentication_token == "not-a-jwt"
        # Expiry stays at default
        assert api.authentication_token_exp == datetime.min
        assert "Failed to decode" in caplog.text

    async def test_no_refresh_token_in_response(self, api, mock_execute):
        resp = validate_device_response()
        resp["data"]["xSValidateDevice"]["refreshToken"] = None
        mock_execute.return_value = resp

        await api.validate_device(
            otp_succeed=True, auth_otp_hash="otp-hash", sms_code="123456"
        )

        assert api.refresh_token_value == ""  # unchanged from init

    async def test_sets_otp_challenge_when_otp_succeed(self, api, mock_execute):
        mock_execute.return_value = validate_device_response()

        await api.validate_device(
            otp_succeed=True, auth_otp_hash="my-hash", sms_code="999999"
        )

        # Should be cleared after successful validation
        assert api.authentication_otp_challenge_value is None


# ── Additional login edge cases ──────────────────────────────────────────────


class TestLoginEdgeCases:
    async def test_error_with_need_device_authorization_raises_two_factor_required_error(
        self, api, mock_execute
    ):
        """When the transport's execute raises VerisureOwaError whose response data
        contains xSLoginToken.needDeviceAuthorization=True, TwoFactorRequiredError is raised."""
        error_response = {
            "data": {
                "xSLoginToken": {
                    "needDeviceAuthorization": True,
                    "hash": None,
                    "refreshToken": None,
                }
            }
        }
        _err = VerisureOwaError("Session expired")
        _err.response_body = error_response
        mock_execute.side_effect = _err

        with pytest.raises(TwoFactorRequiredError):
            await api.login()

    async def test_error_response_with_data_raises_authentication_error(
        self, api, mock_execute
    ):
        """When the transport's execute raises VerisureOwaError whose response data
        has xSLoginToken but needDeviceAuthorization is False, AuthenticationError is raised."""
        error_response = {
            "data": {
                "xSLoginToken": {
                    "needDeviceAuthorization": False,
                    "hash": None,
                    "refreshToken": None,
                }
            }
        }
        _err = VerisureOwaError("Some error")
        _err.response_body = error_response
        mock_execute.side_effect = _err

        with pytest.raises(AuthenticationError):
            await api.login()

    async def test_null_xslogintoken_raises_error(self, api, mock_execute):
        """When xSLoginToken is None in the response, VerisureOwaError is raised."""
        mock_execute.return_value = {"data": {"xSLoginToken": None}}

        with pytest.raises(VerisureOwaError, match="xSLoginToken response is None"):
            await api.login()

    async def test_login_stores_empty_token_for_null_hash(self, api, mock_execute):
        """When hash is None (2FA flow), auth token stays None but timestamp is set."""
        mock_execute.return_value = login_response(hash_token=None)  # type: ignore[arg-type]

        await api.login()

        assert api.authentication_token is None
        assert api.login_timestamp > 0

    async def test_account_blocked_raises_account_blocked_error(
        self, api, mock_execute
    ):
        """Error 60052 (account blocked) raises AccountBlockedError, not LoginError."""
        blocked_response = {
            "errors": [
                {
                    "message": "Utilisateur bloqué.",
                    "data": {"res": "ERROR", "err": "60052", "status": 403},
                }
            ],
            "data": {"xSLoginToken": None},
        }
        err = VerisureOwaError("Utilisateur bloqué.")
        err.response_body = blocked_response
        mock_execute.side_effect = err

        with pytest.raises(AccountBlockedError):
            await api.login()


# ── Additional validate_device edge cases ────────────────────────────────────


class TestValidateDeviceEdgeCases:
    async def test_error_with_phone_data_returns_otp_tuple(self, api, mock_execute):
        """When the transport's execute raises VerisureOwaError with phone data in
        the error response, returns (otp_hash, phones) tuple."""
        error_response = {
            "errors": [
                {
                    "message": "Unauthorized",
                    "data": {
                        "auth-otp-hash": "challenge-hash-123",
                        "auth-phones": [
                            {"id": 1, "phone": "***456"},
                            {"id": 2, "phone": "***789"},
                        ],
                    },
                }
            ]
        }
        _err = VerisureOwaError("Unauthorized")
        _err.response_body = error_response
        mock_execute.side_effect = _err

        result = await api.validate_device(
            otp_succeed=False, auth_otp_hash="", sms_code=""
        )

        assert result[0] == "challenge-hash-123"
        assert len(result[1]) == 2
        assert result[1][0].phone == "***456"
        assert result[1][1].phone == "***789"

    async def test_otp_not_succeed_returns_challenge_and_phones(
        self, api, mock_execute
    ):
        """When otp_succeed=False and response has errors with 'Unauthorized',
        returns the OTP challenge hash and phone list."""
        mock_execute.return_value = {
            "errors": [
                {
                    "message": "Unauthorized",
                    "data": {
                        "auth-otp-hash": "otp-hash-abc",
                        "auth-phones": [{"id": 1, "phone": "***111"}],
                    },
                }
            ]
        }

        result = await api.validate_device(
            otp_succeed=False, auth_otp_hash="", sms_code=""
        )

        assert result[0] == "otp-hash-abc"
        assert len(result[1]) == 1
        assert result[1][0].id == 1

    async def test_null_validate_data_raises_error(self, api, mock_execute):
        """When xSValidateDevice is None, VerisureOwaError is raised."""
        mock_execute.return_value = {"data": {"xSValidateDevice": None}}

        with pytest.raises(VerisureOwaError, match="xSValidateDevice response is None"):
            await api.validate_device(
                otp_succeed=True, auth_otp_hash="hash", sms_code="123456"
            )


# ── Additional refresh/auth edge cases ──────────────────────────────────────


class TestRefreshTokenEdgeCases:
    async def test_transient_refresh_error_propagates_no_login(self, api):
        """A bare VerisureOwaError from refresh (no err code) is transient —
        must propagate instead of falling back to login."""
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min  # expired
        api.refresh_token_value = "some-refresh-token"
        api.refresh_token = AsyncMock(side_effect=VerisureOwaError("Refresh failed"))
        api.login = AsyncMock()

        with pytest.raises(VerisureOwaError):
            await api._check_authentication_token()

        api.refresh_token.assert_awaited_once()
        api.login.assert_not_called()


# ── Auth-recovery streak counter ─────────────────────────────────────────────


class TestAuthRecoveryStreak:
    def test_starts_at_zero(self, api):
        assert api.consecutive_auth_recovery_failures == 0

    def test_record_increments_and_warns_first_time(self, api, caplog):
        with caplog.at_level("WARNING"):
            api.record_auth_recovery_failure(VerisureOwaError("boom", http_status=500))
        assert api.consecutive_auth_recovery_failures == 1
        assert "NOT forcing reauthentication" in caplog.text

    def test_escalates_at_threshold_with_report_url(self, api, caplog):
        with caplog.at_level("WARNING"):
            for _ in range(3):
                api.record_auth_recovery_failure(
                    VerisureOwaError("boom", http_status=500)
                )
        assert api.consecutive_auth_recovery_failures == 3
        assert "github.com/guerrerotook/securitas-direct-new-api/issues" in caplog.text
        assert "3 times" in caplog.text

    def test_escalation_is_throttled(self, api, caplog):
        with caplog.at_level("WARNING"):
            for _ in range(10):
                api.record_auth_recovery_failure(
                    VerisureOwaError("boom", http_status=500)
                )
        escalations = caplog.text.count("deliberately NOT forcing")
        assert escalations == 1

    def test_note_success_resets_and_logs_recovery(self, api, caplog):
        for _ in range(3):
            api.record_auth_recovery_failure(VerisureOwaError("boom", http_status=500))
        with caplog.at_level("INFO"):
            api.note_auth_success()
        assert api.consecutive_auth_recovery_failures == 0
        assert "recovered after 3 transient" in caplog.text

    def test_note_success_noop_when_no_streak(self, api, caplog):
        with caplog.at_level("INFO"):
            api.note_auth_success()
        assert api.consecutive_auth_recovery_failures == 0
        assert "recovered after" not in caplog.text

    def test_stale_streak_decays_to_fresh(self, api, caplog, monkeypatch):
        """A new failure long after the previous one starts a fresh streak,
        not a misleading high count spanning the idle gap."""
        # Seed a partial streak as if 2 failures happened, last one ~hours ago.
        api.consecutive_auth_recovery_failures = 2
        api._auth_streak_started = datetime.now() - timedelta(hours=3)
        api._last_auth_failure = datetime.now() - timedelta(hours=3)

        with caplog.at_level("WARNING"):
            api.record_auth_recovery_failure(VerisureOwaError("boom", http_status=500))

        # Treated as a fresh first failure, not count==3 escalation.
        assert api.consecutive_auth_recovery_failures == 1
        assert "deliberately NOT forcing" not in caplog.text

    def test_continuous_failures_still_escalate(self, api, caplog):
        """Back-to-back failures (no idle gap) still accumulate and escalate."""
        with caplog.at_level("WARNING"):
            for _ in range(3):
                api.record_auth_recovery_failure(
                    VerisureOwaError("boom", http_status=500)
                )
        assert api.consecutive_auth_recovery_failures == 3
        assert "deliberately NOT forcing" in caplog.text


class TestStreakResetOnSuccess:
    async def test_refresh_success_resets_streak(self, api, mock_execute):
        api.consecutive_auth_recovery_failures = 4
        mock_execute.return_value = refresh_response()

        ok = await api.refresh_token()

        assert ok is True
        assert api.consecutive_auth_recovery_failures == 0

    async def test_login_success_resets_streak(self, api, mock_execute):
        api.consecutive_auth_recovery_failures = 4
        mock_execute.return_value = login_response()

        await api.login()

        assert api.consecutive_auth_recovery_failures == 0


# ── Verisure refusing the saved sign-in: keep retrying, alert at 15 min ──────


class _Clock:
    """The time the client's ``datetime.now()`` reports, moved by hand.

    Real time is kept in UTC; the local wall clock is Lisbon's, so moving
    across 01:00 UTC on 2026-10-25 sets it back an hour as daylight saving
    ends.
    """

    def __init__(self) -> None:
        self.utc = datetime(2026, 10, 16, 14, 44, tzinfo=UTC)

    @property
    def now(self) -> datetime:
        """The local wall-clock time, naive like ``datetime.now()``."""
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


REFUSALS = pytest.mark.parametrize(
    "make_refusal",
    [
        refresh_token_rejected_error,
        refresh_token_rejected_err7_error,
        refresh_login_crash_error,
    ],
    ids=["err4", "err7", "crash"],
)


def _token_only_client(mock_transport, **kwargs) -> VerisureOwaClient:
    """A token-only client (no password, the norm since v5.1.0) with an
    expired auth token and a stored refresh token."""
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
        **kwargs,
    )
    client.authentication_token = FAKE_JWT
    client.authentication_token_exp = datetime.min
    client.login = AsyncMock()
    return client


def _succeed(client):
    """A refresh_token() side effect that renews the way the real one does."""

    async def _refresh():
        client.note_auth_success()
        return True

    return _refresh


async def _poll(client) -> Exception | None:
    """One renewal due on an expired token; returns what it raised."""
    client.authentication_token_exp = datetime.min
    try:
        await client._check_authentication_token()
    except Exception as err:  # pylint: disable=broad-exception-caught
        return err
    return None


async def _refuse_until_persisting(client, clock, make_refusal) -> None:
    """Polls every minute from t=0 to t=15, each refused: persisting at t=15."""
    client.refresh_token = AsyncMock(side_effect=_fresh(make_refusal))
    for minute in range(16):
        if minute:
            clock.advance(minutes=1)
        await _poll(client)
    assert client.refresh_refusals_persisting


def _fresh(make_refusal):
    """A side effect raising a new refusal on every call."""

    def _refuse():
        raise make_refusal()

    return _refuse


class TestRefusalsKeepRetrying:
    """A refusal (err 4, err 7 or the #568 crash) is never Verisure saying the token is
    invalid, so the token is never condemned: every refusal is a transient
    failure the coordinators retry. After 15 minutes of them the host is told
    once, and renewals slow to one every 5 minutes."""

    @REFUSALS
    async def test_refusals_never_ask_for_reauth(
        self, mock_transport, clock, make_refusal
    ):
        client = _token_only_client(mock_transport)
        client.refresh_token = AsyncMock(side_effect=_fresh(make_refusal))

        for _ in range(15):
            err = await _poll(client)
            assert isinstance(err, VerisureOwaError)
            assert not isinstance(err, AuthenticationError)
            assert not is_genuine_auth_failure(err)
            assert dead_refresh_token_signal(err) is not None
            clock.advance(minutes=1)
        assert client.refresh_token.await_count == 15

        for _ in range(120):
            err = await _poll(client)
            assert isinstance(err, VerisureOwaError)
            assert not isinstance(err, AuthenticationError)
            clock.advance(minutes=1)
        client.login.assert_not_called()

    @REFUSALS
    async def test_a_single_refusal_is_not_persisting(
        self, mock_transport, clock, make_refusal
    ):
        client = _token_only_client(mock_transport)
        client.refresh_token = AsyncMock(side_effect=make_refusal())

        await _poll(client)

        assert client.refresh_refusals_persisting is False

    @REFUSALS
    async def test_minute_polls_alert_once_at_15_minutes_then_pace(
        self, mock_transport, clock, make_refusal, caplog
    ):
        alerted_at: list[tuple[bool, datetime]] = []
        client = _token_only_client(
            mock_transport,
            on_refresh_refusal_alert=lambda active: alerted_at.append(
                (active, clock.now)
            ),
        )
        client.refresh_token = AsyncMock(side_effect=_fresh(make_refusal))
        client.record_auth_recovery_failure = MagicMock()
        start = clock.now
        attempted: list[int] = []
        paced: list[int] = []

        with caplog.at_level("WARNING"):
            for minute in range(61):
                calls = client.refresh_token.await_count
                err = await _poll(client)
                assert isinstance(err, VerisureOwaError)
                assert not isinstance(err, AuthenticationError)
                if client.refresh_token.await_count > calls:
                    attempted.append(minute)
                else:
                    paced.append(minute)
                    assert "still refusing" in str(err)
                clock.advance(minutes=1)

        assert attempted == list(range(16)) + list(range(20, 61, 5))
        assert alerted_at == [(True, start + timedelta(minutes=15))]
        assert caplog.text.count("refused to renew the saved sign-in") == 1
        assert client.record_auth_recovery_failure.call_count == len(attempted)
        client.login.assert_not_called()

    @pytest.mark.parametrize(
        "failure",
        [TimeoutError(), VerisureOwaError("boom", http_status=500)],
        ids=["timeout", "5xx"],
    )
    async def test_any_attempt_while_persisting_restarts_the_five_minutes(
        self, mock_transport, clock, failure
    ):
        client = _token_only_client(mock_transport)
        await _refuse_until_persisting(client, clock, refresh_token_rejected_error)

        clock.advance(minutes=5)  # t=20
        client.refresh_token = AsyncMock(side_effect=failure)
        assert isinstance(await _poll(client), VerisureOwaError)
        assert client.refresh_token.await_count == 1

        client.refresh_token = AsyncMock(side_effect=refresh_token_rejected_error())
        for _ in range(4):  # t=21..24
            clock.advance(minutes=1)
            assert "still refusing" in str(await _poll(client))
        assert client.refresh_token.await_count == 0
        clock.advance(minutes=1)  # t=25
        await _poll(client)
        assert client.refresh_token.await_count == 1

    @REFUSALS
    async def test_success_after_the_alert_clears_it_and_starts_afresh(
        self, mock_transport, clock, make_refusal
    ):
        alerts = MagicMock()
        client = _token_only_client(mock_transport, on_refresh_refusal_alert=alerts)
        await _refuse_until_persisting(client, clock, make_refusal)

        clock.advance(minutes=5)
        client.refresh_token = AsyncMock(side_effect=_succeed(client))
        assert await _poll(client) is None

        assert alerts.call_args_list == [call(True), call(False)]
        assert client.refresh_refusals_persisting is False

        # A new period: no pacing, no alert until 15 minutes of refusals.
        client.refresh_token = AsyncMock(side_effect=_fresh(make_refusal))
        for _ in range(15):
            clock.advance(minutes=1)
            await _poll(client)
        assert client.refresh_token.await_count == 15
        assert alerts.call_count == 2

    async def test_success_without_an_alert_calls_nothing(self, mock_transport, clock):
        alerts = MagicMock()
        client = _token_only_client(mock_transport, on_refresh_refusal_alert=alerts)
        client.refresh_token = AsyncMock(side_effect=refresh_token_rejected_error())
        await _poll(client)

        clock.advance(minutes=1)
        client.refresh_token = AsyncMock(side_effect=_succeed(client))
        assert await _poll(client) is None

        alerts.assert_not_called()

    async def test_refusals_and_crashes_share_one_period(self, mock_transport, clock):
        alerts = MagicMock()
        client = _token_only_client(mock_transport, on_refresh_refusal_alert=alerts)
        refusals = [
            refresh_token_rejected_error,
            refresh_token_rejected_err7_error,
            refresh_login_crash_error,
        ]

        for minute in range(16):
            client.refresh_token = AsyncMock(
                side_effect=refusals[minute % len(refusals)]()
            )
            await _poll(client)
            clock.advance(minutes=1)

        alerts.assert_called_once_with(True)

    @pytest.mark.parametrize(
        "failure",
        [TimeoutError(), VerisureOwaError("boom", http_status=500)],
        ids=["timeout", "5xx"],
    )
    async def test_other_failures_neither_start_nor_reset_the_period(
        self, mock_transport, clock, failure
    ):
        alerts = MagicMock()
        client = _token_only_client(mock_transport, on_refresh_refusal_alert=alerts)

        # Other failures alone never start one.
        client.refresh_token = AsyncMock(side_effect=failure)
        for _ in range(30):
            await _poll(client)
            clock.advance(minutes=1)
        alerts.assert_not_called()
        assert client.refresh_refusals_persisting is False

        # Refusal, other failures, refusal 15 minutes later: still one period.
        client.refresh_token = AsyncMock(side_effect=refresh_token_rejected_error())
        await _poll(client)
        client.refresh_token = AsyncMock(side_effect=failure)
        for _ in range(14):
            clock.advance(minutes=1)
            await _poll(client)
        clock.advance(minutes=1)
        client.refresh_token = AsyncMock(side_effect=refresh_token_rejected_error())
        await _poll(client)

        alerts.assert_called_once_with(True)

    @REFUSALS
    async def test_a_stored_password_is_used_once_persisting(
        self, mock_transport, clock, make_refusal
    ):
        """A stored password is the stronger credential: once refusals persist,
        use it rather than keep presenting the refused token."""
        client = _token_only_client(mock_transport, password="secret")
        client.refresh_token = AsyncMock(side_effect=_fresh(make_refusal))

        for _ in range(15):
            assert isinstance(await _poll(client), VerisureOwaError)
            clock.advance(minutes=1)
        client.login.assert_not_called()

        assert await _poll(client) is None  # t=15: persisting
        client.login.assert_awaited_once()

        # The mocked login does not end the period, as a failed one would not:
        # the password login is paced like a refresh.
        calls = client.refresh_token.await_count
        for _ in range(4):  # t=16..19
            clock.advance(minutes=1)
            assert "still refusing" in str(await _poll(client))
        assert client.login.await_count == 1
        clock.advance(minutes=1)  # t=20
        assert await _poll(client) is None
        assert client.refresh_token.await_count == calls
        assert client.login.await_count == 2

    async def test_a_failing_password_login_is_paced(self, mock_transport, clock):
        """A password login that fails while refusals persist (a 5xx during an
        outage) is tried at most once every 5 minutes, like a refresh."""
        client = _token_only_client(mock_transport, password="secret")
        del client.login  # the real login, failing at the transport
        logins: list[datetime] = []

        async def execute(content, headers, **kwargs):
            if content["operationName"] == "RefreshLogin":
                raise refresh_token_rejected_error()
            assert content["operationName"] == "mkLoginToken"
            logins.append(clock.utc)
            raise VerisureOwaError("server unavailable", http_status=500)

        mock_transport.execute.side_effect = execute
        start = clock.utc

        for minute in range(26):
            if minute:
                clock.advance(minutes=1)
            assert isinstance(await _poll(client), VerisureOwaError)

        assert logins == [start + timedelta(minutes=m) for m in (15, 20, 25)]

    @REFUSALS
    async def test_adopting_a_token_retries_at_once_and_keeps_the_alert(
        self, mock_transport, clock, make_refusal
    ):
        alerts = MagicMock()
        client = _token_only_client(mock_transport, on_refresh_refusal_alert=alerts)
        await _refuse_until_persisting(client, clock, make_refusal)

        clock.advance(minutes=1)
        client.adopt_refresh_token("co-tenant-token")
        assert client.refresh_refusals_persisting is False
        assert client.refresh_refusal_alert_raised is True
        calls = client.refresh_token.await_count
        await _poll(client)
        assert client.refresh_token.await_count == calls + 1
        clock.advance(minutes=1)
        await _poll(client)
        assert client.refresh_token.await_count == calls + 2
        alerts.assert_called_once_with(True)

        clock.advance(minutes=1)
        client.refresh_token = AsyncMock(side_effect=_succeed(client))
        assert await _poll(client) is None
        assert alerts.call_args_list == [call(True), call(False)]
        assert client.refresh_refusal_alert_raised is False

    async def test_restoring_undoes_an_adoption(self, mock_transport, clock):
        """An adopted token that fails is handed back: the client's own token
        and its refusal period return as they were, so renewals stay paced."""
        client = _token_only_client(mock_transport)
        client.refresh_token_value = "own-token"
        await _refuse_until_persisting(client, clock, refresh_token_rejected_error)

        clock.advance(minutes=1)
        snapshot = client.adopt_refresh_token("co-tenant-token")
        assert client.refresh_token_value == "co-tenant-token"
        client.restore_refresh_token(snapshot)

        assert client.refresh_token_value == "own-token"
        assert client.refresh_refusals_persisting is True
        calls = client.refresh_token.await_count
        err = await _poll(client)
        assert "next try after" in str(err)
        assert client.refresh_token.await_count == calls
        clock.advance(minutes=4)
        await _poll(client)
        assert client.refresh_token.await_count == calls + 1

    async def test_restoring_masks_the_restored_token_in_logs(self, mock_transport):
        """The log filter masks one refresh token at a time: after an adoption
        is undone it must mask the token back in use, not the failed one."""
        log_filter = SensitiveDataFilter()
        client = _token_only_client(mock_transport, log_filter=log_filter)

        client.restore_refresh_token(client.adopt_refresh_token("co-tenant-token"))

        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="presenting has-refresh-token",
            args=(),
            exc_info=None,
        )
        log_filter.filter(record)
        assert "has-refresh-token" not in record.msg
        assert "[REFRESH_TOKEN]" in record.msg

    async def test_restoring_keeps_the_period_start(self, mock_transport, clock):
        """A period not yet persisting keeps its start: the refusal 15 minutes
        after the first still raises the alert."""
        alerts = MagicMock()
        client = _token_only_client(mock_transport, on_refresh_refusal_alert=alerts)
        client.refresh_token = AsyncMock(
            side_effect=_fresh(refresh_token_rejected_error)
        )
        await _poll(client)

        clock.advance(minutes=14)
        client.restore_refresh_token(client.adopt_refresh_token("co-tenant-token"))
        clock.advance(minutes=1)
        await _poll(client)

        alerts.assert_called_once_with(True)

    async def test_a_raising_callback_does_not_break_renewal(
        self, mock_transport, clock, caplog
    ):
        client = _token_only_client(
            mock_transport, on_refresh_refusal_alert=MagicMock(side_effect=OSError)
        )
        with caplog.at_level("WARNING"):
            await _refuse_until_persisting(client, clock, refresh_token_rejected_error)

            clock.advance(minutes=5)
            client.refresh_token = AsyncMock(side_effect=_succeed(client))
            assert await _poll(client) is None

        assert caplog.text.count("on_refresh_refusal_alert callback raised") == 2

    async def test_clock_set_back_while_persisting_keeps_five_minute_pacing(
        self, mock_transport, clock
    ):
        """Daylight saving ending must not stretch the 5-minute wait to 65."""
        clock.utc = datetime(2026, 10, 25, 0, 41, tzinfo=UTC)
        client = _token_only_client(mock_transport)
        await _refuse_until_persisting(client, clock, refresh_token_rejected_error)
        before = clock.now  # 01:56 local, the last attempt
        attempted: list[int] = []
        messages: list[str] = []

        for minute in range(1, 11):
            clock.advance(minutes=1)
            calls = client.refresh_token.await_count
            err = await _poll(client)
            if client.refresh_token.await_count > calls:
                attempted.append(minute)
            else:
                messages.append(str(err))

        assert clock.now < before  # the wall clock really went back
        assert attempted == [5, 10]
        # The next try reads in local time, after the change: 01:01 WET.
        assert all(m.endswith("next try after 01:01:00") for m in messages[:4])

    async def test_clock_set_back_does_not_delay_the_alert(self, mock_transport, clock):
        clock.utc = datetime(2026, 10, 25, 0, 50, tzinfo=UTC)  # 01:50 local
        alerted_at: list[datetime] = []
        client = _token_only_client(
            mock_transport,
            on_refresh_refusal_alert=lambda active: alerted_at.append(clock.utc),
        )
        client.refresh_token = AsyncMock(
            side_effect=_fresh(refresh_token_rejected_error)
        )

        for _ in range(21):
            await _poll(client)
            clock.advance(minutes=1)

        # 15 minutes after the first refusal, though local time read 01:05.
        assert alerted_at == [datetime(2026, 10, 25, 1, 5, tzinfo=UTC)]

    async def test_concurrent_renewals_while_paced_share_one_attempt(
        self, mock_transport, clock
    ):
        client = _token_only_client(mock_transport)
        await _refuse_until_persisting(client, clock, refresh_token_rejected_error)
        client.refresh_token = AsyncMock(
            side_effect=_yielding(_fresh(refresh_token_rejected_error))
        )

        clock.advance(minutes=1)
        results = await _race(client)
        assert all("still refusing" in str(r) for r in results)
        assert client.refresh_token.await_count == 0

        clock.advance(minutes=4)  # the window's end
        results = await _race(client)
        assert all(isinstance(r, VerisureOwaError) for r in results)
        assert client.refresh_token.await_count == 1

    async def test_concurrent_callers_at_the_window_end_share_one_renewal(
        self, mock_transport, clock
    ):
        """The caller queued behind the one allowed attempt waits for its
        result: when it renews, both carry on with the new token rather than
        the second being told Verisure is still refusing."""
        client = _token_only_client(mock_transport)
        await _refuse_until_persisting(client, clock, refresh_token_rejected_error)

        async def _renew():
            client.authentication_token_exp = clock.now + timedelta(minutes=15)
            client.note_auth_success()
            return True

        client.refresh_token = AsyncMock(side_effect=_yielding(_renew))
        clock.advance(minutes=5)  # the window's end

        assert await _race(client) == [None, None]
        assert client.refresh_token.await_count == 1
        assert client.refresh_refusals_persisting is False


class TestKeptPassword:
    """A password the user chose to keep is spent at the first refusal; one
    held only in memory waits until refusals persist."""

    @REFUSALS
    async def test_kept_password_signs_in_at_the_first_refusal(
        self, mock_transport, clock, make_refusal
    ):
        alerts = MagicMock()
        client = _token_only_client(
            mock_transport,
            password="secret",
            password_kept=True,
            on_refresh_refusal_alert=alerts,
        )
        client.refresh_token = AsyncMock(side_effect=make_refusal())

        assert await _poll(client) is None

        client.login.assert_awaited_once()
        alerts.assert_not_called()

    async def test_kept_password_login_failing_transiently_keeps_the_refusal_period(
        self, mock_transport, clock
    ):
        alerts = MagicMock()
        client = _token_only_client(
            mock_transport,
            password="secret",
            password_kept=True,
            on_refresh_refusal_alert=alerts,
        )
        del client.login  # the real login, failing at the transport
        operations: list[str] = []

        async def execute(content, headers, **kwargs):
            operations.append(content["operationName"])
            if content["operationName"] == "RefreshLogin":
                raise refresh_token_rejected_error()
            assert content["operationName"] == "mkLoginToken"
            raise APIConnectionError("connection reset")

        mock_transport.execute.side_effect = execute

        assert isinstance(await _poll(client), APIConnectionError)
        assert operations == ["RefreshLogin", "mkLoginToken"]

        clock.advance(minutes=1)
        err = await _poll(client)
        assert "still refusing" in str(err)
        assert operations == ["RefreshLogin", "mkLoginToken"]

        for _ in range(14):
            clock.advance(minutes=1)
            await _poll(client)
        alerts.assert_called_once_with(True)

    @REFUSALS
    async def test_in_memory_password_waits_for_persisting_refusals(
        self, mock_transport, clock, make_refusal
    ):
        client = _token_only_client(mock_transport, password="secret")
        client.refresh_token = AsyncMock(side_effect=make_refusal())

        assert isinstance(await _poll(client), VerisureOwaError)

        client.login.assert_not_called()


def _yielding(effect):
    """Wrap a refresh_token() side effect so it yields to the event loop
    first, as a real network call does, letting a concurrent caller run."""

    async def _effect():
        await asyncio.sleep(0)
        result = effect()
        if asyncio.iscoroutine(result):
            result = await result
        return result

    return _effect


async def _race(client) -> list[BaseException | None]:
    """Two renewals due at once on an expired token; what each one returned."""
    client.authentication_token_exp = datetime.min
    return await asyncio.gather(
        client._check_authentication_token(),
        client._check_authentication_token(),
        return_exceptions=True,
    )


# ── Auth mutations opt out of the transport's blind 403 retry ──────────────


class TestAuthMutationsSkip403Retry:
    """RefreshLogin and friends consume one-time material on the first send."""

    async def test_refresh_login_is_sent_without_403_retry(self, api, mock_execute):
        api.refresh_token_value = FAKE_REFRESH_TOKEN
        mock_execute.return_value = refresh_response()

        assert await api.refresh_token() is True

        assert mock_execute.await_args.kwargs.get("retry_on_403") is False

    async def test_login_is_sent_without_403_retry(self, api, mock_execute):
        mock_execute.return_value = login_response()

        await api.login()

        assert mock_execute.await_args.kwargs.get("retry_on_403") is False

    async def test_typed_path_also_opts_auth_operations_out(self, api, mock_execute):
        """Both transport call sites must agree, or a future auth mutation on
        the typed path silently regains the blind retry."""
        mock_execute.return_value = refresh_response()

        class _Envelope(BaseModel):
            data: dict

        await api._execute_graphql(
            {"operationName": "RefreshLogin"}, "RefreshLogin", _Envelope
        )

        assert mock_execute.await_args.kwargs.get("retry_on_403") is False

    async def test_data_operations_keep_the_403_retry(self, api, mock_execute):
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.now() + timedelta(hours=1)
        mock_execute.return_value = {"data": {"xSInstallations": {"installations": []}}}

        await api.list_installations()

        assert mock_execute.await_args.kwargs.get("retry_on_403", True) is True
