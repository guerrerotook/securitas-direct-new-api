"""Client behaviour around the issue #557 xSRefreshLogin 'fr' crash.

The root cause of #557 — a rotated refresh token that was never persisted to
the config entry, so a restart reloaded a stale token — is fixed in the setup
path (``_get_or_create_session`` now attaches the entry to a reused config-flow
hub). These tests characterise the *client-side* handling of the server crash
itself, which is independent of that fix: the crash is classified transient
(retryable), not a genuine auth failure, and it leaves the stored refresh token
untouched. They guard against a future change silently turning the crash into a
reauth trigger or corrupting the stored token.
"""

from __future__ import annotations

import pytest

from custom_components.securitas.verisure_owa_api.client import VerisureOwaClient
from custom_components.securitas.verisure_owa_api.exceptions import (
    VerisureOwaError,
    is_genuine_auth_failure,
    is_refresh_token_crash,
)

# The exact server crash from issue #557: xSRefreshLogin resolver throws a
# JS TypeError and returns a null field.
FR_CRASH_RESPONSE = {
    "errors": [
        {
            "message": "Cannot read properties of undefined (reading 'fr')",
            "path": ["xSRefreshLogin"],
            "locations": [{"line": 2, "column": 3}],
            "extensions": {},
            "data": {},
        }
    ],
    "data": {"xSRefreshLogin": None},
}


def _make_client(mock_transport, *, refresh_token: str) -> VerisureOwaClient:
    """An FR client with a mocked transport and a preloaded refresh token.

    The shared ``api`` fixture is ES with no refresh token, so this file needs
    its own factory for the FR locale and the on-disk token these tests exercise.
    """
    return VerisureOwaClient(
        transport=mock_transport,
        country="FR",
        language="fr",
        username="user@example.com",
        password="",
        device_id="dev-id",
        uuid="uuid-value",
        id_device_indigitall="indigitall-value",
        refresh_token=refresh_token,
    )


class TestRefreshCrashHandling:
    """The client treats the FR server crash as a transient, non-destructive error.

    The #557 *trap* — the entry stuck until deleted — arose from the setup path
    feeding a stale refresh token, now fixed. Independently, the client's
    handling of the crash response itself must stay safe: it is classified
    transient (so the coordinator retries rather than forcing reauth) and it
    leaves the stored refresh token untouched (so nothing is corrupted).
    """

    async def test_crash_leaves_the_on_disk_token_unchanged(
        self, mock_transport
    ) -> None:
        """The failing refresh does not rotate the token — the retry reuses it."""
        mock_transport.execute.return_value = FR_CRASH_RESPONSE
        client = _make_client(mock_transport, refresh_token="on-disk-refresh-token")

        with pytest.raises(VerisureOwaError):
            await client.refresh_token()

        assert client.refresh_token_value == "on-disk-refresh-token"

    async def test_crash_is_classified_transient_not_a_reauth_signal(
        self, mock_transport
    ) -> None:
        """The crash is NOT a genuine auth failure, so it retries, never reauths."""
        mock_transport.execute.return_value = FR_CRASH_RESPONSE
        client = _make_client(mock_transport, refresh_token="on-disk-refresh-token")

        with pytest.raises(VerisureOwaError) as excinfo:
            await client.refresh_token()

        assert is_genuine_auth_failure(excinfo.value) is False

    async def test_crash_is_recognised_as_a_refresh_token_crash(
        self, mock_transport
    ) -> None:
        """End-to-end: the *real* error object matches the dead-token fingerprint.

        Guards the seam between where the client raises the crash (its
        ``response_body`` must carry the ``xSRefreshLogin`` path) and the
        ``is_refresh_token_crash`` fingerprint the setup path escalates on.
        """
        mock_transport.execute.return_value = FR_CRASH_RESPONSE
        client = _make_client(mock_transport, refresh_token="on-disk-refresh-token")

        with pytest.raises(VerisureOwaError) as excinfo:
            await client.refresh_token()

        assert is_refresh_token_crash(excinfo.value) is True


# The same resolver crash localised to a different language — the null field is
# read via the account's locale, so the message word after "reading" varies.
ES_CRASH_RESPONSE = {
    "errors": [
        {
            "message": "Cannot read properties of undefined (reading 'es')",
            "path": ["xSRefreshLogin"],
            "locations": [{"line": 2, "column": 3}],
            "extensions": {},
            "data": {},
        }
    ],
    "data": {"xSRefreshLogin": None},
}

# A genuine, coded refresh rejection (err 60067 "Invalid Session") — a real
# reauth signal handled by is_genuine_auth_failure, NOT the uncoded crash.
CODED_REJECTION_RESPONSE = {
    "errors": [
        {
            "message": "Invalid Session",
            "path": ["xSRefreshLogin"],
            "data": {"err": "60067"},
        }
    ],
    "data": {"xSRefreshLogin": None},
}


class TestIsRefreshTokenCrash:
    """``is_refresh_token_crash`` fingerprints the dead-token xSRefreshLogin crash.

    It identifies the *specific* server crash that signals a stale on-disk
    refresh token (so the setup path can escalate a persistent one to reauth),
    while excluding coded rejections (handled elsewhere) and generic transient
    errors (5xx/WAF/network) that must keep retrying.
    """

    def _err(self, body: object) -> VerisureOwaError:
        err = VerisureOwaError("xSRefreshLogin failed")
        err.response_body = body
        return err

    def test_matches_the_fr_crash(self) -> None:
        assert is_refresh_token_crash(self._err(FR_CRASH_RESPONSE)) is True

    def test_matches_the_same_crash_in_another_locale(self) -> None:
        """Matching is on the operation path, not the locale word in the message."""
        assert is_refresh_token_crash(self._err(ES_CRASH_RESPONSE)) is True

    def test_ignores_a_coded_rejection(self) -> None:
        """A real err-coded rejection is a genuine auth failure, not this crash."""
        assert is_refresh_token_crash(self._err(CODED_REJECTION_RESPONSE)) is False

    def test_ignores_an_error_with_no_response_body(self) -> None:
        """Network/timeout errors carry no GraphQL body and must not match."""
        assert is_refresh_token_crash(VerisureOwaError("connection failed")) is False

    def test_ignores_a_crash_in_a_different_operation(self) -> None:
        """A null-data error on some other resolver is not the refresh crash."""
        body = {
            "errors": [{"message": "boom", "path": ["xSSomethingElse"], "data": {}}],
            "data": {"xSSomethingElse": None},
        }
        assert is_refresh_token_crash(self._err(body)) is False

    def test_ignores_an_uncoded_error_with_a_non_null_result(self) -> None:
        """Only the *null-result* resolver crash counts, not any uncoded error.

        An uncoded GraphQL error that still returned a real xSRefreshLogin
        payload is not the dead-token crash and must not trigger reauth.
        """
        body = {
            "errors": [{"message": "partial", "path": ["xSRefreshLogin"], "data": {}}],
            "data": {"xSRefreshLogin": {"res": "OK"}},
        }
        assert is_refresh_token_crash(self._err(body)) is False

    def test_ignores_an_error_not_rooted_at_the_operation(self) -> None:
        """The errored path must be rooted at xSRefreshLogin, not merely mention it."""
        body = {
            "errors": [
                {"message": "boom", "path": ["other", "xSRefreshLogin"], "data": {}}
            ],
            "data": {"other": None},
        }
        assert is_refresh_token_crash(self._err(body)) is False
