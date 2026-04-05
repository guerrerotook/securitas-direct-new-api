"""Tests for the Securitas Direct exception hierarchy."""

from __future__ import annotations

import pytest

from custom_components.securitas.securitas_direct_new_api.exceptions import (
    # New typed hierarchy
    APIConnectionError,
    APIResponseError,
    ArmingExceptionError,
    AuthenticationError,
    ImageCaptureError,
    OperationFailedError,
    OperationTimeoutError,
    SecuritasDirectError,
    SessionExpiredError,
    TwoFactorRequiredError,
    UnexpectedStateError,
    WAFBlockedError,
    # Backward-compat aliases
    APIError,
    AuthError,
    Login2FAError,
    LoginError,
    TokenRefreshError,
)


# ── Subclass checks ───────────────────────────────────────────────────────────


class TestSubclassRelationships:
    """Every exception type must derive from SecuritasDirectError."""

    @pytest.mark.parametrize(
        "exc_class",
        [
            AuthenticationError,
            TwoFactorRequiredError,
            SessionExpiredError,
            APIResponseError,
            WAFBlockedError,
            APIConnectionError,
            OperationTimeoutError,
            OperationFailedError,
            ArmingExceptionError,
            ImageCaptureError,
            UnexpectedStateError,
        ],
    )
    def test_is_subclass_of_base(self, exc_class):
        assert issubclass(exc_class, SecuritasDirectError)

    def test_base_is_exception(self):
        assert issubclass(SecuritasDirectError, Exception)


# ── Basic construction & message ─────────────────────────────────────────────


class TestBasicConstruction:
    def test_securitas_direct_error_message(self):
        err = SecuritasDirectError("something went wrong")
        assert err.message == "something went wrong"

    def test_authentication_error(self):
        err = AuthenticationError("bad credentials")
        assert err.message == "bad credentials"
        assert isinstance(err, SecuritasDirectError)

    def test_two_factor_required_error(self):
        err = TwoFactorRequiredError("2FA required")
        assert err.message == "2FA required"
        assert isinstance(err, SecuritasDirectError)

    def test_session_expired_error(self):
        err = SessionExpiredError("JWT expired")
        assert err.message == "JWT expired"
        assert isinstance(err, SecuritasDirectError)

    def test_waf_blocked_error(self):
        err = WAFBlockedError("WAF block")
        assert err.message == "WAF block"
        assert isinstance(err, SecuritasDirectError)

    def test_api_connection_error(self):
        err = APIConnectionError("network failure")
        assert err.message == "network failure"
        assert isinstance(err, SecuritasDirectError)

    def test_operation_timeout_error(self):
        err = OperationTimeoutError("timed out")
        assert err.message == "timed out"
        assert isinstance(err, SecuritasDirectError)

    def test_image_capture_error(self):
        err = ImageCaptureError("capture failed")
        assert err.message == "capture failed"
        assert isinstance(err, SecuritasDirectError)


# ── Typed-field exceptions ────────────────────────────────────────────────────


class TestAPIResponseError:
    def test_no_http_status(self):
        err = APIResponseError("GraphQL error")
        assert err.message == "GraphQL error"
        assert err.http_status is None

    def test_with_http_status(self):
        err = APIResponseError("Forbidden", http_status=403)
        assert err.http_status == 403
        assert err.message == "Forbidden"

    def test_is_subclass(self):
        assert issubclass(APIResponseError, SecuritasDirectError)


class TestOperationFailedError:
    def test_defaults(self):
        err = OperationFailedError("panel rejected")
        assert err.message == "panel rejected"
        assert err.error_code is None
        assert err.error_type is None

    def test_with_codes(self):
        err = OperationFailedError("rejected", error_code="E01", error_type="LOCK")
        assert err.error_code == "E01"
        assert err.error_type == "LOCK"
        assert err.message == "rejected"

    def test_is_subclass(self):
        assert issubclass(OperationFailedError, SecuritasDirectError)


class TestArmingExceptionError:
    def _make(self, aliases: list[str]) -> ArmingExceptionError:
        exceptions = [{"alias": a, "status": "OPEN"} for a in aliases]
        return ArmingExceptionError("ref-1", "suid-42", exceptions)

    def test_carries_reference_id(self):
        err = self._make(["Kitchen window"])
        assert err.reference_id == "ref-1"

    def test_carries_suid(self):
        err = self._make(["Kitchen window"])
        assert err.suid == "suid-42"

    def test_carries_exceptions_list(self):
        err = self._make(["Kitchen window", "Garage door"])
        assert len(err.exceptions) == 2

    def test_message_includes_alias(self):
        err = self._make(["Kitchen window"])
        assert "Kitchen window" in err.message

    def test_message_includes_multiple_aliases(self):
        err = self._make(["Zone A", "Zone B"])
        assert "Zone A" in err.message
        assert "Zone B" in err.message

    def test_missing_alias_falls_back_to_unknown(self):
        err = ArmingExceptionError("ref-1", "suid-42", [{"status": "OPEN"}])
        assert "unknown" in err.message

    def test_empty_exceptions(self):
        err = ArmingExceptionError("ref-1", "suid-42", [])
        assert "Arming blocked by exceptions:" in err.message

    def test_is_subclass(self):
        assert issubclass(ArmingExceptionError, SecuritasDirectError)


class TestUnexpectedStateError:
    def test_carries_proto_code(self):
        err = UnexpectedStateError("XYZ")
        assert err.proto_code == "XYZ"

    def test_message_includes_proto_code(self):
        err = UnexpectedStateError("XYZ")
        assert "XYZ" in err.message

    def test_is_subclass(self):
        assert issubclass(UnexpectedStateError, SecuritasDirectError)


# ── log_detail() behaviour ────────────────────────────────────────────────────


class TestLogDetail:
    """log_detail() returns brief output for known statuses, verbose otherwise."""

    KNOWN_STATUSES = [400, 403, 409]
    UNKNOWN_STATUSES = [500, 502, 429, None]

    @pytest.mark.parametrize("status", KNOWN_STATUSES)
    def test_known_status_returns_message_only(self, status):
        err = APIResponseError("known error", http_status=status)
        err.response_body = {"errors": ["something"]}
        assert err.log_detail() == "known error"

    @pytest.mark.parametrize("status", UNKNOWN_STATUSES)
    def test_unknown_status_with_body_includes_body(self, status):
        err = APIResponseError("unknown error", http_status=status)
        err.response_body = {"errors": ["oops"]}
        detail = err.log_detail()
        assert "unknown error" in detail
        assert "oops" in detail

    def test_unknown_status_without_body_returns_message(self):
        err = SecuritasDirectError("bare error", http_status=500)
        assert err.log_detail() == "bare error"

    def test_no_status_no_body_returns_message(self):
        err = SecuritasDirectError("bare error")
        assert err.log_detail() == "bare error"

    def test_response_body_set_after_construction(self):
        err = SecuritasDirectError("late body", http_status=500)
        assert err.log_detail() == "late body"
        err.response_body = {"raw": "data"}
        assert "raw" in err.log_detail()


# ── Backward-compatibility aliases ────────────────────────────────────────────


class TestBackwardCompatAliases:
    def test_login_error_is_authentication_error(self):
        assert LoginError is AuthenticationError

    def test_login_2fa_error_is_two_factor_required_error(self):
        assert Login2FAError is TwoFactorRequiredError

    def test_auth_error_is_authentication_error(self):
        assert AuthError is AuthenticationError

    def test_token_refresh_error_is_session_expired_error(self):
        assert TokenRefreshError is SessionExpiredError

    def test_api_error_is_api_response_error(self):
        assert APIError is APIResponseError

    def test_login_error_instance_caught_as_authentication_error(self):
        with pytest.raises(AuthenticationError):
            raise LoginError("bad credentials")

    def test_login_2fa_instance_caught_as_two_factor_required(self):
        with pytest.raises(TwoFactorRequiredError):
            raise Login2FAError("need 2fa")

    def test_alias_instances_are_subclass_of_base(self):
        for alias in (LoginError, Login2FAError, AuthError, TokenRefreshError, APIError):
            assert issubclass(alias, SecuritasDirectError)
