"""Verisure OWA binary sensor platform."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, VerisureDevice
from .coordinators import ActivityCoordinator, ActivityData, AlarmCoordinator
from .entity import securitas_device_info, zone_device_info
from .verisure_owa_api import Installation, PanelDevice
from .verisure_owa_api.models import ActivityCategory, ActivityEvent

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Verisure OWA binary sensor entities.

    Per-zone entities are not created here — they depend on an API call for
    the peripheral inventory and on the panel having actually reported a zone
    exception at least once, both of which happen after setup. The callback is
    parked in entry_data for discovery to use (the camera.py pattern).
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AlarmCoordinator = entry_data["alarm_coordinator"]
    securitas_devices: list[VerisureDevice] = entry_data["devices"]
    entry_data["binary_sensor_add_entities"] = async_add_entities

    entities: list[BinarySensorEntity] = []
    for device in securitas_devices:
        installation = device.installation
        entities.append(WifiConnectedSensor(coordinator, installation))
        entities.append(ZonesOpenSensor(coordinator, installation))
        entities.append(ZonesBatteryLowSensor(coordinator, installation))
    entities.extend(_build_panel_problem_sensors(entry_data))
    async_add_entities(entities, False)


class WifiConnectedSensor(  # type: ignore[override]
    CoordinatorEntity[AlarmCoordinator],
    BinarySensorEntity,
):
    """WiFi connection status from coordinator — no independent polling."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "WiFi Connected"
    _attr_should_poll = False

    def __init__(
        self, coordinator: AlarmCoordinator, installation: Installation
    ) -> None:
        super().__init__(coordinator)
        self._installation = installation
        self._attr_unique_id = (
            f"v4_securitas_direct.{installation.number}_wifi_connected"
        )
        self._attr_device_info = securitas_device_info(installation)

    @property
    def is_on(self) -> bool | None:  # type: ignore[override]
        """Return True if WiFi is connected."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.status.wifi_connected


# ── Panel problem sensors ────────────────────────────────────────────────────
#
# The panel's status endpoint (xSStatus) reports only arm state, wifi, and zone
# exceptions — nothing about intrusion, mains power, panel-to-central comms, or
# tampering.  The activity timeline is the only source for those, and it
# reports them as *edges*: "alarm fired" is an event, with no follow-up saying
# it is still firing.  These sensors therefore derive their state by scanning
# the timeline window rather than by tracking transitions.

# How long a tamper/sabotage report keeps the sensor on.
#
# TAMPERING and SABOTAGE have no paired "resolved" category — the panel never
# says the interference ended.  Clearing on a later DISARMED would be
# semantically false (disarming does not repair a prised-open cover) and would
# fire on the next routine morning disarm; never clearing makes the sensor
# useless after one lifetime event; clearing when the row falls out of the
# 30-row window is unpredictable (minutes on a busy panel, weeks on a quiet
# one).  A fixed window is the only policy that is both bounded and
# predictable.
_TAMPER_STICKY_WINDOW = timedelta(hours=24)

_PANEL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class PanelProblemSpec:
    """Declarative definition of one timeline-derived problem sensor."""

    key: str
    name: str
    device_class: BinarySensorDeviceClass
    on_categories: frozenset[ActivityCategory]
    off_categories: frozenset[ActivityCategory] = field(default=frozenset())
    entity_category: EntityCategory | None = None
    # When set, an ON event older than this no longer counts — for conditions
    # the panel never reports as resolved.
    sticky_for: timedelta | None = None


# Device classes are deliberately uniform on "on = bad".  POWER and
# CONNECTIVITY both mean "on = healthy", which would make is_on=False read as
# "mains cut" — backwards in every automation and dashboard.  The installation
# already carries a CONNECTIVITY sensor (WifiConnectedSensor); a second one
# with inverted polarity would be a support-ticket generator.
PANEL_PROBLEM_SPECS: tuple[PanelProblemSpec, ...] = (
    PanelProblemSpec(
        key="alarm_triggered",
        name="Alarm Triggered",
        device_class=BinarySensorDeviceClass.SAFETY,
        on_categories=frozenset({ActivityCategory.ALARM}),
        # DISARMED clears as well as ALARM_RESOLVED: only one panel type code
        # maps to ALARM_RESOLVED (331) against two for ALARM (13, 14), so on a
        # panel that never emits 331 this would latch on forever.  A panel
        # cannot be in alarm while disarmed, and disarming is the user
        # acknowledging the intrusion.
        off_categories=frozenset(
            {ActivityCategory.ALARM_RESOLVED, ActivityCategory.DISARMED}
        ),
    ),
    PanelProblemSpec(
        key="power_cut",
        name="Mains Power Cut",
        device_class=BinarySensorDeviceClass.PROBLEM,
        on_categories=frozenset({ActivityCategory.POWER_CUT}),
        off_categories=frozenset({ActivityCategory.POWER_RESTORED}),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PanelProblemSpec(
        key="communication_problem",
        name="Communication Problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        on_categories=frozenset({ActivityCategory.COMMUNICATION_FAILED}),
        off_categories=frozenset({ActivityCategory.COMMUNICATION_RESTORED}),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PanelProblemSpec(
        key="tamper",
        name="Tamper",
        device_class=BinarySensorDeviceClass.TAMPER,
        # One entity for both: each means "someone physically interfered", both
        # map to TAMPER, both are one-sided.  problem_category in the
        # attributes distinguishes them.
        on_categories=frozenset(
            {ActivityCategory.TAMPERING, ActivityCategory.SABOTAGE}
        ),
        sticky_for=_TAMPER_STICKY_WINDOW,
    ),
)


def _is_recent(value: str, window: timedelta) -> bool:
    """Return True if a panel timestamp falls within *window* of now.

    An empty or unparseable timestamp counts as recent: for a safety-class
    sensor a false alert beats a silent miss.  A future timestamp (panel clock
    ahead of HA's) also counts — the codebase already assumes the two clocks
    agree to within seconds (see _HA_ECHO_MATCH_WINDOW), and a window measured
    in hours is immune to anything that assumption tolerates.
    """
    if not value:
        return True
    try:
        stamp = datetime.strptime(value, _PANEL_TIME_FORMAT)
    except ValueError:
        return True
    return datetime.now() - stamp < window


def _build_panel_problem_sensors(
    entry_data: dict[str, Any],
) -> list[BinarySensorEntity]:
    """Create the panel problem sensors, but only if the timeline is polled.

    These entities are only as fresh as the activity coordinator, and it polls
    on a timer only when the user enabled background activity polling —
    otherwise it refreshes on demand (when the activity-log card is on screen).
    A safety sensor that silently stops updating is worse than an absent one,
    so with polling off they are not created at all.

    Gated on the coordinator's own interval rather than the config key: the
    interval is the single derived truth, and sensor.py asks the same question
    the same way.
    """
    coordinator: ActivityCoordinator | None = entry_data.get("activity_coordinator")
    if coordinator is None or coordinator.update_interval is None:
        return []
    return [
        PanelProblemSensor(coordinator, coordinator.installation, spec)
        for spec in PANEL_PROBLEM_SPECS
    ]


class PanelProblemSensor(  # type: ignore[override]
    CoordinatorEntity[ActivityCoordinator],
    BinarySensorEntity,
):
    """A panel condition derived from the activity timeline.

    State comes from scanning the timeline window on every read and taking the
    most recent event that is decisive for this sensor.  That is deliberately
    stateless: `new_events` is empty by construction on the first poll after
    every restart and reload, so a transition tracker would learn nothing at
    startup and would need the window scan anyway as a cold-start pass.
    Scanning also resolves an ON and an OFF arriving in the same batch for
    free — whichever is newer wins — and self-heals: if HA was down while an
    alarm fired and was resolved, the first poll sees both rows and lands off.

    For the same reason there is no RestoreEntity: a restored value is an
    unverifiable claim about the panel made by a process that was not running.
    Restoring "on" for an alarm that was resolved during the outage would fire
    a phantom "alarm resolved" transition 60 seconds later.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: ActivityCoordinator,
        installation: Installation,
        spec: PanelProblemSpec,
    ) -> None:
        super().__init__(coordinator)
        self._spec = spec
        self._installation = installation
        self._attr_name = spec.name
        self._attr_device_class = spec.device_class
        self._attr_entity_category = spec.entity_category
        self._attr_unique_id = f"v4_securitas_direct.{installation.number}_{spec.key}"
        self._attr_device_info = securitas_device_info(installation)
        self._event_cache: tuple[ActivityData, ActivityEvent | None] | None = None
        self._attrs_cache: tuple[ActivityData, dict[str, Any] | None] | None = None

    def _decisive_event(self) -> ActivityEvent | None:
        """Return the newest timeline event that decides this sensor's state.

        HA-injected rows are skipped.  This is a stuck-sensor guard, not
        cosmetics: COMMUNICATION_FAILED is injectable but there is no
        injectable COMMUNICATION_RESTORED, so an injected failure would latch
        the sensor on with no possible pairing clear.  Injected rows also
        describe HA-to-cloud health, which WifiConnectedSensor already covers,
        whereas these sensors describe the panel.

        Rows tagged `duplicate_of` are kept — those are the panel's own entries
        carrying its authoritative type and native-language alias.  Since the
        injected original is already filtered out, each real event is counted
        exactly once, from the panel's own record.
        """
        data = self.coordinator.data
        if data is None:
            return None
        if self._event_cache is not None and self._event_cache[0] is data:
            return self._event_cache[1]
        decisive = self._spec.on_categories | self._spec.off_categories
        event = next(
            (ev for ev in data.events if not ev.injected and ev.category in decisive),
            None,
        )
        self._event_cache = (data, event)
        return event

    @property
    def is_on(self) -> bool | None:  # type: ignore[override]
        """Return True while the panel condition is active.

        Nothing decisive in the window means off, not unknown: a healthy panel
        emits 30 arm/disarm rows and no problem rows, and a tile stuck on
        "Unknown" forever is indistinguishable from a broken integration.
        Unknown is reserved for genuinely unknown — no data fetched yet.
        """
        data = self.coordinator.data
        if data is None:
            return None
        event = self._decisive_event()
        if event is None or event.category not in self._spec.on_categories:
            return False
        if self._spec.sticky_for is None:
            return True
        return _is_recent(event.time, self._spec.sticky_for)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:  # type: ignore[override]
        """Describe the event that decided the current state.

        These always describe the most recent event this sensor tracks, which
        includes the case where the sensor has since cleared — e.g. a 30-hour
        old tamper row while `is_on` is False.
        """
        data = self.coordinator.data
        if self._attrs_cache is not None and self._attrs_cache[0] is data:
            return self._attrs_cache[1]
        event = self._decisive_event()
        attrs: dict[str, Any] | None = (
            None
            if event is None
            else {
                "problem_category": event.category.value,
                "last_event_time": event.time,
                "last_event_alias": event.alias,
                "last_event_id_signal": event.id_signal,
                "last_event_device": event.device_name,
            }
        )
        if data is not None:
            self._attrs_cache = (data, attrs)
        return attrs


# ── Zone exception sensors ───────────────────────────────────────────────────
#
# Source: xSStatus.exceptions, already fetched by AlarmCoordinator on every
# poll and previously discarded — so these cost no extra API calls.
#
# The list is SPARSE: only zones with a current problem appear. A zone that is
# absent therefore means "no exception reported", which implies "closed and
# healthy" ONLY if the panel populates the field at all. Until the coordinator
# has seen one non-empty payload (`exceptions_observed`), every zone-derived
# sensor reports unknown rather than asserting all-clear — see
# AlarmCoordinator._refresh_exception_cache.

_STATUS_OPEN = "open"
_STATUS_BATTERY_LOW = "battery_low"

# Human-readable model per inventory device type, for the child device entry.
_ZONE_DEVICE_MODELS: dict[str, str] = {"MG": "Magnetic contact"}

# Below this length a prefix match is too weak to trust — a 2-3 character
# label would collide with half the installation.
_MIN_PREFIX_MATCH_LEN = 4

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def zone_alias_slug(alias: str) -> str:
    """Normalise a panel alias into a unique_id-safe fragment."""
    return _SLUG_RE.sub("_", alias.strip().casefold()).strip("_")


def alias_matches(alias: str, name: str) -> bool:
    """Return True if a panel exception *alias* plausibly denotes zone *name*.

    The exceptions payload identifies zones only by ``alias`` — a panel label
    that may be truncated (~11 chars in observed data) — while the inventory
    carries the full ``name``. Equal strings match; otherwise one must be a
    prefix of the other, and both must be long enough for a prefix to mean
    anything (a 2-3 character label would collide with half the installation).

    Case is deliberately preserved: casefolding would collapse short accented
    labels such as ``Vbaño`` into false collisions.
    """
    alias, name = alias.strip(), name.strip()
    if not alias or not name:
        return False
    if alias == name:
        return True
    if min(len(alias), len(name)) < _MIN_PREFIX_MATCH_LEN:
        return False
    return alias.startswith(name) or name.startswith(alias)


def match_exception_keys(keys: dict[str, frozenset[str]], name: str) -> frozenset[str]:
    """Resolve one device's exception kinds from the panel's alias-keyed map.

    Exact matches win outright. Failing that a prefix match is accepted only
    when exactly one alias qualifies: ambiguity always loses. If ``Dorm``
    plausibly matches both ``Dorm1`` and ``Dorm2``, nothing is returned —
    reporting the neighbouring door's state is a silent, dangerous error, far
    worse than reporting nothing at all.
    """
    name = name.strip()
    if not name:
        return frozenset()
    exact = keys.get(name)
    if exact is not None:
        return exact
    candidates = [key for key in keys if alias_matches(key, name)]
    if len(candidates) == 1:
        return keys[candidates[0]]
    return frozenset()


@dataclass(frozen=True)
class ZoneTarget:
    """Identity of one zone the panel can report exceptions for."""

    # unique_id / device-identifier fragment: the panel zone id (``MG04``) for
    # an inventory device, or ``alias_<slug>`` for a zone known by name only.
    key: str
    name: str
    # What to match against the panel's exception aliases. Equal to `name` for
    # inventory devices; for orphans it is the alias itself, so exact matching
    # always succeeds.
    match_name: str
    model: str | None = None

    @classmethod
    def from_device(cls, device: PanelDevice) -> ZoneTarget:
        """Build a target from an inventory peripheral."""
        return cls(
            key=device.zone_id,
            name=device.name,
            match_name=device.name,
            model=_ZONE_DEVICE_MODELS.get(device.device_type, device.device_type),
        )

    @classmethod
    def from_alias(cls, alias: str) -> ZoneTarget:
        """Build a target for a zone the panel named but the inventory lacks."""
        alias = alias.strip()
        return cls(key=f"alias_{zone_alias_slug(alias)}", name=alias, match_name=alias)


class _ZoneExceptionSensorBase(  # type: ignore[override]
    CoordinatorEntity[AlarmCoordinator],
    BinarySensorEntity,
):
    """Shared evidence gate for everything derived from status.exceptions."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _status_key: str = ""

    def _gate_open(self) -> bool:
        """Return True when the exceptions feed is known to carry information."""
        return (
            self.coordinator.data is not None and self.coordinator.exceptions_observed
        )


class _ZoneAggregateSensor(_ZoneExceptionSensorBase):
    """Installation-wide roll-up of one exception kind.

    Computed straight from the panel's raw alias list, never from the
    inventory, so a zone the integration failed to identify still counts
    towards the state and still appears in the attributes.
    """

    _unique_id_suffix: str = ""

    def __init__(
        self, coordinator: AlarmCoordinator, installation: Installation
    ) -> None:
        super().__init__(coordinator)
        self._installation = installation
        self._attr_unique_id = (
            f"v4_securitas_direct.{installation.number}_{self._unique_id_suffix}"
        )
        self._attr_device_info = securitas_device_info(installation)
        self._attrs_cache: tuple[object, dict[str, Any]] | None = None

    def _affected_zones(self) -> list[str]:
        keys = self.coordinator.zone_exception_keys
        seen: set[str] = set()
        zones: list[str] = []
        for alias in self.coordinator.zone_exception_aliases:
            if alias in seen or self._status_key not in keys.get(alias, frozenset()):
                continue
            seen.add(alias)
            zones.append(alias)
        return zones

    @property
    def is_on(self) -> bool | None:  # type: ignore[override]
        """Return True if any zone currently reports this exception kind."""
        if not self._gate_open():
            return None
        return bool(self._affected_zones())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:  # type: ignore[override]
        """List the affected zones by their panel alias."""
        data = self.coordinator.data
        if self._attrs_cache is not None and self._attrs_cache[0] is data:
            return self._attrs_cache[1]
        zones = self._affected_zones() if self._gate_open() else []
        attrs: dict[str, Any] = {"zones": zones, "count": len(zones)}
        if data is not None:
            self._attrs_cache = (data, attrs)
        return attrs


class ZonesOpenSensor(_ZoneAggregateSensor):
    """True while any zone reports itself open."""

    # No entity_category: this is a security signal a user puts on a dashboard,
    # and DIAGNOSTIC would hide it from auto-generated views.
    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_name = "Zones Open"
    _status_key = _STATUS_OPEN
    _unique_id_suffix = "zones_open"


class ZonesBatteryLowSensor(_ZoneAggregateSensor):
    """True while any zone reports a flat battery."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Zone Battery Low"
    _status_key = _STATUS_BATTERY_LOW
    _unique_id_suffix = "zones_battery_low"


class _ZoneSensor(_ZoneExceptionSensorBase):
    """One exception kind for one zone, on that zone's own child device."""

    _unique_id_infix: str = ""

    def __init__(
        self,
        coordinator: AlarmCoordinator,
        installation: Installation,
        target: ZoneTarget,
        hass: HomeAssistant | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._installation = installation
        self._target = target
        self._attr_unique_id = (
            f"v4_securitas_direct.{installation.number}"
            f"_zone_{self._unique_id_infix}{target.key}"
        )
        self._attr_device_info = zone_device_info(
            installation, target.key, target.name, target.model, hass
        )

    @property
    def is_on(self) -> bool | None:  # type: ignore[override]
        """Return True while this zone reports this exception kind."""
        if not self._gate_open():
            return None
        return self._status_key in match_exception_keys(
            self.coordinator.zone_exception_keys, self._target.match_name
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:  # type: ignore[override]
        """Expose the panel identifiers behind this entity."""
        return {"zone_key": self._target.key, "panel_alias": self._target.match_name}


class ZoneOpenSensor(_ZoneSensor):
    """Open/closed state for a single zone."""

    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_name = "Open"
    _status_key = _STATUS_OPEN


class ZoneBatteryLowSensor(_ZoneSensor):
    """Battery state for a single zone."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Battery"
    _status_key = _STATUS_BATTERY_LOW
    _unique_id_infix = "battery_"


def build_zone_entities(
    coordinator: AlarmCoordinator,
    installation: Installation,
    targets: list[ZoneTarget],
    hass: HomeAssistant | None = None,
) -> list[BinarySensorEntity]:
    """Create the open + battery entity pair for each zone target."""
    entities: list[BinarySensorEntity] = []
    for target in targets:
        entities.append(ZoneOpenSensor(coordinator, installation, target, hass))
        entities.append(ZoneBatteryLowSensor(coordinator, installation, target, hass))
    return entities
