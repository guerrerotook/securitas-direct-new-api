"""Tests for connecting over IPv4 first, with a fallback (issue #606).

Verisure's customer endpoint publishes no IPv6 address in any country this
integration supports — all ten are CNAMEs into the same Imperva edge, and none
of them answers an AAAA query. So the IPv6 half of the combined lookup that
aiohttp issues by default can only ever come back empty here, and on some
networks that empty answer fails the whole lookup instead of falling back to the
IPv4 address that resolved fine. The alarm then sits at unavailable.

Asking for IPv4 only skips a question that has no useful answer. The fallback is
for the opposite network: a host with no IPv4 route of its own, which reaches
IPv4-only servers through NAT64/DNS64 and therefore needs the IPv6 answer its
resolver synthesises. A network-level failure on the IPv4 attempt is retried
once on Home Assistant's default client, which asks for both.

Neither client is ours: Home Assistant caches one per address family and closes
them at shutdown, so nothing here is ever detached.
"""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.securitas import DOMAIN, _never_reached_the_server
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

    async def _run_login(
        self, hass, *, login_effects, raises=None, hubs_out=None, register_first=False
    ):
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
            if hubs_out is not None:
                hubs_out.append(hub)
            if register_first and len(sessions_used) == 1:
                # Model async_step_user's reuse branch: this account already has
                # a shared hub registered, and it is the one the flow is using.
                hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})["alice"] = {
                    "hub": hub,
                    "ref_count": 1,
                }
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

    async def test_the_fallback_updates_a_registered_hub(self, hass):
        """A shared hub the flow replaces must be replaced in the registry too.

        Entries for one account share a hub by username. If the flow falls back
        and leaves the old hub registered, a later setup reuses a hub that was
        never signed in.
        """
        hubs = []

        await self._run_login(
            hass,
            login_effects=[_could_not_connect(), None],
            hubs_out=hubs,
            register_first=True,
        )

        registered = hass.data[DOMAIN]["sessions"]["alice"]["hub"]
        assert registered is not hubs[0], "the registry still holds the replaced hub"
        assert registered is hubs[1]


class TestTheGateMatchesWhatTheTransportRaises:
    """The fallback reads `__cause__`, so the transport has to keep setting it.

    `http_transport` wraps aiohttp's error with `raise ... from err`. Drop that
    `from err` and every other test in this file still passes while the fallback
    silently stops working, because the cause it inspects would be gone.
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

    async def test_a_connector_error_survives_as_the_cause(self, hass):
        """An unreachable host reaches the gate as something it recognises."""
        cause = aiohttp.ClientConnectorError(MagicMock(), OSError(51, "unreachable"))

        err = await self._execute_against(cause)

        assert err.__cause__ is cause
        assert _never_reached_the_server(err) is True

    async def test_a_read_timeout_survives_as_the_cause(self, hass):
        """And a sent-but-slow request reaches it as something it refuses."""
        cause = aiohttp.SocketTimeoutError("timed out reading")

        err = await self._execute_against(cause)

        assert err.__cause__ is cause
        assert _never_reached_the_server(err) is False


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
