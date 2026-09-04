"""Tests for the Verisure OWA activity `event` entity."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homeassistant.components.event.const import ATTR_EVENT_TYPE

from custom_components.securitas.const import DOMAIN
from custom_components.securitas.coordinators import ActivityData
from custom_components.securitas.event import (
    ActivityLogEvent,
    _event_attributes,
    async_setup_entry,
)
from custom_components.securitas.verisure_owa_api.models import (
    ActivityCategory,
    ActivityEvent,
    Installation,
)


def make_installation() -> Installation:
    return Installation(
        number="123456", alias="Home", panel="SDVFAST", type="PLUS", address="123 St"
    )


def _make_event(id_signal: str, **overrides) -> ActivityEvent:
    base = {
        "alias": "Armed",
        "type": 701,
        "signal_type": 701,
        "id_signal": id_signal,
        "time": "2026-05-05 15:00:00",
        "img": 0,
        "device_name": "Ingresso",
        "verisure_user": "Luci",
    }
    base.update(overrides)
    return ActivityEvent.model_validate(base)


def _make_coordinator(data: ActivityData | None = None) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.installation = make_installation()
    return coordinator


def _entity(data: ActivityData | None = None) -> ActivityLogEvent:
    coordinator = _make_coordinator(data)
    entity = ActivityLogEvent(coordinator, coordinator.installation)
    entity.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    return entity


class TestActivityLogEvent:
    def test_event_types_are_every_activity_category(self):
        entity = _entity()
        assert entity.event_types == [c.value for c in ActivityCategory]

    def test_unique_id_is_activity_event_suffixed(self):
        entity = _entity()
        assert entity._attr_unique_id == "v4_securitas_direct.123456_activity_event"

    def test_no_trigger_when_new_events_empty(self):
        """First-poll baseline / no-new: state stays None, nothing fired."""
        entity = _entity(ActivityData(events=[_make_event("1")], new_events=[]))
        entity._handle_coordinator_update()
        assert entity.state is None
        entity.async_write_ha_state.assert_called_once()

    def test_triggers_for_each_new_event_in_order(self):
        # Set `category` explicitly — the model validator honours it and skips
        # numeric type→category derivation, keeping the assertion deterministic.
        e1 = _make_event("1", alias="Armed", category="armed")
        e2 = _make_event("2", alias="Disarmed", category="disarmed")
        entity = _entity(ActivityData(events=[e2, e1], new_events=[e1, e2]))
        entity._handle_coordinator_update()
        # Each new event publishes its own state change — not just the last.
        assert entity.async_write_ha_state.call_count == 2
        # Last triggered wins the exposed event_type; state is a timestamp.
        assert entity.state_attributes[ATTR_EVENT_TYPE] == "disarmed"
        assert entity.state is not None

    def test_image_request_carries_id_signal_and_signal_type(self):
        img = _make_event(
            "9",
            alias="Image request",
            category="image_request",
            signal_type=99,
            verisure_user=None,
            device_name="Cucina",
        )
        entity = _entity(ActivityData(events=[img], new_events=[img]))
        entity._handle_coordinator_update()
        attrs = entity.state_attributes
        assert attrs[ATTR_EVENT_TYPE] == ActivityCategory.IMAGE_REQUEST.value
        assert attrs["id_signal"] == "9"
        assert attrs["signal_type"] == 99

    def test_attributes_are_single_event_not_a_dump(self):
        e1 = _make_event("1")
        attrs = _event_attributes(e1)
        assert set(attrs) == {
            "alias",
            "device_name",
            "verisure_user",
            "time",
            "id_signal",
            "signal_type",
            "img",
            "injected",
            "exceptions",
        }


@pytest.mark.asyncio
async def test_setup_adds_one_event_entity_when_activity_coordinator_present():
    coordinator = _make_coordinator(ActivityData(events=[], new_events=[]))
    entry = MagicMock()
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: {"activity_coordinator": coordinator}}}
    added: list = []
    await async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    assert len(added) == 1
    assert isinstance(added[0], ActivityLogEvent)


@pytest.mark.asyncio
async def test_setup_adds_nothing_without_activity_coordinator():
    entry = MagicMock()
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: {"activity_coordinator": None}}}
    added: list = []
    await async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    assert added == []


_COMPONENT = Path("custom_components/securitas")
_LOCALES = ["ca", "en", "es", "fr", "it", "pt", "pt-BR"]


def _all_translation_files() -> list[Path]:
    return [_COMPONENT / "strings.json"] + [
        _COMPONENT / "translations" / f"{loc}.json" for loc in _LOCALES
    ]


class TestActivityEventTranslations:
    def test_every_file_has_activity_event_name(self):
        for path in _all_translation_files():
            data = json.loads(path.read_text(encoding="utf-8"))
            name = data["entity"]["event"]["activity"]["name"]
            assert name, f"missing entity.event.activity.name in {path}"

    def test_every_file_translates_every_event_type(self):
        expected = {c.value for c in ActivityCategory}
        for path in _all_translation_files():
            data = json.loads(path.read_text(encoding="utf-8"))
            states = data["entity"]["event"]["activity"]["state_attributes"][
                "event_type"
            ]["state"]
            assert set(states) == expected, f"event_type states drift in {path}"
