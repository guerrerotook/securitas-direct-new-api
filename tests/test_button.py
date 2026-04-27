"""Tests for button entity (SecuritasRefreshButton)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.securitas.button import SecuritasRefreshButton, async_setup_entry
from custom_components.securitas import DOMAIN
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    OperationTimeoutError,
    SecuritasDirectError,
)
from custom_components.securitas.securitas_direct_new_api.models import OperationStatus

from tests.conftest import (
    make_installation,
    make_securitas_hub_mock,
    setup_integration_data,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_button(entry_id: str = "test-entry-id") -> SecuritasRefreshButton:
    """Create a SecuritasRefreshButton with mocked dependencies."""
    installation = make_installation()
    client = make_securitas_hub_mock()
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.async_entity_ids = MagicMock(
        return_value=["alarm_control_panel.securitas_123"]
    )
    hass.services = AsyncMock()
    return SecuritasRefreshButton(installation, client, hass, entry_id)


# ===========================================================================
# __init__
# ===========================================================================


class TestSecuritasRefreshButtonInit:
    """Tests for SecuritasRefreshButton.__init__."""

    def test_name_includes_installation_alias(self):
        """Button name includes the installation alias."""
        button = make_button()
        assert button._attr_name == "Refresh Home"

    def test_unique_id_format(self):
        """unique_id follows refresh_button_{number} format."""
        button = make_button()
        assert button._attr_unique_id == "v4_refresh_button_123456"

    def test_device_info_identifiers(self):
        """device_info contains correct identifiers, manufacturer, and model."""
        button = make_button()
        info = button._attr_device_info
        assert (DOMAIN, "v4_securitas_direct.123456") in info["identifiers"]  # type: ignore[typeddict-item]
        assert info["manufacturer"] == "Securitas Direct"  # type: ignore[typeddict-item]
        assert info["model"] == "SDVFAST"  # type: ignore[typeddict-item]
        assert info["name"] == "Home"  # type: ignore[typeddict-item]
        assert info["hw_version"] == "PLUS"  # type: ignore[typeddict-item]

    def test_stores_client_reference(self):
        """Button stores the client (SecuritasHub) reference."""
        button = make_button()
        assert button.client is not None
        assert hasattr(button.client, "client")

    def test_stores_entry_id(self):
        """Button stores the entry_id for coordinator lookup."""
        button = make_button(entry_id="my-entry")
        assert button._entry_id == "my-entry"


# ===========================================================================
# async_press
# ===========================================================================


@pytest.mark.asyncio
class TestSecuritasRefreshButtonAsyncPress:
    """Tests for SecuritasRefreshButton.async_press."""

    async def test_calls_refresh_alarm_status(self):
        """async_press calls hub.refresh_alarm_status for authoritative round-trip."""
        button = make_button()
        status = OperationStatus(operation_status="OK", protom_response="T", status="")
        button._client.refresh_alarm_status = AsyncMock(return_value=status)
        button.hass.data = {DOMAIN: {"alarm_entities": {}}}  # type: ignore[attr-defined]

        await button.async_press()

        button._client.refresh_alarm_status.assert_awaited_once_with(
            button._installation
        )

    async def test_updates_protom_response_on_success(self):
        """async_press updates client.protom_response from the result."""
        button = make_button()
        status = OperationStatus(operation_status="OK", protom_response="T", status="")
        button._client.refresh_alarm_status = AsyncMock(return_value=status)
        button.hass.data = {DOMAIN: {"alarm_entities": {}}}  # type: ignore[attr-defined]

        await button.async_press()

        assert button._client.client.protom_response == "T"

    async def test_clears_refresh_failed_on_success(self):
        """async_press clears refresh_failed on the alarm entity."""
        button = make_button()
        status = OperationStatus(operation_status="OK", protom_response="T", status="")
        button._client.refresh_alarm_status = AsyncMock(return_value=status)
        alarm_entity = MagicMock()
        button.hass.data = {  # type: ignore[attr-defined]
            DOMAIN: {"alarm_entities": {button._installation.number: alarm_entity}}
        }

        await button.async_press()

        alarm_entity._set_refresh_failed.assert_called_with(False)
        alarm_entity.async_write_ha_state.assert_called()

    async def test_sets_refresh_failed_on_timeout(self):
        """async_press sets refresh_failed on timeout."""
        button = make_button()
        button._client.refresh_alarm_status = AsyncMock(
            side_effect=OperationTimeoutError("timed out")
        )
        alarm_entity = MagicMock()
        button.hass.data = {  # type: ignore[attr-defined]
            DOMAIN: {"alarm_entities": {button._installation.number: alarm_entity}}
        }

        await button.async_press()

        alarm_entity._set_refresh_failed.assert_called_with(True)

    async def test_sets_waf_blocked_on_403(self):
        """async_press sets waf_blocked on 403 error."""
        button = make_button()
        err = SecuritasDirectError("blocked", http_status=403)
        button._client.refresh_alarm_status = AsyncMock(side_effect=err)
        alarm_entity = MagicMock()
        button.hass.data = {  # type: ignore[attr-defined]
            DOMAIN: {"alarm_entities": {button._installation.number: alarm_entity}}
        }

        await button.async_press()

        alarm_entity._set_waf_blocked.assert_called_with(True)
        button.hass.services.async_call.assert_awaited_once()

    async def test_no_crash_when_hass_is_none(self):
        """async_press does not crash when hass is None."""
        button = make_button()
        button.hass = None

        # Should not raise
        await button.async_press()


# ===========================================================================
# async_setup_entry
# ===========================================================================


@pytest.mark.asyncio
class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    async def test_creates_one_button_per_device(self):
        """Creates one button per device in hass.data."""
        from custom_components.securitas import SecuritasDirectDevice

        hass = MagicMock()
        hass.data = {}
        client = make_securitas_hub_mock()
        inst1 = make_installation(number="111", alias="Office")
        inst2 = make_installation(number="222", alias="Warehouse")
        devices = [SecuritasDirectDevice(inst1), SecuritasDirectDevice(inst2)]
        setup_integration_data(hass, client, devices=devices)

        entry = MagicMock()
        entry.entry_id = "test-entry-id"
        async_add_entities = MagicMock()

        await async_setup_entry(hass, entry, async_add_entities)

        async_add_entities.assert_called_once()
        buttons = async_add_entities.call_args[0][0]
        assert len(buttons) == 2

    async def test_calls_async_add_entities_with_correct_buttons(self):
        """Calls async_add_entities with SecuritasRefreshButton instances."""
        from custom_components.securitas import SecuritasDirectDevice

        hass = MagicMock()
        hass.data = {}
        client = make_securitas_hub_mock()
        inst = make_installation(number="333", alias="Garage")
        devices = [SecuritasDirectDevice(inst)]
        setup_integration_data(hass, client, devices=devices)

        entry = MagicMock()
        entry.entry_id = "test-entry-id"
        async_add_entities = MagicMock()

        await async_setup_entry(hass, entry, async_add_entities)

        buttons = async_add_entities.call_args[0][0]
        assert len(buttons) == 1
        assert isinstance(buttons[0], SecuritasRefreshButton)
        assert buttons[0]._attr_name == "Refresh Garage"
        assert buttons[0]._attr_unique_id == "v4_refresh_button_333"

    async def test_update_flag_passed_to_async_add_entities(self):
        """async_add_entities is called with update_before_add=True."""
        from custom_components.securitas import SecuritasDirectDevice

        hass = MagicMock()
        hass.data = {}
        client = make_securitas_hub_mock()
        devices = [SecuritasDirectDevice(make_installation())]
        setup_integration_data(hass, client, devices=devices)

        entry = MagicMock()
        entry.entry_id = "test-entry-id"
        async_add_entities = MagicMock()

        await async_setup_entry(hass, entry, async_add_entities)

        # Second positional arg or keyword arg should be True
        assert async_add_entities.call_args[0][1] is True


# ===========================================================================
# hass-is-None guard tests (issue #323)
# ===========================================================================


@pytest.mark.asyncio
class TestHassNoneGuardsButton:
    """Verify button entity bails out when hass is None (after removal)."""

    async def test_async_press_skips_when_hass_is_none(self):
        button = make_button()
        button.hass = None  # type: ignore[attr-defined]

        # Should not raise or call any API methods
        await button.async_press()
