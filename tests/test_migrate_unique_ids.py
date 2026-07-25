"""Tests for the registry-rewrite that normalises pre-v5 entity unique_ids
to the v5.0.2 canonical ``v4_securitas_direct.<num>_<type>`` form.

The pre-v5 schema was inconsistent — alarm panel and lock used the dotted,
branded prefix, but every other entity used a bare ``v4_<num>_<type>`` or
the special-case ``v4_refresh_button_<num>``. v5.0.2 unifies all generated
unique_ids onto the dotted form; this migration rewrites existing
registry entries from any pre-v5 shape to that canonical shape, so
HACS upgraders don't see duplicated entities with ``_2`` suffixes.
"""

from __future__ import annotations

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.securitas.const import DOMAIN
from custom_components.securitas.migrate_unique_ids import (
    canonical_unique_id,
    migrate_unique_ids,
)


class TestCanonicalUniqueId:
    """Pure-function tests for the per-id mapper."""

    def test_already_canonical_passes_through(self):
        """Entries already on v4_securitas_direct.* are returned unchanged."""
        assert (
            canonical_unique_id("v4_securitas_direct.2654190")
            == "v4_securitas_direct.2654190"
        )
        assert (
            canonical_unique_id("v4_securitas_direct.2654190_lock_01")
            == "v4_securitas_direct.2654190_lock_01"
        )

    def test_bare_v4_num_type_form_gets_branded_prefix(self):
        """v4_<num>_<type> → v4_securitas_direct.<num>_<type>."""
        assert (
            canonical_unique_id("v4_2654190_wifi_connected")
            == "v4_securitas_direct.2654190_wifi_connected"
        )
        assert (
            canonical_unique_id("v4_2654190_camera_QR10")
            == "v4_securitas_direct.2654190_camera_QR10"
        )
        assert (
            canonical_unique_id("v4_2654190_camera_full_QR10")
            == "v4_securitas_direct.2654190_camera_full_QR10"
        )
        assert (
            canonical_unique_id("v4_2654190_capture_QR10")
            == "v4_securitas_direct.2654190_capture_QR10"
        )

    def test_sentinel_sensor_forms(self):
        """v4_<num>_<sensor>_<svc_id> forms (temperature, humidity, etc.)."""
        for sensor in (
            "temperature",
            "humidity",
            "airquality",
            "airquality_status",
        ):
            assert (
                canonical_unique_id(f"v4_2654190_{sensor}_5")
                == f"v4_securitas_direct.2654190_{sensor}_5"
            )

    def test_refresh_button_reorders(self):
        """v4_refresh_button_<num> → v4_securitas_direct.<num>_refresh_button.

        The pre-v5 refresh button had the type before the installation
        number — the only entity in the integration with that ordering.
        """
        assert (
            canonical_unique_id("v4_refresh_button_2654190")
            == "v4_securitas_direct.2654190_refresh_button"
        )

    def test_unrecognised_form_returns_none(self):
        """An unrecognised unique_id is left alone (returns None)."""
        assert canonical_unique_id("v3_legacy_format") is None
        assert canonical_unique_id("totally_unrelated") is None
        # A multi-installation entry from a 3rd-party fork
        assert canonical_unique_id("v4_invalid") is None


@pytest.mark.asyncio
async def test_migrate_unique_ids_rewrites_pre_v5_entries(hass) -> None:
    """End-to-end: register pre-v5 entries and confirm migrate rewrites them
    to the canonical form, preserving entity_id."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    registry = er.async_get(hass)
    # The pre-v5 mix that an upgrader's registry might hold:
    fixtures = [
        # (platform, unique_id, expected_after_migration)
        (
            "sensor",
            "v4_2654190_temperature_5",
            "v4_securitas_direct.2654190_temperature_5",
        ),
        (
            "binary_sensor",
            "v4_2654190_wifi_connected",
            "v4_securitas_direct.2654190_wifi_connected",
        ),
        (
            "button",
            "v4_refresh_button_2654190",
            "v4_securitas_direct.2654190_refresh_button",
        ),
        (
            "camera",
            "v4_2654190_camera_QR10",
            "v4_securitas_direct.2654190_camera_QR10",
        ),
        # An already-canonical entry: must be left alone.
        (
            "alarm_control_panel",
            "v4_securitas_direct.2654190",
            "v4_securitas_direct.2654190",
        ),
        (
            "lock",
            "v4_securitas_direct.2654190_lock_01",
            "v4_securitas_direct.2654190_lock_01",
        ),
    ]

    created_entity_ids: dict[str, str] = {}
    for platform, old_uid, _ in fixtures:
        registry_entry = registry.async_get_or_create(
            domain=platform,
            platform=DOMAIN,
            unique_id=old_uid,
            config_entry=entry,
        )
        created_entity_ids[old_uid] = registry_entry.entity_id

    await migrate_unique_ids(hass, entry)

    # Walk fixtures and confirm the unique_id is the expected canonical form,
    # AND that the entity_id is unchanged (registry treats this as the same row).
    for _, old_uid, new_uid in fixtures:
        original_entity_id = created_entity_ids[old_uid]
        live = registry.async_get(original_entity_id)
        assert live is not None, f"entity_id {original_entity_id} disappeared"
        assert live.unique_id == new_uid, (
            f"expected {new_uid!r}, got {live.unique_id!r}"
        )


@pytest.mark.asyncio
async def test_migrate_unique_ids_is_idempotent(hass) -> None:
    """Calling migrate twice is a no-op on the second call."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="sensor",
        platform=DOMAIN,
        unique_id="v4_2654190_temperature_5",
        config_entry=entry,
    )

    await migrate_unique_ids(hass, entry)
    after_first = {e.unique_id for e in registry.entities.values()}

    await migrate_unique_ids(hass, entry)
    after_second = {e.unique_id for e in registry.entities.values()}

    assert after_first == after_second
    assert "v4_securitas_direct.2654190_temperature_5" in after_first


@pytest.mark.asyncio
async def test_migrate_unique_ids_leaves_other_integrations_alone(hass) -> None:
    """Entries in our config_entry but with platform != DOMAIN are skipped.

    (HA's async_migrate_entries already filters by config_entry_id, so an
    entry from a different integration can't reach our callback at all —
    but we belt-and-braces test that non-securitas registry entries are
    untouched if they happen to share the entry.)
    """
    securitas_entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="sec-1")
    securitas_entry.add_to_hass(hass)
    other_entry = MockConfigEntry(domain="some_other", data={}, entry_id="oth-1")
    other_entry.add_to_hass(hass)

    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="sensor",
        platform="some_other",
        unique_id="v4_2654190_temperature_5",  # would look like ours, but isn't
        config_entry=other_entry,
    )

    await migrate_unique_ids(hass, securitas_entry)

    # The other integration's entry was untouched.
    other_entity = next(
        (e for e in registry.entities.values() if e.config_entry_id == "oth-1"),
        None,
    )
    assert other_entity is not None
    assert other_entity.unique_id == "v4_2654190_temperature_5"
