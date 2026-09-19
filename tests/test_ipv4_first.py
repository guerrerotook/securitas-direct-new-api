"""Tests for connecting over IPv4 first, with a fallback (issue #606).

The reasoning lives with the code, in `_login_ipv4_then_any` — briefly, Verisure
has no IPv6 address in any supported country, so asking for one can only ever
come back empty, and on some resolvers that empty answer fails the whole lookup.
Whether a failure may be retried is decided once, in the transport, which sets
`APIConnectionError.connection_never_established`; the fallback only reads it.

Unlike the other setup tests in this suite, these deliberately do NOT patch
`async_get_clientsession`: which client each attempt was handed is the thing
under test, so the assertions compare against Home Assistant's real per-family
sessions. Copy the sibling pattern in `tests/test_init.py` for anything else.
"""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.securitas import DOMAIN
from custom_components.securitas.verisure_owa_api.exceptions import (
    APIConnectionError,
    AuthenticationError,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let the config-flow tests below load this custom integration."""
    yield


def _ipv4_session(hass):
    """Home Assistant's own client for IPv4-only lookups."""
    return async_get_clientsession(hass, family=socket.AF_INET)


def _could_not_connect():
    """A DNS or TCP failure: the connection was never established.

    The transport tags this ``connection_never_established=True`` (see
    ``TestTheTransportClassifiesConnectionFailures`` for that mapping); here we
    build the already-classified error the fallback actually receives.
    """
    return APIConnectionError(
        "Connection error with URL x", connection_never_established=True
    )


def _timed_out():
    """A read timeout: the request was sent and may still be in flight."""
    return APIConnectionError(
        "Connection error with URL x", connection_never_established=False
    )


def _connect_timed_out():
    """A connect timeout: the connection never opened, so nothing was sent.

    Identical to _could_not_connect once the error reaches the fallback — both
    are already tagged connection_never_established=True. The aiohttp-class
    distinction between them (a DNS/TCP failure vs a connect timeout) is what the
    transport classifies, and that mapping is tested in
    TestTheTransportClassifiesConnectionFailures, not here.
    """
    return _could_not_connect()


class TestSetupPrefersIpv4:
    """Setup connects over IPv4 first, and falls back only when the network fails."""

    async def _run_setup(self, hass, *, login_effects):
        """Drive `async_setup_entry`, returning the client each login attempt used.

        `login_effects` is one entry per attempt: None to succeed, or an
        exception to raise. Setup is stopped at the first post-login network
        call, which is past everything under test.
        """
        from custom_components.securitas import async_setup_entry
        from custom_components.securitas.verisure_owa_api.exceptions import (
            VerisureOwaError,
        )
        from tests.conftest import make_config_entry_data, make_securitas_hub_mock

        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        sessions_used = []
        effects = list(login_effects)

        def _build_hub(config, config_entry, http_session, hass_):
            sessions_used.append(http_session)
            hub = make_securitas_hub_mock()
            # Tag the hub with the client it was built on, so a test can tell
            # which hub was kept for reuse after a fallback, not just which
            # clients were tried.
            hub._test_session = http_session
            effect = effects.pop(0) if effects else None

            async def _login():
                if effect is not None:
                    raise effect

            hub.login = AsyncMock(side_effect=_login)
            return hub

        hub_cls = MagicMock(side_effect=_build_hub)
        hub_cls.__name__ = "VerisureHub"

        with (
            patch("custom_components.securitas.VerisureHub", hub_cls),
            patch(
                "custom_components.securitas._fetch_and_cache_installations",
                new=AsyncMock(side_effect=VerisureOwaError("stop here")),
            ),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

        return sessions_used

    async def test_first_attempt_asks_for_ipv4_only(self, hass):
        """The first login goes out on the IPv4-only client."""
        used = await self._run_setup(hass, login_effects=[None])

        # async_get_clientsession returns a per-family singleton, so identity
        # with the AF_INET session is proof of the address family — no need to
        # read aiohttp's private connector._family.
        assert used == [_ipv4_session(hass)]

    async def test_a_network_failure_falls_back_to_both_families(self, hass):
        """No IPv4 route: retry once on the client that also asks for IPv6."""
        used = await self._run_setup(hass, login_effects=[_could_not_connect(), None])

        assert len(used) == 2, "expected a fallback attempt"
        assert used[0] is _ipv4_session(hass)
        # The default (AF_UNSPEC) session is again identified by identity, not by
        # reaching into the connector's private address-family field.
        assert used[1] is async_get_clientsession(hass)

    async def test_the_fallback_hub_is_the_one_kept_for_reuse(self, hass):
        """After a fallback the session registered for reuse is the AF_UNSPEC hub.

        Returning the first (IPv4-only) hub would strand every future entry for
        this account on the family that could not connect (issue #606).
        """
        await self._run_setup(hass, login_effects=[_could_not_connect(), None])

        sessions = hass.data[DOMAIN]["sessions"]
        (registered,) = sessions.values()
        assert registered["hub"]._test_session is async_get_clientsession(hass), (
            "the kept hub must be the AF_UNSPEC fallback, not the IPv4 attempt"
        )

    async def test_a_timeout_is_not_retried(self, hass):
        """A slow server is not a wrong address family.

        The request may already have arrived, and this integration deliberately
        does not resend a sign-in to a busy server — resending can end the
        session instead of recovering it. Only a failure that proves nothing was
        delivered earns a second attempt.
        """
        used = await self._run_setup(hass, login_effects=[_timed_out(), None])

        assert len(used) == 1, "a timeout must not trigger a second sign-in"

    async def test_a_connect_timeout_does_fall_back(self, hass):
        """A connection that never opened sent nothing, so retrying is free.

        This is the IPv6-only host whose IPv4 packets are dropped rather than
        refused: it never gets ENETUNREACH, just silence. Without this it would
        never reach the fallback and could never set the integration up.
        """
        used = await self._run_setup(hass, login_effects=[_connect_timed_out(), None])

        assert len(used) == 2, "a connect timeout should reach the fallback"
        assert used[1] is async_get_clientsession(hass)

    async def test_a_rejected_password_is_not_retried(self, hass):
        """Only network failures fall back; bad credentials fail once, as before."""
        from homeassistant.exceptions import ConfigEntryAuthFailed

        from custom_components.securitas import async_setup_entry
        from tests.conftest import make_config_entry_data, make_securitas_hub_mock

        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        attempts = []

        def _build_hub(config, config_entry, http_session, hass_):
            attempts.append(http_session)
            hub = make_securitas_hub_mock()
            hub.login = AsyncMock(side_effect=AuthenticationError("wrong password"))
            return hub

        hub_cls = MagicMock(side_effect=_build_hub)
        hub_cls.__name__ = "VerisureHub"

        with (
            patch("custom_components.securitas.VerisureHub", hub_cls),
            patch("custom_components.securitas._notify"),
            pytest.raises(ConfigEntryAuthFailed),
        ):
            await async_setup_entry(hass, entry)

        assert len(attempts) == 1, "a credential rejection must not be retried"


class TestConfigFlowPrefersIpv4:
    """The config flow connects the same way setup does.

    This is the half that has to work for someone installing fresh on an
    affected network: signing in is what stands between them and having an
    entry at all, so there is no later screen that could offer them a choice.
    """

    async def _run_login(self, hass, *, login_effects, raises=None):
        """Drive the flow's login, returning the client each attempt used."""
        from custom_components.securitas.config_flow import FlowHandler

        handler = FlowHandler()
        handler.hass = hass
        handler.config = {"username": "alice", "password": "secret"}

        sessions_used = []
        effects = list(login_effects)

        def _build_hub(config, config_entry, http_session, hass_):
            sessions_used.append(http_session)
            hub = MagicMock()
            hub._test_session = http_session
            effect = effects.pop(0) if effects else None

            async def _login():
                if effect is not None:
                    raise effect

            hub.login = AsyncMock(side_effect=_login)
            return hub

        hub_cls = MagicMock(side_effect=_build_hub)
        hub_cls.__name__ = "VerisureHub"

        with patch("custom_components.securitas.config_flow.VerisureHub", hub_cls):
            handler._create_client()
            if raises is not None:
                with pytest.raises(raises):
                    await handler._login_with_family_fallback()
            else:
                await handler._login_with_family_fallback()

        self._handler = handler
        return sessions_used

    async def test_first_attempt_asks_for_ipv4_only(self, hass):
        """Signing in from the flow skips the lookup that was failing."""
        used = await self._run_login(hass, login_effects=[None])

        assert used == [_ipv4_session(hass)]

    async def test_an_unreachable_server_falls_back_to_both_families(self, hass):
        """An IPv6-only host can still complete setup."""
        used = await self._run_login(hass, login_effects=[_could_not_connect(), None])

        assert len(used) == 2, "expected a fallback attempt"
        assert used[1] is async_get_clientsession(hass)

    async def test_a_timeout_does_not_resend_the_sign_in(self, hass):
        """A slow server must not turn one sign-in into two.

        The request may already have arrived and been acted on — a second
        sign-in can invalidate the first, and on a 2FA account it means a
        second code for a challenge the user can no longer answer. Setup
        refuses this; the flow has to refuse it too.
        """
        used = await self._run_login(
            hass, login_effects=[_timed_out(), None], raises=APIConnectionError
        )

        assert len(used) == 1, "a timeout must not trigger a second sign-in"

    async def test_the_fallback_hub_becomes_the_flows_hub(self, hass):
        """After a fallback the flow carries the AF_UNSPEC hub forward.

        finish_setup/reauth act on ``self.hub`` after this returns; if it were
        left pointing at the IPv4 attempt that could not connect, the rest of
        the flow would run against a dead hub.
        """
        await self._run_login(hass, login_effects=[_could_not_connect(), None])

        assert self._handler.hub._test_session is async_get_clientsession(hass)


class TestConfigFlowDoesNotSwapABorrowedHub:
    """A hub borrowed from a running session is shared with the live entries.

    The IPv4 fallback rebuilds by making a fresh hub and signing it in with the
    password — the very login ``async_step_user`` reuses the session to avoid.
    So when the hub is borrowed rather than built by this flow, a connection
    failure must propagate untouched: no new hub, no second sign-in, and the
    shared hub left in place for its owners. Rebuilding it would wire the new
    entry to a hub the running entries never see, and lose its rotated token
    (issue #606, on top of the session reuse from issue #557).
    """

    async def test_a_borrowed_hub_is_not_rebuilt_on_a_connect_failure(self, hass):
        """Owning nothing, the flow lets the connection error surface as-is."""
        from custom_components.securitas.config_flow import FlowHandler

        handler = FlowHandler()
        handler.hass = hass
        handler.config = {"username": "alice", "password": "secret"}

        # Stand in for the shared, running hub that async_step_user borrows.
        borrowed = MagicMock()
        borrowed.login = AsyncMock(side_effect=_could_not_connect())
        handler.hub = borrowed
        handler._owns_hub = False

        built: list[int] = []
        hub_cls = MagicMock(side_effect=lambda *a, **k: built.append(1))
        hub_cls.__name__ = "VerisureHub"

        with (
            patch("custom_components.securitas.config_flow.VerisureHub", hub_cls),
            pytest.raises(APIConnectionError),
        ):
            await handler._login_with_family_fallback()

        assert built == [], "a borrowed hub must not be rebuilt on the fallback"
        assert handler.hub is borrowed, "the shared hub must be left in place"
        assert borrowed.login.await_count == 1, "no second sign-in on the shared hub"


class TestConfigFlowReauthFallsBack:
    """Reauth reaches the fallback the same way a fresh install does.

    Reauth always builds its own hub, so it owns it and may rebuild it. This
    drives the real ``async_step_reauth_confirm`` and checks the hub that reaches
    ``_finish_reauth`` after a fallback is the AF_UNSPEC one, not the IPv4 attempt.
    """

    async def test_reauth_confirm_carries_the_fallback_hub_forward(self, hass):
        from custom_components.securitas.config_flow import FlowHandler
        from tests.conftest import make_config_entry_data

        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        handler = FlowHandler()
        handler.hass = hass
        handler._reauth_entry = entry
        handler.config = {}

        effects = [_could_not_connect(), None]

        def _build_hub(config, config_entry, http_session, hass_):
            hub = MagicMock()
            hub._test_session = http_session
            effect = effects.pop(0) if effects else None

            async def _login():
                if effect is not None:
                    raise effect

            hub.login = AsyncMock(side_effect=_login)
            return hub

        hub_cls = MagicMock(side_effect=_build_hub)
        hub_cls.__name__ = "VerisureHub"

        captured = {}

        async def _capture():
            captured["hub"] = handler.hub
            return handler.async_abort(reason="reauth_successful")

        with (
            patch("custom_components.securitas.config_flow.VerisureHub", hub_cls),
            patch.object(handler, "_finish_reauth", new=_capture),
        ):
            await handler.async_step_reauth_confirm(
                {"username": "alice", "password": "secret"}
            )

        assert captured["hub"]._test_session is async_get_clientsession(hass), (
            "reauth must finish on the AF_UNSPEC fallback hub"
        )


class TestHomeAssistantsClientsAreLeftAlone:
    """Neither client is ours, so unloading must not close or detach one.

    Both come from `async_get_clientsession`, which hands the same object to
    every caller in the instance and closes it itself at shutdown. Closing one
    here would break every other integration using that address family, and the
    breakage would show up far from this code.
    """

    async def test_unloading_leaves_both_clients_usable(self, hass):
        """After a full load-and-unload cycle, both are still open and attached."""
        from custom_components.securitas import (
            VerisureHub,
            _build_config_dict,
            async_unload_entry,
        )
        from tests.conftest import make_config_entry_data

        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        ipv4 = _ipv4_session(hass)
        shared = async_get_clientsession(hass)

        # A real hub, holding the real client, so that releasing the session the
        # unload code actually has in hand is visible here — a mock hub would
        # swallow that and leave this test able to pass against it.
        config, _ = _build_config_dict(entry)
        hub = VerisureHub(config, entry, ipv4, hass)
        assert hub.client._transport._session is ipv4

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["sessions"] = {
            entry.data["username"]: {"hub": hub, "ref_count": 1}
        }
        hass.data[DOMAIN][entry.entry_id] = {"hub": hub}

        with (
            patch.object(
                hass.config_entries,
                "async_unload_platforms",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "custom_components.securitas._unregister_card_resource", new=AsyncMock()
            ),
        ):
            assert await async_unload_entry(hass, entry) is True

        for name, session in (("IPv4-only", ipv4), ("default", shared)):
            assert not session.closed, f"the {name} client was closed"
            assert session.connector is not None, f"the {name} client was detached"


class TestTheTransportClassifiesConnectionFailures:
    """The transport is the one layer that still holds aiohttp's own error, so
    it decides whether the connection ever opened and tags the APIConnectionError
    it raises. The fallback then only reads that flag — this is where the
    aiohttp-class-to-flag mapping is pinned, so a change to it fails here rather
    than silently disabling the fallback with every fallback test still green.
    """

    async def _execute_against(self, error):
        """Run the real transport against a session whose POST raises `error`."""
        from custom_components.securitas.verisure_owa_api.http_transport import (
            HttpTransport,
        )

        session = MagicMock()
        session.post = MagicMock(side_effect=error)
        transport = HttpTransport(session, "https://example.invalid/graphql")

        with pytest.raises(APIConnectionError) as caught:
            await transport.execute({"operationName": "x"}, {})
        return caught.value

    async def test_a_connector_error_is_tagged_never_established(self, hass):
        """An unreachable host never opened the socket, so nothing was sent."""
        cause = aiohttp.ClientConnectorError(MagicMock(), OSError(51, "unreachable"))

        err = await self._execute_against(cause)

        assert err.connection_never_established is True

    async def test_a_connect_timeout_is_tagged_never_established(self, hass):
        """A connect timeout is silence before the socket opened — safe to retry."""
        cause = aiohttp.ConnectionTimeoutError("timed out connecting")

        err = await self._execute_against(cause)

        assert err.connection_never_established is True

    async def test_a_read_timeout_is_not_tagged_never_established(self, hass):
        """A sent-but-slow request may have arrived; it must not be retried."""
        cause = aiohttp.SocketTimeoutError("timed out reading")

        err = await self._execute_against(cause)

        assert err.connection_never_established is False


class TestBothFamiliesFailing:
    """When neither family works, the user gets one clear failure, not two."""

    async def test_a_second_failure_reports_once(self, hass, caplog):
        """The retried first attempt stays silent; only the real failure speaks."""
        from custom_components.securitas import async_setup_entry
        from tests.conftest import make_config_entry_data, make_securitas_hub_mock

        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        def _build_hub(config, config_entry, http_session, hass_):
            hub = make_securitas_hub_mock()
            hub.login = AsyncMock(side_effect=_could_not_connect())
            return hub

        hub_cls = MagicMock(side_effect=_build_hub)
        hub_cls.__name__ = "VerisureHub"

        with (
            patch("custom_components.securitas.VerisureHub", hub_cls),
            caplog.at_level("ERROR", logger="custom_components.securitas"),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

        connect_errors = [
            r
            for r in caplog.records
            if r.levelname == "ERROR" and "Unable to connect" in r.getMessage()
        ]
        assert len(connect_errors) == 1, (
            f"expected one error for a failure, got {len(connect_errors)}"
        )
