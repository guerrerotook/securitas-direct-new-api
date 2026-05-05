"""Tests for the activity-timeline event-bus helper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.securitas.coordinators import ActivityCoordinator, ActivityData
from custom_components.securitas.events import (
    ACTIVITY_EVENT_TYPE,
    attach_activity_listener,
    fire_activity_events,
    inject_ha_event,
    make_synthetic_event,
    resolve_ha_user,
)
from custom_components.securitas.const import DOMAIN
from custom_components.securitas.securitas_direct_new_api.models import Installation
from custom_components.securitas.securitas_direct_new_api.models import (
    ActivityCategory,
    ActivityEvent,
    ActivityException,
)


def _make_event(id_signal: str, **overrides) -> ActivityEvent:
    base = {
        "alias": "Armed",
        "type": 701,
        "signal_type": 701,
        "id_signal": id_signal,
        "time": "2026-05-05 15:00:00",
        "img": 0,
        "source": "Web",
        "device": "VV",
        "device_name": "Ingresso",
        "verisure_user": "Test User",
    }
    base.update(overrides)
    return ActivityEvent.model_validate(base)


class TestFireActivityEvents:
    def test_fires_one_event_per_activity(self):
        hass = MagicMock()
        events = [_make_event("999"), _make_event("998", type=720, alias="Disarmed")]

        fire_activity_events(hass, "2654190", events)

        assert hass.bus.async_fire.call_count == 2

    def test_event_type_is_securitas_activity(self):
        hass = MagicMock()
        fire_activity_events(hass, "2654190", [_make_event("999")])

        event_type = hass.bus.async_fire.call_args[0][0]
        assert event_type == "securitas_activity"
        assert event_type == ACTIVITY_EVENT_TYPE

    def test_payload_includes_numinst(self):
        hass = MagicMock()
        fire_activity_events(hass, "2654190", [_make_event("999")])

        payload = hass.bus.async_fire.call_args[0][1]
        assert payload["numinst"] == "2654190"

    def test_payload_includes_event_fields(self):
        hass = MagicMock()
        ev = _make_event("16215212397", type=701, alias="Armed", device="VV")

        fire_activity_events(hass, "2654190", [ev])

        payload = hass.bus.async_fire.call_args[0][1]
        assert payload["id_signal"] == "16215212397"
        assert payload["type"] == 701
        assert payload["alias"] == "Armed"
        assert payload["device"] == "VV"
        assert payload["time"] == "2026-05-05 15:00:00"

    def test_payload_includes_category(self):
        """Automations can filter by `category` instead of raw type codes."""
        hass = MagicMock()
        ev = _make_event("999", type=701, alias="Armed")

        fire_activity_events(hass, "2654190", [ev])

        payload = hass.bus.async_fire.call_args[0][1]
        assert payload["category"] == "armed"

    def test_empty_list_fires_nothing(self):
        hass = MagicMock()
        fire_activity_events(hass, "2654190", [])
        hass.bus.async_fire.assert_not_called()

    def test_each_event_gets_its_own_call(self):
        """Multiple events each get a distinct fire with their own payload."""
        hass = MagicMock()
        ev1 = _make_event("1", alias="Armed")
        ev2 = _make_event("2", alias="Disarmed", type=720, signal_type=720)

        fire_activity_events(hass, "2654190", [ev1, ev2])

        calls = hass.bus.async_fire.call_args_list
        payloads = [call[0][1] for call in calls]
        ids = [p["id_signal"] for p in payloads]
        aliases = [p["alias"] for p in payloads]
        assert ids == ["1", "2"]
        assert aliases == ["Armed", "Disarmed"]


class TestAttachActivityListener:
    def test_registers_listener_and_returns_unsub(self):
        hass = MagicMock()
        unsub_sentinel = object()
        coord = MagicMock(spec=ActivityCoordinator)
        coord.async_add_listener.return_value = unsub_sentinel

        unsub = attach_activity_listener(hass, coord, "2654190")

        coord.async_add_listener.assert_called_once()
        assert unsub is unsub_sentinel

    def test_registered_callback_fires_new_events(self):
        hass = MagicMock()
        coord = MagicMock(spec=ActivityCoordinator)
        new_event = _make_event("999")
        coord.data = ActivityData(events=[new_event], new_events=[new_event])

        attach_activity_listener(hass, coord, "2654190")
        callback = coord.async_add_listener.call_args[0][0]
        callback()

        assert hass.bus.async_fire.call_count == 1
        payload = hass.bus.async_fire.call_args[0][1]
        assert payload["numinst"] == "2654190"
        assert payload["id_signal"] == "999"

    def test_callback_is_silent_when_data_is_none(self):
        """If the coordinator hasn't completed a refresh yet, fire nothing."""
        hass = MagicMock()
        coord = MagicMock(spec=ActivityCoordinator)
        coord.data = None

        attach_activity_listener(hass, coord, "2654190")
        callback = coord.async_add_listener.call_args[0][0]
        callback()

        hass.bus.async_fire.assert_not_called()

    def test_callback_silent_when_no_new_events(self):
        """First poll: coordinator.data has events but no new_events."""
        hass = MagicMock()
        coord = MagicMock(spec=ActivityCoordinator)
        coord.data = ActivityData(events=[_make_event("999")], new_events=[])

        attach_activity_listener(hass, coord, "2654190")
        callback = coord.async_add_listener.call_args[0][0]
        callback()

        hass.bus.async_fire.assert_not_called()


# ── resolve_ha_user ──────────────────────────────────────────────────────────


class TestResolveHaUser:
    """Maps HA Context.user_id → display name for synthetic event attribution."""

    @pytest.mark.asyncio
    async def test_returns_user_name_when_resolvable(self):
        hass = MagicMock()
        user = MagicMock()
        user.name = "Clinton"
        hass.auth.async_get_user = AsyncMock(return_value=user)

        ctx = MagicMock()
        ctx.user_id = "uid-123"

        assert await resolve_ha_user(hass, ctx) == "Clinton"
        hass.auth.async_get_user.assert_awaited_once_with("uid-123")

    @pytest.mark.asyncio
    async def test_returns_home_assistant_when_no_context(self):
        hass = MagicMock()
        hass.auth.async_get_user = AsyncMock()

        result = await resolve_ha_user(hass, None)
        assert result == "Home Assistant"
        hass.auth.async_get_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_home_assistant_when_no_user_id(self):
        """Automation/script triggers have no user_id."""
        hass = MagicMock()
        hass.auth.async_get_user = AsyncMock()

        ctx = MagicMock()
        ctx.user_id = None

        result = await resolve_ha_user(hass, ctx)
        assert result == "Home Assistant"
        hass.auth.async_get_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_home_assistant_when_user_not_found(self):
        hass = MagicMock()
        hass.auth.async_get_user = AsyncMock(return_value=None)

        ctx = MagicMock()
        ctx.user_id = "deleted-uid"

        result = await resolve_ha_user(hass, ctx)
        assert result == "Home Assistant"


# ── make_synthetic_event ─────────────────────────────────────────────────────


class TestMakeSyntheticEvent:
    """Factory for HA-side synthetic ActivityEvent instances."""

    def test_basic_armed_event(self):
        ev = make_synthetic_event(
            category=ActivityCategory.ARMED, alias="Armed", verisure_user="Clinton"
        )
        assert isinstance(ev, ActivityEvent)
        assert ev.alias == "Armed"
        assert ev.verisure_user == "Clinton"
        assert ev.source == "Home Assistant"
        assert ev.category == ActivityCategory.ARMED

    def test_id_signal_is_synthetic_prefix(self):
        """Synthetic ids start with 'ha-' so they don't collide with panel ids."""
        ev = make_synthetic_event(
            category=ActivityCategory.ARMED, alias="Armed", verisure_user="x"
        )
        assert ev.id_signal.startswith("ha-")

    def test_two_calls_produce_distinct_ids(self):
        ev1 = make_synthetic_event(
            category=ActivityCategory.ARMED, alias="Armed", verisure_user="x"
        )
        ev2 = make_synthetic_event(
            category=ActivityCategory.ARMED, alias="Armed", verisure_user="x"
        )
        assert ev1.id_signal != ev2.id_signal

    def test_time_format_matches_panel(self):
        """time format is 'YYYY-MM-DD HH:MM:SS' — matches the panel's naive format."""
        ev = make_synthetic_event(
            category=ActivityCategory.DISARMED, alias="Disarmed", verisure_user="x"
        )
        assert len(ev.time) == 19
        assert ev.time[4] == "-" and ev.time[10] == " " and ev.time[13] == ":"

    def test_every_category_round_trips_through_factory(self):
        """The factory picks a type code that maps back to the requested category.

        Regression test: an earlier version mapped only 4 of 13 categories,
        causing the rest to silently surface as ``UNKNOWN``.
        """
        for category in ActivityCategory:
            ev = make_synthetic_event(category=category, alias="x", verisure_user="x")
            assert ev.category == category, (
                f"make_synthetic_event(category={category}) produced "
                f"{ev.category} (type={ev.type})"
            )

    def test_armed_with_exceptions_carries_exceptions_list(self):
        """Force-arm injection includes the bypassed sensors."""
        excs = [
            ActivityException(status="0", device_type="MG", alias="Front Door"),
            ActivityException(status="2", device_type="MG", alias="Kitchen Window"),
        ]
        ev = make_synthetic_event(
            category=ActivityCategory.ARMED_WITH_EXCEPTIONS,
            alias="Armed with exceptions",
            verisure_user="x",
            exceptions=excs,
        )
        assert ev.category == ActivityCategory.ARMED_WITH_EXCEPTIONS
        assert ev.exceptions == excs

    def test_optional_device_name(self):
        ev = make_synthetic_event(
            category=ActivityCategory.IMAGE_REQUEST,
            alias="Image request",
            verisure_user="x",
            device_name="Cucina",
        )
        assert ev.device_name == "Cucina"


# ── inject_ha_event ──────────────────────────────────────────────────────────


def _make_test_installation(number: str = "123456") -> Installation:
    return Installation(
        number=number, alias="Home", panel="SDVFAST", type="PLUS", address="x"
    )


def _hass_with_activity_coord(
    installation: Installation, coord: MagicMock
) -> MagicMock:
    """Build a hass mock whose hass.data[DOMAIN][<entry>].activity_coordinator is `coord`."""
    coord.installation = installation
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "entry-1": {"activity_coordinator": coord},
        }
    }
    hass.auth.async_get_user = AsyncMock(return_value=None)  # no HA user by default
    return hass


class TestInjectHaEvent:
    @pytest.mark.asyncio
    async def test_finds_coordinator_and_injects(self):
        installation = _make_test_installation()
        coord = MagicMock(spec=ActivityCoordinator)
        hass = _hass_with_activity_coord(installation, coord)

        await inject_ha_event(
            hass, installation, category=ActivityCategory.ARMED, alias="Armed"
        )

        coord.inject_event.assert_called_once()
        injected = coord.inject_event.call_args[0][0]
        assert isinstance(injected, ActivityEvent)
        assert injected.category == ActivityCategory.ARMED

    @pytest.mark.asyncio
    async def test_uses_ha_user_name_when_context_has_user(self):
        installation = _make_test_installation()
        coord = MagicMock(spec=ActivityCoordinator)
        hass = _hass_with_activity_coord(installation, coord)
        user = MagicMock()
        user.name = "Clinton"
        hass.auth.async_get_user = AsyncMock(return_value=user)

        ctx = MagicMock()
        ctx.user_id = "uid"

        await inject_ha_event(
            hass,
            installation,
            category=ActivityCategory.ARMED,
            alias="Armed",
            context=ctx,
        )

        injected = coord.inject_event.call_args[0][0]
        assert injected.verisure_user == "Clinton"

    @pytest.mark.asyncio
    async def test_falls_back_to_home_assistant_without_user(self):
        installation = _make_test_installation()
        coord = MagicMock(spec=ActivityCoordinator)
        hass = _hass_with_activity_coord(installation, coord)

        await inject_ha_event(
            hass, installation, category=ActivityCategory.DISARMED, alias="Disarmed"
        )

        injected = coord.inject_event.call_args[0][0]
        assert injected.verisure_user == "Home Assistant"

    @pytest.mark.asyncio
    async def test_no_coordinator_for_installation_is_no_op(self):
        """Action fires for an installation whose coordinator doesn't exist (yet)."""
        installation = _make_test_installation(number="999")
        other_coord = MagicMock(spec=ActivityCoordinator)
        hass = _hass_with_activity_coord(
            _make_test_installation(number="123"), other_coord
        )

        # Should not raise and should not inject into the wrong coordinator
        await inject_ha_event(
            hass, installation, category=ActivityCategory.ARMED, alias="Armed"
        )
        other_coord.inject_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_entries_dispatch_by_installation_number(self):
        """With two installations, only the matching coordinator gets the inject."""
        installation_a = _make_test_installation(number="111")
        installation_b = _make_test_installation(number="222")
        coord_a = MagicMock(spec=ActivityCoordinator)
        coord_a.installation = installation_a
        coord_b = MagicMock(spec=ActivityCoordinator)
        coord_b.installation = installation_b
        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "e-a": {"activity_coordinator": coord_a},
                "e-b": {"activity_coordinator": coord_b},
            }
        }
        hass.auth.async_get_user = AsyncMock(return_value=None)

        await inject_ha_event(
            hass, installation_b, category=ActivityCategory.ARMED, alias="Armed"
        )

        coord_a.inject_event.assert_not_called()
        coord_b.inject_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_through_device_and_exceptions(self):
        installation = _make_test_installation()
        coord = MagicMock(spec=ActivityCoordinator)
        hass = _hass_with_activity_coord(installation, coord)
        excs = [ActivityException(status="0", device_type="MG", alias="Door")]

        await inject_ha_event(
            hass,
            installation,
            category=ActivityCategory.ARMED_WITH_EXCEPTIONS,
            alias="Armed with exceptions",
            device_name="Cucina",
            exceptions=excs,
        )

        injected = coord.inject_event.call_args[0][0]
        assert injected.device_name == "Cucina"
        assert injected.exceptions == excs
