"""Tests for connecting over IPv4 first, with a fallback (issue #606).

The reasoning lives with the code, in `_login_ipv4_first` and
`_never_reached_the_server` — briefly, Verisure has no IPv6 address in any
supported country, so asking for one can only ever come back empty, and on some
resolvers that empty answer fails the whole lookup.

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


def _transport_error(cause):
    """Build the error the transport raises, with its cause attached as it does.

    `http_transport` wraps whatever aiohttp raised with `raise ... from err`, and
    that original is what says whether the request ever left this machine.
    """
    try:
        raise cause
    except Exception as err:
        try:
            raise APIConnectionError("Connection error with URL x") from err
        except APIConnectionError as wrapped:
            return wrapped


def _could_not_connect():
    """A DNS or TCP failure: nothing was delivered to Verisure."""
    return _transport_error(
        aiohttp.ClientConnectorDNSError(
            MagicMock(), OSError(None, "DNS server returned answer with no data")
        )
    )


def _timed_out():
    """A read timeout: the request was sent and may still be in flight."""
    return _transport_error(aiohttp.SocketTimeoutError("timed out reading"))


def _connect_timed_out():
    """A connect timeout: the connection was never established, so nothing was sent."""
    return _transport_error(aiohttp.ConnectionTimeoutError("timed out connecting"))


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
        """The first login goes out on the IPv4-only client, with no opt-in."""
        used = await self._run_setup(hass, login_effects=[None])

        assert used == [_ipv4_session(hass)]
        assert used[0].connector._family == socket.AF_INET

    async def test_a_network_failure_falls_back_to_both_families(self, hass):
        """No IPv4 route: retry once on the client that also asks for IPv6."""
        used = await self._run_setup(hass, login_effects=[_could_not_connect(), None])

        assert len(used) == 2, "expected a fallback attempt"
        assert used[0] is _ipv4_session(hass)
        assert used[1] is async_get_clientsession(hass)
        assert used[1].connector._family == socket.AF_UNSPEC

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


class TestHomeAssistantsClientsAreLeftAlone:
    """Neither client is ours, so unloading must not close or detach one.

    Both come from `async_get_clientsession`, which hands the same object to
    every caller in the instance and closes it itself at shutdown. Closing one
    here would break every other integration using that address family, and the
    breakage would show up far from this code.
    """

    async def test_unloading_leaves_both_clients_usable(self, hass):
        """After a full load-and-unload cycle, both are still open and attached."""
        from custom_components.securitas import async_unload_entry
        from tests.conftest import make_config_entry_data, make_securitas_hub_mock

        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        ipv4 = _ipv4_session(hass)
        shared = async_get_clientsession(hass)

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["sessions"] = {
            entry.data["username"]: {"hub": make_securitas_hub_mock(), "ref_count": 1}
        }
        hass.data[DOMAIN][entry.entry_id] = {"hub": make_securitas_hub_mock()}

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
