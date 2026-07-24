"""Tests for magnetic-contact background discovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.securitas.discovery import _discover_contacts

from tests.conftest import make_installation


async def test_contact_discovery_does_not_require_homestt_service() -> None:
    """Always query the device inventory for contacts.

    Some French installations expose MG/MR devices without advertising the
    HOMESTT service capability.
    """
    hub = MagicMock()
    hub.get_contact_devices = AsyncMock(return_value=[])

    installation = make_installation()
    await _discover_contacts(
        MagicMock(),
        hub,
        installation,
        {},
        MagicMock(),
    )

    hub.get_contact_devices.assert_awaited_once_with(installation)
    hub.get_services.assert_not_called()
