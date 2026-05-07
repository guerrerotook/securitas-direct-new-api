"""Tests for the legacy → v5 unique-id and identifier mapping."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.verisure_owa.migrate import (
    old_to_new_identifier,
    old_to_new_unique_id,
    migrate_legacy_entry,
)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # Alarm panel
        ("v4_securitas_direct.100001", "v5_verisure_owa.100001"),
        # Sensors
        ("v4_100001_temperature_5", "v5_verisure_owa.100001_temperature_5"),
        ("v4_100001_humidity_5", "v5_verisure_owa.100001_humidity_5"),
        ("v4_100001_airquality_5", "v5_verisure_owa.100001_airquality_5"),
        ("v4_100001_airquality_status_5", "v5_verisure_owa.100001_airquality_status_5"),
        # Cameras
        ("v4_100001_camera_YR08", "v5_verisure_owa.100001_camera_YR08"),
        ("v4_100001_camera_full_YR08", "v5_verisure_owa.100001_camera_full_YR08"),
        # Capture button
        ("v4_100001_capture_YR08", "v5_verisure_owa.100001_capture_YR08"),
        # Refresh button (note format reorder)
        ("v4_refresh_button_100001", "v5_verisure_owa.100001_refresh_button"),
        # WiFi binary sensor
        ("v4_100001_wifi_connected", "v5_verisure_owa.100001_wifi_connected"),
        # Lock
        (
            "v4_securitas_direct.100001_lock_01",
            "v5_verisure_owa.100001_lock_01",
        ),
    ],
)
def test_unique_id_mapping(old, new):
    assert old_to_new_unique_id(old) == new


def test_unique_id_mapping_already_migrated_is_idempotent():
    """If the input is already in v5 form, return it unchanged."""
    new = "v5_verisure_owa.100001_temperature_5"
    assert old_to_new_unique_id(new) == new


def test_unique_id_mapping_unknown_format_raises():
    with pytest.raises(ValueError):
        old_to_new_unique_id("zzz_unknown_format")


# ── Identifier (tuple) mapping ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # Alarm panel device id
        (
            ("securitas", "v4_securitas_direct.100001"),
            ("verisure_owa", "v5_verisure_owa.100001"),
        ),
        # Camera device id
        (
            ("securitas", "v4_securitas_direct.100001_camera_YR08"),
            ("verisure_owa", "v5_verisure_owa.100001_camera_YR08"),
        ),
        # Lock device id
        (
            ("securitas", "v4_securitas_direct.100001_lock_01"),
            ("verisure_owa", "v5_verisure_owa.100001_lock_01"),
        ),
    ],
)
def test_identifier_mapping(old, new):
    assert old_to_new_identifier(old) == new


def test_identifier_mapping_unknown_domain_returns_unchanged():
    """Identifiers under an unrelated domain are returned untouched."""
    other = ("hue", "abc123")
    assert old_to_new_identifier(other) == other


# ── End-to-end migration tests (Phase D) ─────────────────────────────────────


@pytest.fixture
def legacy_entry_with_state(hass: HomeAssistant):
    """Seed a 'securitas' config entry with representative registry state.

    Returns the entry so tests can drive migration on it.
    """
    entry = MockConfigEntry(
        domain="securitas",
        data={"username": "u@x", "password": "p", "country": "ES"},
        options={},
        title="My Home",
        unique_id="u@x:100001",
        version=3,
    )
    entry.add_to_hass(hass)

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    # Alarm panel device + entity
    panel_dev = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("securitas", "v4_securitas_direct.100001")},
        manufacturer="Securitas Direct",
        name="My Home",
    )
    ent_reg.async_get_or_create(
        domain="alarm_control_panel",
        platform="securitas",
        unique_id="v4_securitas_direct.100001",
        config_entry=entry,
        device_id=panel_dev.id,
        suggested_object_id="my_home",
    )

    # Lock device + entity (with via_device coupling)
    lock_dev = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("securitas", "v4_securitas_direct.100001_lock_01")},
        via_device=("securitas", "v4_securitas_direct.100001"),
        manufacturer="Securitas Direct",
        name="Front Door",
    )
    ent_reg.async_get_or_create(
        domain="lock",
        platform="securitas",
        unique_id="v4_securitas_direct.100001_lock_01",
        config_entry=entry,
        device_id=lock_dev.id,
    )

    # Sensor entity (under panel device)
    ent_reg.async_get_or_create(
        domain="sensor",
        platform="securitas",
        unique_id="v4_100001_temperature_5",
        config_entry=entry,
        device_id=panel_dev.id,
    )

    return entry


async def test_migration_creates_new_entry(hass, legacy_entry_with_state):
    """A new verisure_owa entry exists after migration with all original data preserved."""
    await migrate_legacy_entry(hass, legacy_entry_with_state)
    entries = hass.config_entries.async_entries("verisure_owa")
    assert len(entries) == 1
    new_entry = entries[0]
    # All original data is preserved (plus the migration flags)
    expected_data = {
        **dict(legacy_entry_with_state.data),
        "migrated_from_securitas": True,
        "unique_id_schema": "v5_verisure_owa",
    }
    assert dict(new_entry.data) == expected_data
    assert new_entry.title == legacy_entry_with_state.title
    assert new_entry.unique_id == legacy_entry_with_state.unique_id


async def test_migration_rewrites_alarm_panel_unique_id(hass, legacy_entry_with_state):
    await migrate_legacy_entry(hass, legacy_entry_with_state)
    ent_reg = er.async_get(hass)
    panel = ent_reg.async_get_entity_id(
        "alarm_control_panel", "verisure_owa", "v5_verisure_owa.100001"
    )
    assert panel is not None
    # Old unique_id no longer registered under either domain
    assert (
        ent_reg.async_get_entity_id(
            "alarm_control_panel", "securitas", "v4_securitas_direct.100001"
        )
        is None
    )


async def test_migration_rewrites_lock_unique_id_and_identifier(
    hass, legacy_entry_with_state
):
    await migrate_legacy_entry(hass, legacy_entry_with_state)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    lock_id = ent_reg.async_get_entity_id(
        "lock", "verisure_owa", "v5_verisure_owa.100001_lock_01"
    )
    assert lock_id is not None

    # Lock's via_device still resolves to the alarm panel device.
    lock_dev = dev_reg.async_get(ent_reg.async_get(lock_id).device_id)
    assert ("verisure_owa", "v5_verisure_owa.100001_lock_01") in lock_dev.identifiers
    via = lock_dev.via_device_id  # device_id, not identifier tuple
    assert via is not None
    panel_dev = dev_reg.async_get(via)
    assert ("verisure_owa", "v5_verisure_owa.100001") in panel_dev.identifiers


async def test_migration_rewrites_sensor_unique_id(hass, legacy_entry_with_state):
    await migrate_legacy_entry(hass, legacy_entry_with_state)
    ent_reg = er.async_get(hass)
    sensor_id = ent_reg.async_get_entity_id(
        "sensor", "verisure_owa", "v5_verisure_owa.100001_temperature_5"
    )
    assert sensor_id is not None


async def test_migration_marks_entry_complete(hass, legacy_entry_with_state):
    await migrate_legacy_entry(hass, legacy_entry_with_state)
    new_entry = hass.config_entries.async_entries("verisure_owa")[0]
    assert new_entry.data.get("migrated_from_securitas") is True
    assert new_entry.data.get("unique_id_schema") == "v5_verisure_owa"


async def test_migration_is_idempotent(hass, legacy_entry_with_state):
    """Running migration twice does not duplicate the new entry or rewrite again."""
    await migrate_legacy_entry(hass, legacy_entry_with_state)
    await migrate_legacy_entry(hass, legacy_entry_with_state)
    assert len(hass.config_entries.async_entries("verisure_owa")) == 1


async def test_migration_preserves_user_customizations(hass, legacy_entry_with_state):
    """Custom name and area_id are preserved."""
    ent_reg = er.async_get(hass)
    sensor_eid = ent_reg.async_get_entity_id(
        "sensor", "securitas", "v4_100001_temperature_5"
    )
    ent_reg.async_update_entity(
        sensor_eid,
        name="Living Room Temp",
        area_id="living_room",
    )

    await migrate_legacy_entry(hass, legacy_entry_with_state)

    new_eid = ent_reg.async_get_entity_id(
        "sensor", "verisure_owa", "v5_verisure_owa.100001_temperature_5"
    )
    new_entry = ent_reg.async_get(new_eid)
    assert new_entry.name == "Living Room Temp"
    assert new_entry.area_id == "living_room"


async def test_migration_rejects_wrong_domain(hass):
    """Calling with a non-securitas entry returns without creating new state."""
    wrong = MockConfigEntry(
        domain="verisure_owa",
        unique_id="x",
        data={"username": "u@x", "password": "p", "country": "ES"},
        version=3,
    )
    wrong.add_to_hass(hass)

    # Capture entry count before
    before = len(hass.config_entries.async_entries("verisure_owa"))

    # Function should log error and return cleanly (no exception)
    await migrate_legacy_entry(hass, wrong)

    after = len(hass.config_entries.async_entries("verisure_owa"))
    assert after == before  # no new entry created


# ── 5.1 Multi-installation migration ─────────────────────────────────────────


@pytest.fixture
def two_legacy_entries(hass: HomeAssistant):
    """Seed TWO independent 'securitas' config entries (different accounts/countries).

    Returns (entry1, entry2) so tests can drive migration on each independently.
    """
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    # --- Entry 1: ES account, installation 100001 ---
    entry1 = MockConfigEntry(
        domain="securitas",
        data={"username": "u1@x", "password": "p1", "country": "ES"},
        options={},
        title="ES Home",
        unique_id="u1@x:100001",
        version=3,
    )
    entry1.add_to_hass(hass)

    panel_dev1 = dev_reg.async_get_or_create(
        config_entry_id=entry1.entry_id,
        identifiers={("securitas", "v4_securitas_direct.100001")},
        manufacturer="Securitas Direct",
        name="ES Home",
    )
    ent_reg.async_get_or_create(
        domain="alarm_control_panel",
        platform="securitas",
        unique_id="v4_securitas_direct.100001",
        config_entry=entry1,
        device_id=panel_dev1.id,
        suggested_object_id="es_home",
    )

    # --- Entry 2: IT account, installation 200002 ---
    entry2 = MockConfigEntry(
        domain="securitas",
        data={"username": "u2@x", "password": "p2", "country": "IT"},
        options={},
        title="IT Home",
        unique_id="u2@x:200002",
        version=3,
    )
    entry2.add_to_hass(hass)

    panel_dev2 = dev_reg.async_get_or_create(
        config_entry_id=entry2.entry_id,
        identifiers={("securitas", "v4_securitas_direct.200002")},
        manufacturer="Securitas Direct",
        name="IT Home",
    )
    ent_reg.async_get_or_create(
        domain="alarm_control_panel",
        platform="securitas",
        unique_id="v4_securitas_direct.200002",
        config_entry=entry2,
        device_id=panel_dev2.id,
        suggested_object_id="it_home",
    )

    return entry1, entry2


async def test_multi_installation_migration_independent(hass, two_legacy_entries):
    """Two legacy entries migrate independently with no cross-entry collision."""
    entry1, entry2 = two_legacy_entries

    await migrate_legacy_entry(hass, entry1)
    await migrate_legacy_entry(hass, entry2)

    owa_entries = hass.config_entries.async_entries("verisure_owa")
    assert len(owa_entries) == 2

    by_uid = {e.unique_id: e for e in owa_entries}
    assert "u1@x:100001" in by_uid
    assert "u2@x:200002" in by_uid

    # Each entry's data preserves its original country
    assert by_uid["u1@x:100001"].data["country"] == "ES"
    assert by_uid["u2@x:200002"].data["country"] == "IT"

    dev_reg = dr.async_get(hass)

    # Both alarm panel devices exist under the new domain with distinct identifiers
    panel1 = dev_reg.async_get_device(
        identifiers={("verisure_owa", "v5_verisure_owa.100001")}
    )
    panel2 = dev_reg.async_get_device(
        identifiers={("verisure_owa", "v5_verisure_owa.200002")}
    )
    assert panel1 is not None, "ES panel device not found after migration"
    assert panel2 is not None, "IT panel device not found after migration"
    assert panel1.id != panel2.id, "Panel devices must be distinct objects"

    # No legacy identifiers remain on either device
    assert ("securitas", "v4_securitas_direct.100001") not in panel1.identifiers
    assert ("securitas", "v4_securitas_direct.200002") not in panel2.identifiers

    # Migrating entry1 did not touch entry2's device (and vice versa)
    ent_reg = er.async_get(hass)
    panel1_eid = ent_reg.async_get_entity_id(
        "alarm_control_panel", "verisure_owa", "v5_verisure_owa.100001"
    )
    panel2_eid = ent_reg.async_get_entity_id(
        "alarm_control_panel", "verisure_owa", "v5_verisure_owa.200002"
    )
    assert panel1_eid is not None
    assert panel2_eid is not None

    # Each entity belongs to the correct new config entry
    assert (
        ent_reg.async_get(panel1_eid).config_entry_id == by_uid["u1@x:100001"].entry_id
    )
    assert (
        ent_reg.async_get(panel2_eid).config_entry_id == by_uid["u2@x:200002"].entry_id
    )


# ── 5.2 Camera device end-to-end migration ───────────────────────────────────


@pytest.fixture
def legacy_entry_with_camera(hass: HomeAssistant):
    """Seed a 'securitas' config entry with an alarm panel and a camera device.

    The camera device has thumbnail, full-image, and capture-button entities.
    Returns the entry so tests can drive migration on it.
    """
    entry = MockConfigEntry(
        domain="securitas",
        data={"username": "u@x", "password": "p", "country": "ES"},
        options={},
        title="My Home",
        unique_id="u@x:100001",
        version=3,
    )
    entry.add_to_hass(hass)

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    # Alarm panel device
    panel_dev = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("securitas", "v4_securitas_direct.100001")},
        manufacturer="Securitas Direct",
        name="My Home",
    )
    ent_reg.async_get_or_create(
        domain="alarm_control_panel",
        platform="securitas",
        unique_id="v4_securitas_direct.100001",
        config_entry=entry,
        device_id=panel_dev.id,
        suggested_object_id="my_home",
    )

    # Camera device (via_device → alarm panel)
    camera_dev = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("securitas", "v4_securitas_direct.100001_camera_YR08")},
        via_device=("securitas", "v4_securitas_direct.100001"),
        manufacturer="Securitas Direct",
        name="Camera YR08",
    )

    # Thumbnail camera entity
    ent_reg.async_get_or_create(
        domain="camera",
        platform="securitas",
        unique_id="v4_100001_camera_YR08",
        config_entry=entry,
        device_id=camera_dev.id,
        suggested_object_id="camera_yr08",
    )

    # Full-image camera entity
    ent_reg.async_get_or_create(
        domain="camera",
        platform="securitas",
        unique_id="v4_100001_camera_full_YR08",
        config_entry=entry,
        device_id=camera_dev.id,
        suggested_object_id="camera_full_yr08",
    )

    # Capture button entity
    ent_reg.async_get_or_create(
        domain="button",
        platform="securitas",
        unique_id="v4_100001_capture_YR08",
        config_entry=entry,
        device_id=camera_dev.id,
        suggested_object_id="capture_yr08",
    )

    return entry


async def test_migration_rewrites_camera_device_identifiers(
    hass, legacy_entry_with_camera
):
    """Camera device identifiers are rewritten to the v5_verisure_owa.* schema."""
    await migrate_legacy_entry(hass, legacy_entry_with_camera)

    dev_reg = dr.async_get(hass)

    camera_dev = dev_reg.async_get_device(
        identifiers={("verisure_owa", "v5_verisure_owa.100001_camera_YR08")}
    )
    assert camera_dev is not None, "Camera device not found under new identifier"

    # Legacy identifier is gone
    assert (
        "securitas",
        "v4_securitas_direct.100001_camera_YR08",
    ) not in camera_dev.identifiers

    # via_device resolves to the alarm panel under the new domain
    assert camera_dev.via_device_id is not None
    panel_dev = dev_reg.async_get(camera_dev.via_device_id)
    assert panel_dev is not None
    assert ("verisure_owa", "v5_verisure_owa.100001") in panel_dev.identifiers


async def test_migration_rewrites_camera_entity_unique_ids(
    hass, legacy_entry_with_camera
):
    """Camera thumbnail, full-image, and capture button unique_ids are rewritten."""
    await migrate_legacy_entry(hass, legacy_entry_with_camera)

    ent_reg = er.async_get(hass)

    thumbnail_eid = ent_reg.async_get_entity_id(
        "camera", "verisure_owa", "v5_verisure_owa.100001_camera_YR08"
    )
    assert thumbnail_eid is not None, "Thumbnail camera entity not found"

    full_eid = ent_reg.async_get_entity_id(
        "camera", "verisure_owa", "v5_verisure_owa.100001_camera_full_YR08"
    )
    assert full_eid is not None, "Full-image camera entity not found"

    capture_eid = ent_reg.async_get_entity_id(
        "button", "verisure_owa", "v5_verisure_owa.100001_capture_YR08"
    )
    assert capture_eid is not None, "Capture button entity not found"
