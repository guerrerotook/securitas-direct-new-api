"""Legacy 'securitas' shim — migrates config entries to 'verisure_owa'.

Removed entirely in v6.0.0. Until then, any user upgrading from a pre-v5
install lands in this shim, which moves their state to verisure_owa and
removes itself.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

_LOGGER = logging.getLogger(__name__)

DOMAIN = "securitas"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:  # noqa: ARG001  # pylint: disable=unused-argument
    """No YAML config to set up — entries handled in async_setup_entry.

    The hass and config arguments are required by HA's integration contract.
    """
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a legacy 'securitas' config entry to 'verisure_owa'.

    Returns False because we never actually set up the legacy entry —
    we replace it with a new one under verisure_owa and remove this one.
    """
    # pylint: disable=import-error  # HA loader resolves custom_components.* at runtime; pylint's static analyser can't see the path
    from custom_components.verisure_owa.migrate import migrate_legacy_entry

    _LOGGER.warning(
        "The 'securitas' integration is deprecated. Migrating config entry %s "
        "to 'verisure_owa'. The legacy 'securitas' shim will be removed entirely "
        "in v6.0.0.",
        entry.entry_id,
    )
    await migrate_legacy_entry(hass, entry)

    # Surface the restart-required prompt as a fixable Repairs issue rather
    # than a long persistent banner. The Fix button restarts HA; the issue's
    # learn-more URL points to the breaking-changes section in the README so
    # users can review the renamed services / events / Lovelace surfaces.
    ir.async_create_issue(
        hass,
        "verisure_owa",
        "restart_required_after_migration",
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="restart_required_after_migration",
        learn_more_url=(
            "https://github.com/guerrerotook/securitas-direct-new-api"
            "#breaking-changes-in-v500"
        ),
    )

    # Remove the legacy entry now that its state has been moved.
    hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
    return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:  # noqa: ARG001  # pylint: disable=unused-argument
    """Nothing to unload — the entry was never set up."""
    return True
