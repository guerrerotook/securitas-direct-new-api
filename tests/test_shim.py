"""Tests for the legacy 'securitas' shim that triggers migration."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_get_persistent_notifications,
)


async def test_shim_migrates_and_removes_self(hass: HomeAssistant):
    """Loading a legacy entry triggers migration and the legacy entry is removed."""
    from custom_components.securitas import async_setup_entry as shim_setup

    legacy = MockConfigEntry(
        domain="securitas",
        data={"username": "u@x", "password": "p", "country": "ES"},
        title="Home",
        unique_id="u@x:100001",
        version=3,
    )
    legacy.add_to_hass(hass)

    result = await shim_setup(hass, legacy)
    await hass.async_block_till_done()

    # Shim returns False — it intentionally does NOT set up the legacy entry.
    assert result is False

    # New entry exists
    assert len(hass.config_entries.async_entries("verisure_owa")) == 1
    # Legacy entry has been removed
    assert legacy not in hass.config_entries.async_entries("securitas")


async def test_shim_setup_idempotent_when_already_migrated(hass: HomeAssistant):
    """Re-running the shim with an already-migrated legacy entry is a no-op."""
    from custom_components.securitas import async_setup_entry as shim_setup

    new_entry = MockConfigEntry(
        domain="verisure_owa",
        data={"username": "u@x", "password": "p", "country": "ES"},
        unique_id="u@x:100001",
        version=3,
    )
    new_entry.add_to_hass(hass)

    legacy = MockConfigEntry(
        domain="securitas",
        data={"username": "u@x", "password": "p", "country": "ES"},
        unique_id="u@x:100001",
        version=3,
    )
    legacy.add_to_hass(hass)

    await shim_setup(hass, legacy)
    await hass.async_block_till_done()

    # Still exactly one verisure_owa entry, no duplicate.
    assert len(hass.config_entries.async_entries("verisure_owa")) == 1


async def test_shim_creates_restart_notification(hass: HomeAssistant):
    """Successful migration creates a persistent notification asking the user to restart."""
    from custom_components.securitas import async_setup_entry as shim_setup

    legacy = MockConfigEntry(
        domain="securitas",
        data={"username": "u@x", "password": "p", "country": "ES"},
        title="Home",
        unique_id="u@x:100001",
        version=3,
    )
    legacy.add_to_hass(hass)

    await shim_setup(hass, legacy)
    await hass.async_block_till_done()

    notifications = async_get_persistent_notifications(hass)
    assert "verisure_owa_migration_complete" in notifications


async def test_shim_notification_lists_deprecated_surfaces(hass: HomeAssistant):
    """Notification body names every deprecated surface so users know what to update."""
    from custom_components.securitas import async_setup_entry as shim_setup

    legacy = MockConfigEntry(
        domain="securitas",
        data={"username": "u@x", "password": "p", "country": "ES"},
        title="Home",
        unique_id="u@x:100001",
        version=3,
    )
    legacy.add_to_hass(hass)

    await shim_setup(hass, legacy)
    await hass.async_block_till_done()

    notifications = async_get_persistent_notifications(hass)
    body = notifications["verisure_owa_migration_complete"]["message"]

    # Restart guidance must be present.
    assert "restart" in body.lower()

    # v6 removal timing must be stated so users know they have a window.
    assert "v6" in body

    # Every deprecated surface is named so users can grep for them in their config.
    assert "securitas.force_arm" in body
    assert "securitas_arming_exception" in body
    assert "/securitas_panel" in body
    assert "custom:securitas-alarm-card" in body

    # And each maps to the new identifier.
    assert "verisure_owa.force_arm" in body
    assert "verisure_owa_arming_exception" in body
    assert "/verisure_owa_panel" in body
    assert "custom:verisure-owa-alarm-card" in body
