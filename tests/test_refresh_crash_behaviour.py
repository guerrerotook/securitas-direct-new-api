"""Client behaviour around the issue #557 xSRefreshLogin 'fr' crash.

The root cause of #557 — a rotated refresh token that was never persisted to
the config entry, so a restart reloaded a stale token — is fixed in the setup
path (``_get_or_create_session`` now attaches the entry to a reused config-flow
hub). These tests characterise the *client-side* handling of a single server
crash, which is independent of that fix: one crash is classified transient
(retryable), not a genuine auth failure, and it leaves the stored refresh token
untouched. Escalation to reauth happens only on a *streak* of crashes (see
RefreshTokenDeadError and the setup-path threshold in __init__); these tests
guard against a lone crash being turned into a reauth trigger or corrupting
the stored token.
"""

from __future__ import annotations

import pytest

from custom_components.securitas.verisure_owa_api.client import VerisureOwaClient
from custom_components.securitas.verisure_owa_api.exceptions import (
    VerisureOwaError,
    is_genuine_auth_failure,
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
    handling of a single crash response must stay safe: it is classified
    transient (so the coordinator retries; only a streak escalates to reauth)
    and it leaves the stored refresh token untouched (so nothing is corrupted).
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
