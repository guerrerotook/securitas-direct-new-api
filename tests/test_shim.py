"""Tests for the legacy 'securitas' shim that triggers migration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry


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


async def test_shim_creates_repairs_issue_pointing_at_breaking_changes(
    hass: HomeAssistant,
):
    """Successful migration raises a fixable Repairs issue (replacing the
    old persistent banner) whose Learn-more link points at the
    breaking-changes section in CHANGES.md so users can review the
    renamed services, events, and Lovelace cards at their pace."""
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

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(
        "verisure_owa", "restart_required_after_migration"
    )
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_key == "restart_required_after_migration"
    assert "CHANGES.md#breaking-changes" in (issue.learn_more_url or "")


async def test_shim_migrates_via_ha_loader(
    hass: HomeAssistant, enable_custom_integrations: None
):
    """Regression: migration runs via HA's full loader path (requires config_flow.py)."""
    legacy = MockConfigEntry(
        domain="securitas",
        data={"username": "u@x", "password": "p", "country": "ES"},
        title="Home",
        unique_id="u@x:100001",
        version=3,
    )
    legacy.add_to_hass(hass)

    await hass.config_entries.async_setup(legacy.entry_id)
    await hass.async_block_till_done()

    assert len(hass.config_entries.async_entries("verisure_owa")) == 1


async def test_repair_flow_confirm_clears_issue_and_restarts(hass: HomeAssistant):
    """The Fix button on the restart-required issue clears the issue and
    requests an HA restart. Order matters: the issue is deleted before the
    stop call so it doesn't reappear on the next boot."""
    from unittest.mock import AsyncMock, patch

    from custom_components.verisure_owa.repairs import _RestartFlow

    # Pre-create the issue so we can observe it being cleared.
    ir.async_create_issue(
        hass,
        "verisure_owa",
        "restart_required_after_migration",
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="restart_required_after_migration",
    )
    issue_reg = ir.async_get(hass)
    assert (
        issue_reg.async_get_issue("verisure_owa", "restart_required_after_migration")
        is not None
    )

    flow = _RestartFlow()
    flow.hass = hass

    with patch.object(hass, "async_stop", AsyncMock()) as mock_stop:
        # First call: show the confirm form.
        result = await flow.async_step_init()
        assert result["type"] == "form"
        # Confirm: clear issue + dispatch restart.
        result = await flow.async_step_confirm({"confirm": True})
        assert result["type"] == "create_entry"
        await hass.async_block_till_done()

    assert (
        issue_reg.async_get_issue("verisure_owa", "restart_required_after_migration")
        is None
    )
    mock_stop.assert_awaited()
