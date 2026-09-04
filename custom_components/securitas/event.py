"""Verisure OWA event platform — the activity timeline as an `event` entity.

Additive companion to ``ActivityLogSensor``: exposes the same xSActV2 timeline
as a core-native ``event`` entity so it renders in the built-in Logbook and the
stock more-info dialog. Rides ``ActivityCoordinator.data.new_events`` — the
same delta the bus events use — so it inherits their semantics for free: no
historical replay on restart (first poll baselines silently), no double-firing
of HA-issued actions (``duplicate_of`` echoes are already excluded), and live
injected arm/disarm events.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .coordinators import ActivityCoordinator
from .entity import securitas_device_info
from .verisure_owa_api import Installation
from .verisure_owa_api.models import ActivityCategory, ActivityEvent


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Verisure OWA activity event entity.

    One entity per installation, only when the activity coordinator exists
    (it is absent when the installation has no accessible activity timeline).
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    activity_coord: ActivityCoordinator | None = entry_data.get("activity_coordinator")
    if activity_coord is not None:
        async_add_entities(
            [ActivityLogEvent(activity_coord, activity_coord.installation)]
        )


def _event_attributes(event: ActivityEvent) -> dict[str, Any]:
    """Flatten one ActivityEvent into a small, recorder-friendly attr dict."""
    return {
        "alias": event.alias,
        "device_name": event.device_name,
        "verisure_user": event.verisure_user,
        "time": event.time,
        "id_signal": event.id_signal,
        "signal_type": event.signal_type,
        "img": event.img,
        "injected": event.injected,
        "exceptions": (
            [exc.model_dump() for exc in event.exceptions] if event.exceptions else []
        ),
    }


class ActivityLogEvent(  # type: ignore[override]
    CoordinatorEntity[ActivityCoordinator],
    EventEntity,
):
    """The alarm panel's activity timeline as an ``event`` entity."""

    _attr_has_entity_name = True
    _attr_translation_key = "activity"
    _attr_icon = "mdi:format-list-bulleted"
    # EventEntity declares `_attr_event_types` as an instance var (not
    # ClassVar), so a ClassVar annotation here would itself be a pyright
    # reportIncompatibleVariableOverride — plain assignment, RUF012 accepted.
    _attr_event_types = [  # noqa: RUF012
        category.value for category in ActivityCategory
    ]

    def __init__(
        self, coordinator: ActivityCoordinator, installation: Installation
    ) -> None:
        """Initialise the activity event entity."""
        super().__init__(coordinator)
        self._installation = installation
        self._attr_device_info = securitas_device_info(installation)
        self._attr_unique_id = (
            f"v4_securitas_direct.{installation.number}_activity_event"
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Publish one state change per just-arrived timeline entry, in order.

        A single poll can surface several new events (e.g. arm-then-disarm
        within the poll interval). ``_trigger_event`` only mutates the pending
        event fields — the *state change* is what reaches the Logbook and
        event-based automation triggers — so each event needs its own
        ``async_write_ha_state()`` or only the last would be observable. The
        empty path still writes once (keeps availability fresh; the first-poll
        baseline carries no ``new_events`` so nothing is replayed).
        """
        data = self.coordinator.data
        if data is not None and data.new_events:
            # new_events is newest-first (the coordinator sorts reverse=True).
            # Fire oldest→newest so each event still gets its own state change
            # (Logbook / automation visibility) AND the NEWEST event wins the
            # entity's resting state.
            for event in reversed(data.new_events):
                self._trigger_event(event.category.value, _event_attributes(event))
                self.async_write_ha_state()
        else:
            self.async_write_ha_state()
