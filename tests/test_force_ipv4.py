"""Tests for the optional IPv4-only HTTP session (issue #606).

Some networks cannot satisfy the combined IPv4+IPv6 lookup that aiohttp
issues by default: the Verisure endpoint publishes no IPv6 address, and a
resolver that treats the empty IPv6 half as a hard failure never falls back
to the working IPv4 answer. The ``force_ipv4`` option lets an affected user
switch this integration's requests to an IPv4-only lookup, which never asks
the IPv6 question in the first place.
"""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.securitas import (
    CONF_FORCE_IPV4,
    DEFAULT_FORCE_IPV4,
    DOMAIN,
    _build_http_session,
    _release_shared_session,
    async_unload_entry,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let the config-flow tests below load this custom integration."""
    yield


class TestBuildHttpSession:
    """`_build_http_session` picks the connection strategy from the option."""

    def test_default_is_off(self):
        """The option ships disabled so behaviour is unchanged out of the box."""
        assert DEFAULT_FORCE_IPV4 is False

    async def test_off_reuses_home_assistant_shared_session(self, hass):
        """With the option off we borrow HA's shared client, and don't own it."""
        session, owned = _build_http_session(hass, force_ipv4=False)

        assert session is async_get_clientsession(hass)
        assert owned is False

    async def test_on_builds_an_owned_ipv4_only_session(self, hass):
        """With the option on we build our own client that only looks up IPv4."""
        session, owned = _build_http_session(hass, force_ipv4=True)

        try:
            assert owned is True
            assert session is not async_get_clientsession(hass)
            # The connector is what carries the address-family restriction.
            assert session.connector._family == socket.AF_INET
        finally:
            # Built with auto_cleanup off, so the owner releases it with
            # detach(), never close() (which HA's helper guards against).
            session.detach()


class TestReleaseSharedSession:
    """Releasing the last reference hands back an owned session to close."""

    def _sessions(self, *, ref_count, owned_session):
        hub = MagicMock()
        # A config_entry that is never the one leaving keeps the survivor path
        # from touching hass.config_entries in these unit tests.
        hub.config_entry = MagicMock()
        return {
            "alice": {
                "hub": hub,
                "ref_count": ref_count,
                "owned_session": owned_session,
            }
        }

    def test_returns_owned_session_when_last_reference_leaves(self, hass):
        """When the session is popped, its owned client is handed back to close."""
        owned = MagicMock()
        sessions = self._sessions(ref_count=1, owned_session=owned)
        leaving = MagicMock()

        returned = _release_shared_session(hass, sessions, "alice", leaving)

        assert returned is owned
        assert "alice" not in sessions

    def test_returns_none_while_references_remain(self, hass):
        """A surviving session must not be closed, so nothing is handed back."""
        owned = MagicMock()
        sessions = self._sessions(ref_count=2, owned_session=owned)
        leaving = MagicMock()

        returned = _release_shared_session(hass, sessions, "alice", leaving)

        assert returned is None
        assert "alice" in sessions

    def test_returns_none_when_shared_session_is_not_owned(self, hass):
        """The default (borrowed) shared client has no owned session to close."""
        sessions = self._sessions(ref_count=1, owned_session=None)
        leaving = MagicMock()

        returned = _release_shared_session(hass, sessions, "alice", leaving)

        assert returned is None


class TestUnloadReleasesOwnedSession:
    """Unloading the entry detaches the owned IPv4 client so reloads don't leak."""

    async def test_unload_detaches_the_owned_session(self, hass):
        """Whatever `_release_shared_session` hands back is detached on unload."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"username": "alice"},
            options={CONF_FORCE_IPV4: True},
        )
        entry.add_to_hass(hass)
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["sessions"] = {
            "alice": {"hub": MagicMock(), "ref_count": 1, "owned_session": None}
        }
        hass.data[DOMAIN][entry.entry_id] = {"hub": MagicMock()}

        owned_session = MagicMock()

        with (
            patch.object(
                hass.config_entries,
                "async_unload_platforms",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "custom_components.securitas._release_shared_session",
                return_value=owned_session,
            ),
            patch(
                "custom_components.securitas._unregister_card_resource",
                new=AsyncMock(),
            ),
        ):
            result = await async_unload_entry(hass, entry)

        assert result is True
        owned_session.detach.assert_called_once()


class TestFailedLoginReleasesOwnedSession:
    """A login failure must not leak the owned client we built for it."""

    async def test_failed_login_detaches_owned_session(self, hass):
        """When login raises, the owned IPv4 client is detached, not left open."""
        from homeassistant.const import CONF_USERNAME

        from custom_components.securitas import _get_or_create_session

        hass.data.setdefault(DOMAIN, {})
        config = {CONF_USERNAME: "alice", CONF_FORCE_IPV4: True}
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_USERNAME: "alice"},
            options={CONF_FORCE_IPV4: True},
        )
        entry.add_to_hass(hass)

        owned_session = MagicMock()

        with (
            patch(
                "custom_components.securitas._build_http_session",
                return_value=(owned_session, True),
            ),
            patch("custom_components.securitas.VerisureHub"),
            patch(
                "custom_components.securitas._login_or_raise",
                new=AsyncMock(side_effect=RuntimeError("login boom")),
            ),
            pytest.raises(RuntimeError, match="login boom"),
        ):
            await _get_or_create_session(hass, config, entry)

        owned_session.detach.assert_called_once()
        assert "alice" not in hass.data[DOMAIN].get("sessions", {})


class TestSetupFailureAfterLoginReleasesOwnedSession:
    """A setup failure AFTER login must release the owned client, not leak it.

    HA does not call async_unload_entry on ConfigEntryNotReady, so a retry
    would otherwise reuse an inflated ref-count and never detach the client.
    """

    async def test_fetch_failure_detaches_owned_session(self, hass):
        """When post-login install fetch fails, the owned client is detached."""
        from homeassistant.const import CONF_USERNAME
        from homeassistant.exceptions import ConfigEntryNotReady

        from custom_components.securitas import async_setup_entry
        from custom_components.securitas.verisure_owa_api.exceptions import (
            VerisureOwaError,
        )
        from tests.conftest import make_config_entry_data, make_securitas_hub_mock

        hub = make_securitas_hub_mock()
        owned_session = MagicMock()

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=make_config_entry_data(),
            options={CONF_FORCE_IPV4: True},
        )
        entry.add_to_hass(hass)

        hub_cls = MagicMock(return_value=hub)
        hub_cls.__name__ = "VerisureHub"

        with (
            patch(
                "custom_components.securitas._build_http_session",
                return_value=(owned_session, True),
            ),
            patch("custom_components.securitas.VerisureHub", hub_cls),
            patch(
                "custom_components.securitas._fetch_and_cache_installations",
                new=AsyncMock(side_effect=VerisureOwaError("boom")),
            ),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(hass, entry)

        owned_session.detach.assert_called_once()
        assert entry.data[CONF_USERNAME] not in hass.data[DOMAIN].get("sessions", {})


REAUTH_DATA = {
    "username": "alice",
    "password": "old-password",
    "country": "ES",
    "instalation": "123456",
    "device_id": "test-device-id",
    "uniqueid": "test-uuid",
    "device_indigitall": "test-indigitall",
}


def _reauth_entry(hass, *, force_ipv4):
    """An entry that already has the IPv4-only option saved (or not)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="alice_123456",
        data=dict(REAUTH_DATA),
        options={CONF_FORCE_IPV4: force_ipv4},
        version=3,
    )
    entry.add_to_hass(hass)
    return entry


async def _run_reauth(hass, entry):
    """Drive the reauth flow to completion.

    Returns the client the hub was given, plus the connector it held while the
    flow was running — the flow detaches its own client on the way out, so the
    address family can only be read from a connector captured at that moment.
    """
    from homeassistant.config_entries import SOURCE_REAUTH

    from tests.conftest import make_securitas_hub_mock

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )

    hub = make_securitas_hub_mock()
    hub.login = AsyncMock()
    hub.get_refresh_token = MagicMock(return_value="fresh-refresh-token")

    captured = {}

    def _build_hub(config, config_entry, http_session, hass_):
        captured["session"] = http_session
        captured["connector"] = http_session.connector
        return hub

    hub_cls = MagicMock(side_effect=_build_hub)
    hub_cls.__name__ = "VerisureHub"

    with (
        patch("custom_components.securitas.config_flow.VerisureHub", hub_cls),
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"username": "alice", "password": "new-password"},
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful", result
    return captured["session"], captured["connector"]


class TestReauthHonoursForceIpv4:
    """Reauth must connect the same way the entry is configured to connect.

    A user turns this option on because the IPv6 lookup fails on their network.
    Reauth is exactly where they land when that failure locks them out, so a
    reauth login on the default dual-stack client would ask the very question
    the option exists to avoid, and the sign-in they were prompted for could
    not succeed.
    """

    async def test_reauth_looks_the_server_up_over_ipv4_only_when_the_option_is_on(
        self, hass
    ):
        """The hub built for reauth gets an IPv4-only client, not the shared one."""
        entry = _reauth_entry(hass, force_ipv4=True)

        session, connector = await _run_reauth(hass, entry)

        assert session is not async_get_clientsession(hass)
        assert connector._family == socket.AF_INET

    async def test_reauth_releases_the_client_it_built(self, hass):
        """The temporary IPv4 client is detached when the flow ends, not leaked."""
        entry = _reauth_entry(hass, force_ipv4=True)

        session, _connector = await _run_reauth(hass, entry)

        # detach() unbinds the connector without closing HA's shared one.
        assert session.connector is None
        # And it releases only its own client: everything else on this
        # Home Assistant still connects through the shared one.
        assert async_get_clientsession(hass).connector is not None

    async def test_reauth_borrows_the_shared_client_when_the_option_is_off(self, hass):
        """The default is unchanged: reauth uses Home Assistant's own client."""
        entry = _reauth_entry(hass, force_ipv4=False)

        session, _connector = await _run_reauth(hass, entry)

        assert session is async_get_clientsession(hass)
        assert session.connector is not None


class TestSavedOptionReachesTheConnection:
    """The saved checkbox must actually change how setup connects.

    The option is read in one place during setup and handed to the client
    builder in another. Nothing else proves that join, so without these the
    checkbox could read as on while every request still went out on the
    default shared resolver.
    """

    async def _session_setup_built(self, hass, *, saved_option):
        """Run setup far enough to see which client the hub was handed.

        Setup is stopped at the first post-login network call, which is the
        earliest point after the client has been chosen; the failure path
        detaches the client, so the connector is captured while it is live.
        """
        from custom_components.securitas import async_setup_entry
        from custom_components.securitas.verisure_owa_api.exceptions import (
            VerisureOwaError,
        )
        from tests.conftest import make_config_entry_data, make_securitas_hub_mock

        options = {} if saved_option is None else {CONF_FORCE_IPV4: saved_option}
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=make_config_entry_data(),
            options=options,
        )
        entry.add_to_hass(hass)

        captured = {}

        def _build_hub(config, config_entry, http_session, hass_):
            captured["session"] = http_session
            captured["connector"] = http_session.connector
            return make_securitas_hub_mock()

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

        return captured

    async def test_option_saved_on_returns_an_ipv4_only_connection(self, hass):
        """A saved `force_ipv4: True` reaches setup and picks the IPv4 client."""
        captured = await self._session_setup_built(hass, saved_option=True)

        assert captured["session"] is not async_get_clientsession(hass)
        assert captured["connector"]._family == socket.AF_INET

    async def test_option_saved_off_keeps_the_shared_connection(self, hass):
        """A saved `force_ipv4: False` leaves the shared client in place."""
        captured = await self._session_setup_built(hass, saved_option=False)

        assert captured["session"] is async_get_clientsession(hass)

    async def test_unset_option_keeps_the_shared_connection(self, hass):
        """An entry saved before this option existed connects as it always did."""
        captured = await self._session_setup_built(hass, saved_option=None)

        assert captured["session"] is async_get_clientsession(hass)
