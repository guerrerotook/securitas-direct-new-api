"""Diagnostics for issue #557 (xSRefreshLogin 'fr' crash on restart).

These tests cover the strategic logging added to tell apart the competing
explanations for the reboot-only failure: a stale/consumed refresh token
loaded from disk vs. a genuinely broken refresh for the account. The signal
is a stable content *fingerprint* of the refresh token (the raw value is
redacted by SensitiveDataFilter, so every generation would otherwise look
identical in logs) plus the request context at the failing call.
"""

from __future__ import annotations

import hashlib
import logging
import re

import pytest

from custom_components.securitas.verisure_owa_api.client import VerisureOwaClient
from custom_components.securitas.verisure_owa_api.client._base import (
    _token_fingerprint,
)
from custom_components.securitas.verisure_owa_api.exceptions import (
    VerisureOwaError,
    is_genuine_auth_failure,
)

from .conftest import refresh_response

_AUTH_LOGGER = "custom_components.securitas.verisure_owa_api.client._auth"
_BASE_LOGGER = "custom_components.securitas.verisure_owa_api.client._base"


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


class TestTokenFingerprint:
    def test_is_stable_content_hash(self) -> None:
        """Same token -> same fingerprint, computed as a sha256 prefix.

        Stability as a pure content hash is the whole point: the fingerprint
        persisted before a restart must equal the one computed after it, so we
        can tell whether the token loaded from disk is the last one rotated.
        """
        token = "some-refresh-token-value"
        expected = hashlib.sha256(token.encode()).hexdigest()[:12]

        assert _token_fingerprint(token) == expected

    def test_distinguishes_different_tokens(self) -> None:
        """Different tokens -> different fingerprints (so generations differ)."""
        assert _token_fingerprint("token-a") != _token_fingerprint("token-b")

    def test_does_not_leak_the_raw_token(self) -> None:
        """The fingerprint must not contain the raw token (safe to log)."""
        token = "super-secret-refresh-token"
        fp = _token_fingerprint(token)

        assert token not in fp
        assert len(fp) < len(token)

    def test_empty_and_none_use_a_sentinel(self) -> None:
        """Falsy tokens fingerprint to a sentinel instead of crashing."""
        assert _token_fingerprint("") == "<none>"
        assert _token_fingerprint(None) == "<none>"


class TestRefreshAttemptDiagnostics:
    async def test_logs_fingerprint_and_startup_context_on_the_crash(
        self, mock_transport, caplog
    ) -> None:
        """The #557 crash still emits a diagnostic pinning fingerprint + context.

        The diagnostic must be logged *before* the request, so it survives the
        server crash — that is the only line that ties the failing generation
        to the reboot (no prior auth token) rather than a steady-state renewal.
        """
        mock_transport.execute.return_value = FR_CRASH_RESPONSE
        client = _make_client(mock_transport, refresh_token="on-disk-refresh-token")
        # Fresh process after a reboot: no in-memory auth token yet.
        assert client.authentication_token is None

        with (
            caplog.at_level(logging.DEBUG, logger=_AUTH_LOGGER),
            pytest.raises(VerisureOwaError),
        ):
            await client.refresh_token()

        fp = _token_fingerprint("on-disk-refresh-token")
        assert f"token_fp={fp}" in caplog.text
        assert "had_prior_auth=False" in caplog.text

    async def test_does_not_leak_the_raw_refresh_token(
        self, mock_transport, caplog
    ) -> None:
        """The raw refresh token must never reach the diagnostic log line."""
        mock_transport.execute.return_value = FR_CRASH_RESPONSE
        secret = "super-secret-on-disk-refresh-token"
        client = _make_client(mock_transport, refresh_token=secret)

        with (
            caplog.at_level(logging.DEBUG, logger=_AUTH_LOGGER),
            pytest.raises(VerisureOwaError),
        ):
            await client.refresh_token()

        assert secret not in caplog.text

    async def test_distinguishes_steady_state_renewal_from_startup(
        self, mock_transport, caplog
    ) -> None:
        """A renewal with a live auth token logs had_prior_auth=True.

        This flag is the startup-vs-steady discriminator: only the reboot path
        reaches refresh with no prior auth token, so a crash tagged
        had_prior_auth=False localises the failure to startup.
        """
        mock_transport.execute.return_value = FR_CRASH_RESPONSE
        client = _make_client(mock_transport, refresh_token="on-disk-refresh-token")
        client.authentication_token = "a-live-though-near-expiry-token"

        with (
            caplog.at_level(logging.DEBUG, logger=_AUTH_LOGGER),
            pytest.raises(VerisureOwaError),
        ):
            await client.refresh_token()

        assert "had_prior_auth=True" in caplog.text


class TestRotationDiagnostics:
    async def test_logs_new_token_fingerprint_on_rotation(
        self, mock_transport, caplog
    ) -> None:
        """A rotated refresh token logs its fingerprint.

        This is the other half of the cross-restart timeline: the last
        ``rotated_fp`` persisted before a shutdown is what the next boot's
        ``token_fp`` should match — a mismatch proves a stale token was loaded.
        """
        new_refresh = "rotated-refresh-token"
        mock_transport.execute.return_value = refresh_response(
            refresh_token=new_refresh
        )
        client = _make_client(mock_transport, refresh_token="old-refresh-token")

        with caplog.at_level(logging.DEBUG, logger=_BASE_LOGGER):
            ok = await client.refresh_token()

        assert ok is True
        assert f"rotated_fp={_token_fingerprint(new_refresh)}" in caplog.text

    async def test_rotation_log_does_not_leak_new_token(
        self, mock_transport, caplog
    ) -> None:
        """The raw rotated token must never reach the log line."""
        new_refresh = "super-secret-rotated-token"
        mock_transport.execute.return_value = refresh_response(
            refresh_token=new_refresh
        )
        client = _make_client(mock_transport, refresh_token="old-refresh-token")

        with caplog.at_level(logging.DEBUG, logger=_BASE_LOGGER):
            await client.refresh_token()

        assert new_refresh not in caplog.text


class TestAuthTokenLifetimeDiagnostics:
    async def test_logs_measured_auth_token_ttl_on_success(
        self, mock_transport, caplog
    ) -> None:
        """A minted auth token logs its real remaining lifetime.

        We have only *inferred* the ~15-minute JWT life from test fixtures; this
        line measures it on the reporter's own account. If the real value were
        hours, the "reboot only forces the refresh we'd otherwise rarely hit"
        reasoning would need revisiting — so it is worth confirming, not assuming.
        """
        mock_transport.execute.return_value = refresh_response(
            refresh_token="rotated-refresh-token"
        )
        client = _make_client(mock_transport, refresh_token="old-refresh-token")

        with caplog.at_level(logging.DEBUG, logger=_BASE_LOGGER):
            ok = await client.refresh_token()

        assert ok is True
        match = re.search(r"auth_token_ttl_s=(\d+)", caplog.text)
        assert match is not None
        ttl = int(match.group(1))
        # refresh_response defaults its hash to a 15-minute JWT (~900s), with
        # clock-skew slack for the test's own runtime.
        assert 840 <= ttl <= 905


# A genuine token rejection (err 60067 "Invalid Session"): NOT the server
# crash. Used to prove the recruitment warning is specific to the #568 crash
# and does not fire for a token the server has simply invalidated.
INVALID_SESSION_RESPONSE = {
    "errors": [
        {
            "message": "Invalid Session",
            "path": ["xSRefreshLogin"],
            "data": {"err": "60067"},
        }
    ],
    "data": {"xSRefreshLogin": None},
}


class TestRefreshCrashRecruitmentWarning:
    """A once-per-client WARNING recruits affected users to the #568 issue.

    The fingerprint diagnostics above are DEBUG and off by default, so only
    users who already know to enable them ever surface in the issue. This
    surfaces the *specific* xSRefreshLogin server crash at WARNING for every
    affected user, with the exact steps to capture the DEBUG data we still
    need — without moving the noisy per-rotation lines (~every 15 min) off
    DEBUG and spamming every healthy installation.
    """

    async def test_crash_logs_a_warning_naming_the_issue_and_next_steps(
        self, mock_transport, caplog
    ) -> None:
        """The crash emits a WARNING naming issue #568 and how to help."""
        mock_transport.execute.return_value = FR_CRASH_RESPONSE
        client = _make_client(mock_transport, refresh_token="on-disk-refresh-token")

        with (
            caplog.at_level(logging.WARNING, logger=_BASE_LOGGER),
            pytest.raises(VerisureOwaError),
        ):
            await client.refresh_token()

        # Names the issue so a reporter can find and follow it,
        assert "#568" in caplog.text
        # and tells them exactly what to enable to capture the DEBUG data.
        assert "custom_components.securitas" in caplog.text

    async def test_warning_fires_only_once_per_client(
        self, mock_transport, caplog
    ) -> None:
        """A retry loop against a persistent crash logs the recruit line once.

        The coordinator retries the failing refresh every poll; the recruitment
        WARNING must not repeat on each retry or it becomes the very log spam it
        was designed to avoid.
        """
        mock_transport.execute.return_value = FR_CRASH_RESPONSE
        client = _make_client(mock_transport, refresh_token="on-disk-refresh-token")

        with caplog.at_level(logging.WARNING, logger=_BASE_LOGGER):
            for _ in range(3):
                with pytest.raises(VerisureOwaError):
                    await client.refresh_token()

        recruitment = [r for r in caplog.records if "#568" in r.getMessage()]
        assert len(recruitment) == 1

    async def test_genuine_token_rejection_does_not_recruit(
        self, mock_transport, caplog
    ) -> None:
        """An invalidated token (err 60067) is not the crash — no recruit line.

        Recruiting is specific to the server-side resolver crash. A genuinely
        rejected token is a different failure (it leads to reauth), and pointing
        those users at the crash issue would only add noise there.
        """
        mock_transport.execute.return_value = INVALID_SESSION_RESPONSE
        client = _make_client(mock_transport, refresh_token="on-disk-refresh-token")

        with (
            caplog.at_level(logging.WARNING, logger=_BASE_LOGGER),
            pytest.raises(VerisureOwaError),
        ):
            await client.refresh_token()

        assert "#568" not in caplog.text


class TestRefreshCrashIsAnUnrecoverableTrap:
    """Characterisation of *existing* behaviour (these pass as-is).

    They pin down why the reporter must delete the entry: the #557 crash is
    classified transient AND leaves the on-disk token untouched, so every retry
    re-presents the exact same token and hits the exact same crash forever.
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
