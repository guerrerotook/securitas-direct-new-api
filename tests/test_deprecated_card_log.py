"""The deprecated alarm card, badge and chip report themselves over the
websocket, and the integration writes one warning per element and dashboard
to the Home Assistant log."""

from __future__ import annotations

import logging

import pytest
from homeassistant.setup import async_setup_component

from custom_components.securitas import async_setup

COMMAND = "verisure_owa/deprecated_element"


@pytest.fixture
async def ws(hass, hass_ws_client):
    assert await async_setup_component(hass, "websocket_api", {})
    assert await async_setup(hass, {}) is True
    return await hass_ws_client(hass)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and "deprecated" in r.getMessage()
    ]


async def _report(ws, element: str, dashboard: str = "lovelace") -> dict:
    await ws.send_json_auto_id(
        {"type": COMMAND, "element": element, "dashboard": dashboard}
    )
    return await ws.receive_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("element", "replacement"),
    [
        ("card", "Tile card"),
        ("badge", "entity badge"),
        ("chip", "Mushroom"),
    ],
)
async def test_logs_a_warning_naming_dashboard_and_replacement(
    ws, caplog, element, replacement
) -> None:
    msg = await _report(ws, element, "dashboard-security")

    assert msg["success"] is True
    [warning] = _warnings(caplog)
    assert "/dashboard-security" in warning
    assert replacement in warning
    assert "#replacing-the-deprecated-alarm-card-badge-and-chip" in warning


@pytest.mark.asyncio
async def test_logs_once_per_element_and_dashboard(ws, caplog) -> None:
    await _report(ws, "card", "lovelace")
    await _report(ws, "card", "lovelace")
    assert len(_warnings(caplog)) == 1

    await _report(ws, "card", "dashboard-security")
    await _report(ws, "badge", "lovelace")
    assert len(_warnings(caplog)) == 3


@pytest.mark.asyncio
async def test_rejects_an_unknown_element(ws, caplog) -> None:
    msg = await _report(ws, "camera-card")

    assert msg["success"] is False
    assert _warnings(caplog) == []


@pytest.mark.asyncio
async def test_rejects_an_oversized_dashboard_path(ws, caplog) -> None:
    msg = await _report(ws, "card", "x" * 500)

    assert msg["success"] is False
    assert _warnings(caplog) == []
