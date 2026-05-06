"""HA event-bus emission for the Securitas Direct activity timeline."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.core import Context, HomeAssistant

from .const import DOMAIN
from .securitas_direct_new_api.models import (
    ActivityCategory,
    ActivityEvent,
    ActivityException,
    Installation,
)

if TYPE_CHECKING:
    from .coordinators import ActivityCoordinator


ACTIVITY_EVENT_TYPE = "securitas_activity"

# Display name attributed to synthetic events when the triggering HA call
# carries no user_id (automation/script-driven actions).
_HA_USER = "Home Assistant"


def fire_activity_events(
    hass: HomeAssistant, numinst: str, events: list[ActivityEvent]
) -> None:
    """Fire one ``securitas_activity`` HA event per ActivityEvent.

    Each ``event_data`` carries the originating ``numinst`` so multi-installation
    users can disambiguate.
    """
    for event in events:
        payload: dict[str, object] = {"numinst": numinst, **event.model_dump()}
        hass.bus.async_fire(ACTIVITY_EVENT_TYPE, payload)


async def resolve_ha_user(hass: HomeAssistant, context: Context | None) -> str:
    """Resolve a HA service-call context to a display name for attribution.

    Returns the HA user's name when the call has a real ``user_id`` (a logged-in
    person clicked a button or called a service).  For automation/script-driven
    calls or missing context, returns ``_HA_USER``.
    """
    if context is None:
        return _HA_USER
    user_id = context.user_id
    if not user_id:
        return _HA_USER
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        return _HA_USER
    return user.name or _HA_USER


def make_synthetic_event(
    *,
    category: ActivityCategory,
    alias: str,
    verisure_user: str,
    device: str | None = None,
    device_name: str | None = None,
    exceptions: list[ActivityException] | None = None,
) -> ActivityEvent:
    """Build a HA-side ActivityEvent for injection into the coordinator.

    Sets ``category`` explicitly (no panel-equivalent type code is borrowed —
    `type` stays at 0 for HA-issued events).  Synthesises a unique
    ``id_signal`` (prefixed ``ha-``) so it never collides with the panel's
    numeric ids; sets ``source`` to ``"Home Assistant"`` so automations can
    distinguish HA-issued events from panel/app/website ones.
    """
    return ActivityEvent(
        alias=alias,
        type=0,
        signal_type=0,
        category=category,
        id_signal=f"ha-{uuid.uuid4().hex}",
        time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        source=_HA_USER,
        verisure_user=verisure_user,
        device=device,
        device_name=device_name,
        exceptions=exceptions,
        injected=True,
    )


def _find_activity_coordinator(
    hass: HomeAssistant, installation: Installation
) -> ActivityCoordinator | None:
    """Look up the ActivityCoordinator for a given installation, or None."""
    if hass is None or not hasattr(hass, "data"):
        return None
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        if not isinstance(entry_data, dict):
            continue
        coord = entry_data.get("activity_coordinator")
        if coord is None:
            continue
        if getattr(coord.installation, "number", None) == installation.number:
            return coord
    return None


async def inject_ha_event(
    hass: HomeAssistant,
    installation: Installation,
    *,
    category: ActivityCategory,
    alias: str,
    context: Context | None = None,
    device: str | None = None,
    device_name: str | None = None,
    exceptions: list[ActivityException] | None = None,
) -> None:
    """Inject a HA-side event into the activity timeline for `installation`.

    Resolves the HA user from `context`, builds a synthetic ActivityEvent, and
    pushes it onto the matching ActivityCoordinator.  Silently no-ops if no
    coordinator exists for the installation (integration not loaded).
    """
    coord = _find_activity_coordinator(hass, installation)
    if coord is None:
        return
    user = await resolve_ha_user(hass, context)
    event = make_synthetic_event(
        category=category,
        alias=alias,
        verisure_user=user,
        device=device,
        device_name=device_name,
        exceptions=exceptions,
    )
    coord.inject_event(event)


def attach_activity_listener(
    hass: HomeAssistant,
    coordinator: ActivityCoordinator,
    numinst: str,
) -> Callable[[], None]:
    """Wire a coordinator listener that fires HA events for new entries.

    Returns the unsubscribe callable from ``async_add_listener``.
    """

    def _on_update() -> None:
        data = coordinator.data
        if data is not None and data.new_events:
            fire_activity_events(hass, numinst, data.new_events)

    return coordinator.async_add_listener(_on_update)
