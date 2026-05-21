"""HA event-bus emission for the Verisure OWA activity timeline."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from homeassistant.core import Context, HomeAssistant

from .const import DOMAIN
from .verisure_owa_api.models import (
    ActivityCategory,
    ActivityEvent,
    ActivityException,
    Installation,
)

if TYPE_CHECKING:
    from .coordinators import ActivityCoordinator


# Every event the integration fires is emitted under BOTH
# ``verisure_owa_<suffix>`` and ``securitas_<suffix>`` via ``fire_event``
# below. Both forms are functionally identical; docs steer users toward
# the ``verisure_owa_*`` form for forward compatibility with the deferred
# domain rename (see docs/MIGRATION_PLAN.md). The constants below name
# the verisure_owa form since that's the recommended one.
ACTIVITY_EVENT_TYPE = "verisure_owa_activity"
ARMING_EXCEPTION_EVENT_TYPE = "verisure_owa_arming_exception"

# Fired when the force-arm context times out (180 s) without the user
# acting on the action buttons. Built-in handler updates the mobile
# notification to remove its action buttons.
FORCE_ARM_EXPIRED_EVENT_TYPE = "verisure_owa_force_arm_expired"

# Fired when an active force-arm context is cleared by a different
# arm/disarm action (NOT by force_arm or force_arm_cancel themselves —
# those are the canonical resolutions). Built-in handler dismisses the
# persistent + mobile notifications.
ARMING_EXCEPTION_DISMISSED_EVENT_TYPE = "verisure_owa_arming_exception_dismissed"


def fire_event(hass: HomeAssistant, suffix: str, payload: dict[str, object]) -> None:
    """Fire ``verisure_owa_<suffix>`` and ``securitas_<suffix>`` in the same tick.

    Both events carry identical payloads. Subscribers that match either
    name will see the event. New automations should subscribe to the
    ``verisure_owa_*`` form (see docs/MIGRATION_PLAN.md).
    """
    hass.bus.async_fire(f"verisure_owa_{suffix}", payload)
    hass.bus.async_fire(f"securitas_{suffix}", payload)


# Closed set of `reason` values for the dismissed event. Kept as
# constants so callers can't typo a string and silently break user
# automations that match the documented values.
DISMISSAL_REASON_USER_ARM = "user_arm"
DISMISSAL_REASON_USER_DISARM = "user_disarm"
DISMISSAL_REASON_INTEGRATION_RELOAD = "integration_reload"
DismissalReason = Literal["user_arm", "user_disarm", "integration_reload"]

# Display name attributed to synthetic events when the triggering HA call
# carries no user_id (automation/script-driven actions).
_HA_USER = "Home Assistant"

# Categories the integration emits synthetic events for via
# ``inject_ha_event``.  Kept here, next to the inject call site, so adding
# a new injectable category in one place is enough — the coordinator imports
# this set to pair the panel's echo of an HA action (by category + timestamp)
# with the injected event and flag it ``duplicate_of``.
HA_INJECTABLE_CATEGORIES: frozenset[ActivityCategory] = frozenset(
    {
        ActivityCategory.ARMED,
        ActivityCategory.ARMED_WITH_EXCEPTIONS,
        ActivityCategory.ARMING_FAILED,
        ActivityCategory.COMMUNICATION_FAILED,
        ActivityCategory.DISARMED,
        ActivityCategory.IMAGE_REQUEST,
    }
)


def fire_activity_events(
    hass: HomeAssistant, numinst: str, events: list[ActivityEvent]
) -> None:
    """Fire one activity HA event per ActivityEvent under both event names.

    Each ``event_data`` carries the originating ``numinst`` so multi-installation
    users can disambiguate. Fires both ``verisure_owa_activity`` and
    ``securitas_activity`` via ``fire_event``.
    """
    for event in events:
        payload: dict[str, object] = {"numinst": numinst, **event.model_dump()}
        fire_event(hass, "activity", payload)


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
    id_signal: str | None = None,
    signal_type: str | int | None = None,
) -> ActivityEvent:
    """Build a HA-side ActivityEvent for injection into the coordinator.

    Sets ``category`` explicitly (no panel-equivalent type code is borrowed
    when ids are synthetic).  Sets ``source`` to ``"Home Assistant"`` so
    automations can distinguish HA-issued events from panel/app/website ones.

    When ``id_signal`` is provided (e.g. captured from a server response
    after a real camera capture), use it verbatim — that lets follow-up
    server-side queries like ``xSGetPhotoImages`` resolve.  Otherwise a
    synthetic id prefixed ``ha-`` is generated so it can't collide with
    panel numeric ids.
    """
    if id_signal:
        real_id = id_signal
        try:
            sig_type = int(signal_type) if signal_type is not None else 0
        except (TypeError, ValueError):
            sig_type = 0
    else:
        real_id = f"ha-{uuid.uuid4().hex}"
        sig_type = 0
    # img=1 tells the activity-log card to render an image block and
    # lazy-fetch via xSGetPhotoImages.  Only set it when we have a real
    # (server-side) id for an IMAGE_REQUEST — synthetic ha-... ids can't
    # resolve, and non-image categories don't carry photos.
    img_flag = 1 if category == ActivityCategory.IMAGE_REQUEST and id_signal else 0
    return ActivityEvent(
        alias=alias,
        type=sig_type,
        signal_type=sig_type,
        category=category,
        id_signal=real_id,
        time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        source=_HA_USER,
        verisure_user=verisure_user,
        device=device,
        device_name=device_name,
        exceptions=exceptions,
        img=img_flag,
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
    id_signal: str | None = None,
    signal_type: str | int | None = None,
) -> None:
    """Inject a HA-side event into the activity timeline for `installation`.

    Resolves the HA user from `context`, builds a synthetic ActivityEvent, and
    pushes it onto the matching ActivityCoordinator.  Silently no-ops if no
    coordinator exists for the installation (integration not loaded).

    Pass ``id_signal``/``signal_type`` when the action's server-side ids are
    known (e.g. after a successful camera capture); follow-up image fetches
    will then succeed.  Otherwise a synthetic ``ha-...`` id is generated.
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
        id_signal=id_signal,
        signal_type=signal_type,
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
