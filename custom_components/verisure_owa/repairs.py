"""Repair flows for Verisure OWA.

Currently used to gate the post-migration restart prompt: when the legacy
``securitas`` shim migrates a config entry it raises a fixable issue here,
and clicking "Fix" runs ``_RestartFlow`` which restarts Home Assistant so
the migrated entries finish coming up under ``verisure_owa``.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.const import RESTART_EXIT_CODE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import issue_registry as ir

ISSUE_RESTART_REQUIRED = "restart_required_after_migration"


class _RestartFlow(RepairsFlow):
    """Confirm-and-restart flow used by ``ISSUE_RESTART_REQUIRED``.

    Clearing the issue before the restart so it doesn't reappear on the next
    boot — the fix flow's normal "delete on async_create_entry" path can't run
    once we've called ``hass.async_stop``.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            ir.async_delete_issue(self.hass, "verisure_owa", ISSUE_RESTART_REQUIRED)
            self.hass.async_create_task(self.hass.async_stop(RESTART_EXIT_CODE))
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001  # pylint: disable=unused-argument
    issue_id: str,
    data: dict[str, Any] | None,  # noqa: ARG001  # pylint: disable=unused-argument
) -> RepairsFlow:
    """Return a repair flow for the given issue id."""
    if issue_id == ISSUE_RESTART_REQUIRED:
        return _RestartFlow()
    raise NotImplementedError(f"Unknown repair issue id: {issue_id}")
