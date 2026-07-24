"""When a stale custom_components/verisure_owa/ directory is left on disk
from an earlier v5.0.1 upgrade attempt, ``async_setup`` should raise a
Repairs issue prompting the user to remove it manually."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.securitas import async_setup
from custom_components.securitas.const import DOMAIN

ORPHAN_ISSUE_ID = "orphan_verisure_owa_directory"


@pytest.mark.asyncio
async def test_orphan_verisure_owa_directory_creates_repair(hass, tmp_path) -> None:
    """If /config/custom_components/verisure_owa/ exists, the repair appears."""
    (tmp_path / "custom_components").mkdir()
    (tmp_path / "custom_components" / "verisure_owa").mkdir()

    def _fake_path(*parts: str) -> str:
        return str(tmp_path.joinpath(*parts))

    with patch.object(hass.config, "path", side_effect=_fake_path):
        assert await async_setup(hass, {}) is True

    registry = ir.async_get(hass)
    matches = [
        issue
        for issue in registry.issues.values()
        if issue.domain == DOMAIN and issue.issue_id == ORPHAN_ISSUE_ID
    ]
    assert len(matches) == 1
    assert str(tmp_path / "custom_components" / "verisure_owa") in (
        matches[0].translation_placeholders or {}
    ).get("path", "")


@pytest.mark.asyncio
async def test_no_orphan_directory_no_repair(hass, tmp_path) -> None:
    """Clean install — no verisure_owa folder, no Repair created."""
    (tmp_path / "custom_components").mkdir()

    def _fake_path(*parts: str) -> str:
        return str(tmp_path.joinpath(*parts))

    with patch.object(hass.config, "path", side_effect=_fake_path):
        assert await async_setup(hass, {}) is True

    registry = ir.async_get(hass)
    matches = [
        issue
        for issue in registry.issues.values()
        if issue.domain == DOMAIN and issue.issue_id == ORPHAN_ISSUE_ID
    ]
    assert matches == []
