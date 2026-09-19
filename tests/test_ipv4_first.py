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

import asyncio
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
    """A timeout: the request may have arrived and still be in flight."""
    return _transport_error(aiohttp.ServerTimeoutError("timed out"))


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

    async def test_a_working_connection_is_never_retried(self, hass):
        """A successful IPv4 login is the whole story — no second attempt."""
        used = await self._run_setup(hass, login_effects=[None])

        assert len(used) == 1

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

    async def test_both_clients_belong_to_home_assistant(self, hass):
        """Nothing here is owned, so nothing is ever detached or closed."""
        used = await self._run_setup(hass, login_effects=[_could_not_connect(), None])

        # Still attached and usable after setup — Home Assistant closes them.
        for session in used:
            assert session.connector is not None
            assert not session.closed


class TestNoUserFacingOption:
    """The address family is not something a user has to diagnose or configure."""

    def test_the_force_ipv4_option_is_gone(self):
        """No constant survives, so no settings screen can offer the toggle."""
        from custom_components.securitas import const

        leftovers = [n for n in dir(const) if "FORCE_IPV4" in n]
        assert leftovers == [], f"option constants still present: {leftovers}"

    async def test_the_advanced_section_does_not_offer_it(self, hass):
        """The options screen has no address-family control of any kind."""
        from custom_components.securitas.config_flow import _build_settings_schema

        rendered = str(_build_settings_schema({}, []))

        assert "force_ipv4" not in rendered


class TestSetupFailureReleasesItsReference:
    """A setup that fails after taking a reference must give it back.

    Home Assistant does not call `async_unload_entry` when setup raises
    `ConfigEntryNotReady`, so a reference left behind here is never returned:
    the retry takes the reuse branch and increments the count again, and it
    never falls back to zero.
    """

    async def _failed_setup(self, hass, *, fetch_raises, surfaces_as):
        from custom_components.securitas import async_setup_entry
        from tests.conftest import make_config_entry_data, make_securitas_hub_mock

        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        hub_cls = MagicMock(return_value=make_securitas_hub_mock())
        hub_cls.__name__ = "VerisureHub"

        with (
            patch("custom_components.securitas.VerisureHub", hub_cls),
            patch(
                "custom_components.securitas._fetch_and_cache_installations",
                new=AsyncMock(side_effect=fetch_raises),
            ),
            pytest.raises(surfaces_as),
        ):
            await async_setup_entry(hass, entry)

        return hass.data[DOMAIN].get("sessions", {})

    async def test_a_cancelled_fetch_releases_the_reference(self, hass):
        """Cancellation is a failure like any other — it must not hold the seat.

        A restart or a config-entry reload cancels setup mid-flight, which is
        exactly when this is easiest to hit.
        """
        sessions = await self._failed_setup(
            hass,
            fetch_raises=asyncio.CancelledError(),
            surfaces_as=asyncio.CancelledError,
        )

        assert sessions == {}, "a cancelled setup kept its session reference"

    async def test_two_failed_attempts_do_not_stack_references(self, hass):
        """The count a successful setup later sees must not have been inflated."""
        from custom_components.securitas.verisure_owa_api.exceptions import (
            VerisureOwaError,
        )

        for _ in range(2):
            sessions = await self._failed_setup(
                hass,
                fetch_raises=VerisureOwaError("boom"),
                surfaces_as=ConfigEntryNotReady,
            )

        assert sessions == {}, f"references stacked up across retries: {sessions}"
