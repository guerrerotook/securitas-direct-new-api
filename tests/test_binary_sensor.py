"""Tests for the binary sensor platform.

Covers WifiConnectedSensor and the timeline-derived panel problem sensors.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from custom_components.securitas.binary_sensor import (
    PANEL_PROBLEM_SPECS,
    ArmingExceptionsSensor,
    PanelProblemSensor,
    WifiConnectedSensor,
    ZoneArmingExceptionSensor,
    ZoneBatteryLowSensor,
    ZonesBatteryLowSensor,
    ZoneTarget,
    _build_panel_problem_sensors,
    alias_matches,
    build_zone_entities,
    match_exception_keys,
    zone_alias_slug,
)
from custom_components.securitas.coordinators import (
    ActivityData,
    AlarmCoordinator,
    AlarmStatusData,
)
from custom_components.securitas.verisure_owa_api.models import (
    ActivityCategory,
    ActivityEvent,
    PanelDevice,
    SStatus,
)
from tests.conftest import make_installation

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_sensor(
    installation_overrides: dict | None = None,
) -> WifiConnectedSensor:
    """Create a WifiConnectedSensor with mocked dependencies."""
    installation = make_installation(**(installation_overrides or {}))
    coordinator = MagicMock(spec=AlarmCoordinator)
    coordinator.data = None
    sensor = WifiConnectedSensor(coordinator, installation)
    sensor.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    return sensor


# ===========================================================================
# __init__
# ===========================================================================


class TestWifiConnectedSensorInit:
    """Tests for WifiConnectedSensor.__init__."""

    def test_unique_id_format(self):
        sensor = make_sensor()
        assert sensor._attr_unique_id == "v4_securitas_direct.123456_wifi_connected"

    def test_name_is_short_form_without_alias(self):
        """Modern pattern: device name carries the alias; entity name is the suffix only."""
        sensor = make_sensor()
        assert sensor._attr_name == "WiFi Connected"

    def test_name_is_alias_independent(self):
        """Changing the alias does not change the entity name (it lives on the device)."""
        sensor = make_sensor(installation_overrides={"alias": "Office"})
        assert sensor._attr_name == "WiFi Connected"

    def test_has_entity_name_is_true(self):
        sensor = make_sensor()
        assert sensor._attr_has_entity_name is True

    def test_device_class_is_connectivity(self):
        sensor = make_sensor()
        assert sensor._attr_device_class == BinarySensorDeviceClass.CONNECTIVITY

    def test_entity_category_is_diagnostic(self):
        sensor = make_sensor()
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_should_poll_is_false(self):
        sensor = make_sensor()
        assert sensor._attr_should_poll is False


# ===========================================================================
# is_on property (coordinator-driven)
# ===========================================================================


class TestIsOnProperty:
    """Tests for WifiConnectedSensor.is_on property."""

    def test_returns_none_when_coordinator_data_is_none(self):
        """is_on returns None when coordinator has no data yet."""
        sensor = make_sensor()
        sensor.coordinator.data = None

        assert sensor.is_on is None

    def test_returns_true_when_wifi_connected(self):
        """is_on returns True when wifi_connected is True."""
        sensor = make_sensor()
        sensor.coordinator.data = AlarmStatusData(
            status=SStatus(wifi_connected=True),
        )

        assert sensor.is_on is True

    def test_returns_false_when_wifi_disconnected(self):
        """is_on returns False when wifi_connected is False."""
        sensor = make_sensor()
        sensor.coordinator.data = AlarmStatusData(
            status=SStatus(wifi_connected=False),
        )

        assert sensor.is_on is False

    def test_returns_none_when_wifi_connected_is_none(self):
        """is_on returns None when wifi_connected field is None."""
        sensor = make_sensor()
        sensor.coordinator.data = AlarmStatusData(
            status=SStatus(wifi_connected=None),
        )

        assert sensor.is_on is None


# ===========================================================================
# Panel problem sensors
# ===========================================================================

_SPEC_BY_KEY = {spec.key: spec for spec in PANEL_PROBLEM_SPECS}


def panel_time(**delta) -> str:
    """Format a panel timestamp relative to now."""
    return (datetime.now() - timedelta(**delta)).strftime("%Y-%m-%d %H:%M:%S")


def activity_event(
    category: ActivityCategory | None = None,
    *,
    time: str = "2026-08-09 10:00:00",
    injected: bool = False,
    **kwargs,
) -> ActivityEvent:
    """Build an ActivityEvent, optionally pinning its category explicitly."""
    payload = {"time": time, "injected": injected, **kwargs}
    if category is not None:
        payload["category"] = category
    return ActivityEvent(**payload)


def make_problem_sensor(
    spec_key: str,
    events: list[ActivityEvent] | None = None,
    *,
    data_is_none: bool = False,
) -> PanelProblemSensor:
    """Create a PanelProblemSensor over a mocked activity coordinator."""
    installation = make_installation()
    # Bare MagicMock rather than spec=ActivityCoordinator: `installation` and
    # `update_interval` are instance/base attributes a spec'd mock won't carry.
    coordinator = MagicMock()
    coordinator.installation = installation
    coordinator.update_interval = timedelta(seconds=60)
    coordinator.data = None if data_is_none else ActivityData(events=events or [])
    sensor = PanelProblemSensor(coordinator, installation, _SPEC_BY_KEY[spec_key])
    sensor.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    return sensor


class TestPanelProblemSetup:
    """Creation gating and entity metadata."""

    def test_not_created_when_polling_disabled(self):
        """update_interval None means the timeline only refreshes on demand."""
        coordinator = MagicMock()
        coordinator.update_interval = None
        coordinator.installation = make_installation()

        assert _build_panel_problem_sensors({"activity_coordinator": coordinator}) == []

    def test_not_created_when_coordinator_missing(self):
        assert _build_panel_problem_sensors({}) == []

    def test_creates_one_sensor_per_spec_when_polling_enabled(self):
        coordinator = MagicMock()
        coordinator.update_interval = timedelta(seconds=60)
        coordinator.installation = make_installation()

        sensors = _build_panel_problem_sensors({"activity_coordinator": coordinator})

        assert len(sensors) == len(PANEL_PROBLEM_SPECS)

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("alarm_triggered", "v4_securitas_direct.123456_alarm_triggered"),
            ("power_cut", "v4_securitas_direct.123456_power_cut"),
            (
                "communication_problem",
                "v4_securitas_direct.123456_communication_problem",
            ),
            ("tamper", "v4_securitas_direct.123456_tamper"),
        ],
    )
    def test_unique_id_format(self, key, expected):
        assert make_problem_sensor(key)._attr_unique_id == expected

    @pytest.mark.parametrize("key", list(_SPEC_BY_KEY))
    def test_name_is_alias_independent(self, key):
        """The installation alias lives on the device, never in the entity name."""
        installation = make_installation(alias="Office")
        coordinator = MagicMock()
        coordinator.data = None
        sensor = PanelProblemSensor(coordinator, installation, _SPEC_BY_KEY[key])

        assert "Office" not in (sensor._attr_name or "")

    @pytest.mark.parametrize("key", list(_SPEC_BY_KEY))
    def test_entity_conventions(self, key):
        sensor = make_problem_sensor(key)

        assert sensor._attr_has_entity_name is True
        assert sensor._attr_should_poll is False

    @pytest.mark.parametrize(
        ("key", "device_class", "entity_category"),
        [
            ("alarm_triggered", BinarySensorDeviceClass.SAFETY, None),
            ("power_cut", BinarySensorDeviceClass.PROBLEM, EntityCategory.DIAGNOSTIC),
            (
                "communication_problem",
                BinarySensorDeviceClass.PROBLEM,
                EntityCategory.DIAGNOSTIC,
            ),
            ("tamper", BinarySensorDeviceClass.TAMPER, None),
        ],
    )
    def test_device_class_and_category(self, key, device_class, entity_category):
        sensor = make_problem_sensor(key)

        assert sensor._attr_device_class == device_class
        assert sensor._attr_entity_category == entity_category


class TestPanelProblemLatching:
    """Window-scan state derivation."""

    @pytest.mark.parametrize("key", list(_SPEC_BY_KEY))
    def test_none_when_no_data(self, key):
        assert make_problem_sensor(key, data_is_none=True).is_on is None

    @pytest.mark.parametrize("key", list(_SPEC_BY_KEY))
    def test_off_when_window_empty(self, key):
        """Empty is off, not unknown — a healthy panel reports no problems."""
        assert make_problem_sensor(key, []).is_on is False

    @pytest.mark.parametrize("key", list(_SPEC_BY_KEY))
    def test_off_when_window_holds_only_unrelated_events(self, key):
        events = [
            activity_event(ActivityCategory.ARMED, time="2026-08-09 10:05:00"),
            activity_event(ActivityCategory.STATUS_CHECK, time="2026-08-09 10:00:00"),
        ]

        assert make_problem_sensor(key, events).is_on is False

    def test_alarm_on_when_alarm_is_newest(self):
        events = [activity_event(ActivityCategory.ALARM)]

        assert make_problem_sensor("alarm_triggered", events).is_on is True

    def test_alarm_does_not_leak_into_other_sensors(self):
        events = [activity_event(ActivityCategory.ALARM)]

        for key in ("power_cut", "communication_problem", "tamper"):
            assert make_problem_sensor(key, events).is_on is False

    def test_resolved_newer_than_alarm_clears(self):
        """ON and OFF in the same batch: the newer one wins."""
        events = [
            activity_event(ActivityCategory.ALARM_RESOLVED, time="2026-08-09 10:05:00"),
            activity_event(ActivityCategory.ALARM, time="2026-08-09 10:00:00"),
        ]

        assert make_problem_sensor("alarm_triggered", events).is_on is False

    def test_alarm_newer_than_resolved_stays_on(self):
        events = [
            activity_event(ActivityCategory.ALARM, time="2026-08-09 10:05:00"),
            activity_event(ActivityCategory.ALARM_RESOLVED, time="2026-08-09 10:00:00"),
        ]

        assert make_problem_sensor("alarm_triggered", events).is_on is True

    def test_disarm_clears_alarm(self):
        """Panels that never emit ALARM_RESOLVED (331) would otherwise latch on."""
        events = [
            activity_event(ActivityCategory.DISARMED, time="2026-08-09 10:05:00"),
            activity_event(ActivityCategory.ALARM, time="2026-08-09 10:00:00"),
        ]

        assert make_problem_sensor("alarm_triggered", events).is_on is False

    @pytest.mark.parametrize(
        ("key", "on_category", "off_category"),
        [
            (
                "power_cut",
                ActivityCategory.POWER_CUT,
                ActivityCategory.POWER_RESTORED,
            ),
            (
                "communication_problem",
                ActivityCategory.COMMUNICATION_FAILED,
                ActivityCategory.COMMUNICATION_RESTORED,
            ),
        ],
    )
    def test_paired_categories_latch_and_clear(self, key, on_category, off_category):
        on_only = [activity_event(on_category)]
        assert make_problem_sensor(key, on_only).is_on is True

        restored = [
            activity_event(off_category, time="2026-08-09 10:05:00"),
            activity_event(on_category, time="2026-08-09 10:00:00"),
        ]
        assert make_problem_sensor(key, restored).is_on is False

    def test_raw_panel_type_drives_category(self):
        """Type 13 is the panel's intrusion code; the type->category map is the contract."""
        events = [ActivityEvent(type=13, time="2026-08-09 10:00:00")]

        assert make_problem_sensor("alarm_triggered", events).is_on is True

    def test_newer_unrelated_event_does_not_disturb_a_latched_sensor(self):
        events = [
            activity_event(ActivityCategory.IMAGE_REQUEST, time="2026-08-09 10:05:00"),
            activity_event(ActivityCategory.POWER_CUT, time="2026-08-09 10:00:00"),
        ]

        assert make_problem_sensor("power_cut", events).is_on is True


class TestTamperStickiness:
    """One-sided tamper reports expire on a fixed window."""

    @pytest.mark.parametrize(
        "category", [ActivityCategory.TAMPERING, ActivityCategory.SABOTAGE]
    )
    def test_recent_tamper_is_on(self, category):
        events = [activity_event(category, time=panel_time(hours=1))]

        assert make_problem_sensor("tamper", events).is_on is True

    def test_stale_tamper_expires(self):
        events = [activity_event(ActivityCategory.TAMPERING, time=panel_time(hours=25))]

        assert make_problem_sensor("tamper", events).is_on is False

    @pytest.mark.parametrize("time", ["", "not-a-timestamp"])
    def test_unparseable_timestamp_fails_loud(self, time):
        """A safety sensor prefers a false alert to a silent miss."""
        events = [activity_event(ActivityCategory.TAMPERING, time=time)]

        assert make_problem_sensor("tamper", events).is_on is True

    def test_future_timestamp_is_on(self):
        """Panel clock ahead of HA's must not read as expired."""
        future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        events = [activity_event(ActivityCategory.TAMPERING, time=future)]

        assert make_problem_sensor("tamper", events).is_on is True


class TestInjectedAndDuplicateFiltering:
    """Injected rows are HA's own; duplicate echoes are the panel's."""

    def test_injected_communication_failure_is_ignored(self):
        """There is no injectable COMMUNICATION_RESTORED — this would latch forever."""
        events = [activity_event(ActivityCategory.COMMUNICATION_FAILED, injected=True)]

        assert make_problem_sensor("communication_problem", events).is_on is False

    def test_injected_failure_does_not_mask_an_older_restore(self):
        events = [
            activity_event(
                ActivityCategory.COMMUNICATION_FAILED,
                time="2026-08-09 10:05:00",
                injected=True,
            ),
            activity_event(
                ActivityCategory.COMMUNICATION_RESTORED, time="2026-08-09 10:00:00"
            ),
        ]

        assert make_problem_sensor("communication_problem", events).is_on is False

    def test_duplicate_echo_still_counts(self):
        """A duplicate_of row is the panel's own record, with authoritative data."""
        events = [activity_event(ActivityCategory.ALARM, duplicate_of="ha-1")]

        assert make_problem_sensor("alarm_triggered", events).is_on is True

    def test_injected_disarm_does_not_clear_an_alarm(self):
        """HA sent a disarm; until the panel echoes it the alarm still stands."""
        events = [
            activity_event(
                ActivityCategory.DISARMED, time="2026-08-09 10:05:00", injected=True
            ),
            activity_event(ActivityCategory.ALARM, time="2026-08-09 10:00:00"),
        ]

        assert make_problem_sensor("alarm_triggered", events).is_on is True


class TestPanelProblemAttributes:
    """extra_state_attributes describe the decisive event."""

    def test_none_when_no_decisive_event(self):
        assert make_problem_sensor("alarm_triggered", []).extra_state_attributes is None

    def test_describes_the_decisive_event(self):
        events = [
            activity_event(
                ActivityCategory.SABOTAGE,
                time=panel_time(hours=1),
                alias="Panel",
                idSignal="sig-9",
                deviceName="CE01",
            )
        ]

        attrs = make_problem_sensor("tamper", events).extra_state_attributes

        assert attrs == {
            "problem_category": "sabotage",
            "last_event_time": events[0].time,
            "last_event_alias": "Panel",
            "last_event_id_signal": "sig-9",
            "last_event_device": "CE01",
        }

    def test_reports_the_decisive_event_not_the_newest_row(self):
        events = [
            activity_event(
                ActivityCategory.IMAGE_REQUEST, time="2026-08-09 10:05:00", alias="Cam"
            ),
            activity_event(
                ActivityCategory.POWER_CUT, time="2026-08-09 10:00:00", alias="Panel"
            ),
        ]

        attrs = make_problem_sensor("power_cut", events).extra_state_attributes

        assert attrs is not None
        assert attrs["last_event_alias"] == "Panel"

    def test_decisive_event_is_memoised_per_payload(self):
        """Four sensors read the same payload on every state write."""
        sensor = make_problem_sensor(
            "alarm_triggered", [activity_event(ActivityCategory.ALARM)]
        )

        first = sensor._decisive_event()
        assert sensor._decisive_event() is first

        sensor.coordinator.data = ActivityData(
            events=[activity_event(ActivityCategory.ALARM)]
        )
        assert sensor._decisive_event() is not first

    def test_decisive_event_is_none_without_data(self):
        assert (
            make_problem_sensor("tamper", data_is_none=True)._decisive_event() is None
        )

    def test_attributes_are_memoised_per_payload(self):
        sensor = make_problem_sensor(
            "alarm_triggered", [activity_event(ActivityCategory.ALARM)]
        )

        first = sensor.extra_state_attributes
        assert sensor.extra_state_attributes is first

        sensor.coordinator.data = ActivityData(
            events=[activity_event(ActivityCategory.ALARM)]
        )
        assert sensor.extra_state_attributes is not first


# ===========================================================================
# Zone exception sensors
# ===========================================================================


def make_alarm_data(exceptions: list[dict] | None = None) -> AlarmStatusData:
    """Build coordinator payload with an xSStatus exceptions list."""
    return AlarmStatusData(status=SStatus(status="D", exceptions=exceptions))


def make_zone_coordinator(exceptions: list[dict] | None = None) -> AlarmCoordinator:
    """Build a real AlarmCoordinator without running its HA-bound __init__.

    Real rather than mocked: the exception parsing and its memo are the
    contract these sensors are built on, so the tests should exercise them
    rather than a hand-rolled stand-in.
    """
    coordinator = AlarmCoordinator.__new__(AlarmCoordinator)
    coordinator._exc_cache_data = None
    coordinator._exc_keys = {}
    coordinator._exc_aliases = ()
    coordinator.data = make_alarm_data(exceptions)
    return coordinator


def zone_exception(alias: str, status: str, device_type: str = "MG") -> dict:
    """One raw xSStatus exception row."""
    return {"status": status, "deviceType": device_type, "alias": alias}


class TestAliasMatching:
    """The inventory-name to panel-alias join."""

    def test_exact_match(self):
        assert alias_matches("Ptaentrada", "Ptaentrada") is True

    def test_strips_surrounding_whitespace(self):
        assert alias_matches(" Ptaentrada ", "Ptaentrada") is True

    def test_truncated_alias_matches_longer_name(self):
        assert alias_matches("Pfincameret", "Pfincameretta") is True

    def test_case_difference_does_not_match(self):
        """Casefolding would collapse short accented labels into collisions."""
        assert alias_matches("PTAENTRADA", "Ptaentrada") is False

    def test_short_labels_never_prefix_match(self):
        assert alias_matches("Vb", "Vbano") is False

    def test_unrelated_labels_do_not_match(self):
        assert alias_matches("Ventana", "Ptacocina") is False

    def test_empty_never_matches(self):
        assert alias_matches("", "Ptaentrada") is False
        assert alias_matches("Ptaentrada", "") is False

    def test_ambiguous_prefix_resolves_to_nothing(self):
        """Dorm plausibly denotes Dorm1 and Dorm2 — reporting either is wrong."""
        keys = {"Dorm1": frozenset({"open"}), "Dorm2": frozenset({"open"})}

        assert match_exception_keys(keys, "Dorm") == frozenset()

    def test_unique_prefix_resolves(self):
        keys = {"Pfincameret": frozenset({"battery_low"})}

        assert match_exception_keys(keys, "Pfincameretta") == frozenset({"battery_low"})

    def test_exact_key_wins_over_prefix_candidates(self):
        keys = {
            "Dorm1": frozenset({"open"}),
            "Dorm12": frozenset({"battery_low"}),
        }

        assert match_exception_keys(keys, "Dorm1") == frozenset({"open"})

    def test_no_match_returns_empty(self):
        assert match_exception_keys({"Ventana": frozenset({"open"})}, "") == frozenset()


class TestZoneAliasSlug:
    """unique_id fragments for zones known only by name."""

    def test_lowercases_and_replaces_separators(self):
        assert zone_alias_slug("Porta 1 Cucina") == "porta_1_cucina"

    def test_strips_accents_to_separators(self):
        assert zone_alias_slug("Vbaño") == "vba_o"

    def test_trims_leading_and_trailing_separators(self):
        assert zone_alias_slug("  -Hall-  ") == "hall"


class TestZoneAggregates:
    """Installation-wide roll-ups over the sparse exceptions list."""

    def test_unique_ids(self):
        installation = make_installation()
        coordinator = make_zone_coordinator()

        assert (
            ArmingExceptionsSensor(coordinator, installation)._attr_unique_id
            == "v4_securitas_direct.123456_zones_open"
        )
        assert (
            ZonesBatteryLowSensor(coordinator, installation)._attr_unique_id
            == "v4_securitas_direct.123456_zones_battery_low"
        )

    def test_entity_metadata(self):
        installation = make_installation(alias="Office")
        coordinator = make_zone_coordinator()

        open_sensor = ArmingExceptionsSensor(coordinator, installation)
        battery_sensor = ZonesBatteryLowSensor(coordinator, installation)

        # PROBLEM, not OPENING: the panel reports these only while armed, so
        # this is "armed with a zone bypassed", not "a door is open".
        assert open_sensor._attr_device_class == BinarySensorDeviceClass.PROBLEM
        # Not diagnostic: arming over an open door belongs on a dashboard.
        # Read the public property — HA only materialises the _attr_ backing
        # field when a subclass assigns it.
        assert open_sensor.entity_category is None
        assert battery_sensor._attr_device_class == BinarySensorDeviceClass.BATTERY
        assert battery_sensor.entity_category == EntityCategory.DIAGNOSTIC
        for sensor in (open_sensor, battery_sensor):
            assert sensor._attr_has_entity_name is True
            assert sensor._attr_should_poll is False
            assert "Office" not in (sensor._attr_name or "")

    def test_unknown_before_any_data(self):
        coordinator = make_zone_coordinator()
        coordinator.data = None

        assert ArmingExceptionsSensor(coordinator, make_installation()).is_on is None

    def test_off_when_the_panel_flags_nothing(self):
        """The panel sends null both while disarmed and while armed-and-clear.

        Under "arming exception" semantics off is honest in both cases: there
        genuinely is no exception. Only a missing payload is unknown.
        """
        for payload in (None, []):
            coordinator = make_zone_coordinator(payload)

            assert (
                ArmingExceptionsSensor(coordinator, make_installation()).is_on is False
            )

    def test_clears_when_the_exception_goes_away(self):
        coordinator = make_zone_coordinator([zone_exception("Ventana", "0")])
        sensor = ArmingExceptionsSensor(coordinator, make_installation())
        assert sensor.is_on is True

        coordinator.data = make_alarm_data(None)
        assert sensor.is_on is False

    def test_open_and_battery_do_not_cross_talk(self):
        coordinator = make_zone_coordinator([zone_exception("Ventana", "0")])
        installation = make_installation()

        assert ArmingExceptionsSensor(coordinator, installation).is_on is True
        assert ZonesBatteryLowSensor(coordinator, installation).is_on is False

    def test_attributes_list_affected_zones(self):
        coordinator = make_zone_coordinator(
            [
                zone_exception("Ventana", "0"),
                zone_exception("Pfincameret", "2"),
                zone_exception("Ptacocina", "0"),
            ]
        )
        installation = make_installation()

        assert ArmingExceptionsSensor(
            coordinator, installation
        ).extra_state_attributes == {
            "zones": ["Ventana", "Ptacocina"],
            "count": 2,
        }
        assert ZonesBatteryLowSensor(
            coordinator, installation
        ).extra_state_attributes == {"zones": ["Pfincameret"], "count": 1}

    def test_attributes_include_zones_absent_from_inventory(self):
        """Aggregates read the panel's raw list, so nothing is ever dropped."""
        coordinator = make_zone_coordinator([zone_exception("Neverseen", "0", "ZZ")])

        attrs = ArmingExceptionsSensor(
            coordinator, make_installation()
        ).extra_state_attributes

        assert attrs["zones"] == ["Neverseen"]

    def test_attributes_are_memoised_per_payload(self):
        coordinator = make_zone_coordinator([zone_exception("Ventana", "0")])
        sensor = ArmingExceptionsSensor(coordinator, make_installation())

        first = sensor.extra_state_attributes
        assert sensor.extra_state_attributes is first

        coordinator.data = make_alarm_data([zone_exception("Ventana", "0")])
        assert sensor.extra_state_attributes is not first


class TestZoneSensors:
    """Per-zone entities on their own child devices."""

    def test_inventory_zone_unique_ids(self):
        target = ZoneTarget.from_device(
            PanelDevice(
                id="5", code=4, zone_id="MG04", name="Ptaentrada", device_type="MG"
            )
        )
        coordinator = make_zone_coordinator()
        installation = make_installation()

        assert (
            ZoneArmingExceptionSensor(coordinator, installation, target)._attr_unique_id
            == "v4_securitas_direct.123456_zone_MG04"
        )
        assert (
            ZoneBatteryLowSensor(coordinator, installation, target)._attr_unique_id
            == "v4_securitas_direct.123456_zone_battery_MG04"
        )

    def test_orphan_zone_unique_ids(self):
        target = ZoneTarget.from_alias("Porta1cucin")
        coordinator = make_zone_coordinator()
        installation = make_installation()

        assert (
            ZoneArmingExceptionSensor(coordinator, installation, target)._attr_unique_id
            == "v4_securitas_direct.123456_zone_alias_porta1cucin"
        )
        assert (
            ZoneBatteryLowSensor(coordinator, installation, target)._attr_unique_id
            == "v4_securitas_direct.123456_zone_battery_alias_porta1cucin"
        )

    def test_device_info_links_to_the_installation(self):
        target = ZoneTarget.from_device(
            PanelDevice(zone_id="MG04", name="Ptaentrada", device_type="MG")
        )
        sensor = ZoneArmingExceptionSensor(
            make_zone_coordinator(), make_installation(), target
        )

        info = sensor._attr_device_info
        assert info is not None
        assert (
            "securitas",
            "v4_securitas_direct.123456_zone_MG04",
        ) in info["identifiers"]
        assert info["via_device"] == ("securitas", "v4_securitas_direct.123456")
        assert info["model"] == "Magnetic contact"

    def test_off_when_the_panel_flags_nothing(self):
        """Disarmed, or armed and clear, the panel sends null — that is "off"."""
        target = ZoneTarget.from_alias("Ventana")

        assert (
            ZoneArmingExceptionSensor(
                make_zone_coordinator(None), make_installation(), target
            ).is_on
            is False
        )

    def test_unknown_before_any_data(self):
        coordinator = make_zone_coordinator()
        coordinator.data = None
        target = ZoneTarget.from_alias("Ventana")

        assert (
            ZoneArmingExceptionSensor(coordinator, make_installation(), target).is_on
            is None
        )

    def test_device_class_and_category(self):
        """The aggregate is the dashboard tile; per-zone detail is diagnostic."""
        target = ZoneTarget.from_alias("Ventana")
        sensor = ZoneArmingExceptionSensor(
            make_zone_coordinator(), make_installation(), target
        )

        assert sensor._attr_device_class == BinarySensorDeviceClass.PROBLEM
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_reports_its_own_zone_only(self):
        coordinator = make_zone_coordinator([zone_exception("Ventana", "0")])
        installation = make_installation()

        assert (
            ZoneArmingExceptionSensor(
                coordinator, installation, ZoneTarget.from_alias("Ventana")
            ).is_on
            is True
        )
        assert (
            ZoneArmingExceptionSensor(
                coordinator, installation, ZoneTarget.from_alias("Ptacocina")
            ).is_on
            is False
        )

    def test_open_and_battery_are_independent(self):
        coordinator = make_zone_coordinator(
            [zone_exception("Ventana", "0"), zone_exception("Ventana", "2")]
        )
        target = ZoneTarget.from_alias("Ventana")
        installation = make_installation()

        assert (
            ZoneArmingExceptionSensor(coordinator, installation, target).is_on is True
        )
        assert ZoneBatteryLowSensor(coordinator, installation, target).is_on is True

    def test_truncated_panel_alias_still_matches_the_inventory_name(self):
        coordinator = make_zone_coordinator([zone_exception("Pfincameret", "0")])
        target = ZoneTarget.from_device(
            PanelDevice(zone_id="MG11", name="Pfincameretta", device_type="MG")
        )

        assert (
            ZoneArmingExceptionSensor(coordinator, make_installation(), target).is_on
            is True
        )

    def test_unknown_status_code_counts_as_neither(self):
        coordinator = make_zone_coordinator([zone_exception("Ventana", "9")])
        target = ZoneTarget.from_alias("Ventana")
        installation = make_installation()

        assert (
            ZoneArmingExceptionSensor(coordinator, installation, target).is_on is False
        )
        assert ZoneBatteryLowSensor(coordinator, installation, target).is_on is False

    def test_attributes_expose_panel_identifiers(self):
        target = ZoneTarget.from_device(
            PanelDevice(zone_id="MG04", name="Ptaentrada", device_type="MG")
        )
        sensor = ZoneArmingExceptionSensor(
            make_zone_coordinator(), make_installation(), target
        )

        assert sensor.extra_state_attributes == {
            "zone_key": "MG04",
            "panel_alias": "Ptaentrada",
        }

    def test_build_zone_entities_pairs_each_target(self):
        targets = [ZoneTarget.from_alias("Ventana"), ZoneTarget.from_alias("Ptacocina")]

        entities = build_zone_entities(
            make_zone_coordinator(), make_installation(), targets
        )

        assert len(entities) == 4
        assert sum(isinstance(e, ZoneArmingExceptionSensor) for e in entities) == 2
        assert sum(isinstance(e, ZoneBatteryLowSensor) for e in entities) == 2
