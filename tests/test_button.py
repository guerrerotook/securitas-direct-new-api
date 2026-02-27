"""Tests for button entity (SecuritasRefreshButton)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.securitas.button import SecuritasRefreshButton, async_setup_entry
from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    CheckAlarmStatus,
    Installation,
)
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
)
from custom_components.securitas import DOMAIN, SecuritasHub

from tests.conftest import make_installation, make_securitas_hub_mock, setup_integration_data


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_button() -> SecuritasRefreshButton:
    """Create a SecuritasRefreshButton with mocked dependencies."""
    installation = make_installation()
    client = make_securitas_hub_mock()
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.async_entity_ids = MagicMock(
        return_value=["alarm_control_panel.securitas_123"]
    )
    hass.services = AsyncMock()
    return SecuritasRefreshButton(installation, client, hass)


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
        assert button._attr_unique_id == "refresh_button_123456"

    def test_device_info_identifiers(self):
        """device_info contains correct identifiers, manufacturer, and model."""
        button = make_button()
        info = button._attr_device_info
        assert (DOMAIN, "securitas_direct.123456") in info["identifiers"]
        assert info["manufacturer"] == "Securitas Direct"
        assert info["model"] == "SDVFAST"
        assert info["name"] == "Home"
        assert info["hw_version"] == "PLUS"

    def test_stores_client_reference(self):
        """Button stores the client (SecuritasHub) reference."""
        button = make_button()
        assert button.client is not None
        assert hasattr(button.client, "session")


# ===========================================================================
# async_press
# ===========================================================================


@pytest.mark.asyncio
class TestSecuritasRefreshButtonAsyncPress:
    """Tests for SecuritasRefreshButton.async_press."""

    async def test_success_calls_check_alarm_and_status(self):
        """Success: calls check_alarm + check_alarm_status, sets protom_response."""
        button = make_button()

        alarm_status = CheckAlarmStatus(
            operation_status="OK",
            message="All good",
            status="",
            InstallationNumer="123456",
            protomResponse="D",
            protomResponseData="",
        )
        button.client.session.check_alarm = AsyncMock(return_value="ref-123")
        button.client.session.check_alarm_status = AsyncMock(return_value=alarm_status)

        with patch("custom_components.securitas.button.asyncio.sleep", new_callable=AsyncMock):
            await button.async_press()

        button.client.session.check_alarm.assert_called_once_with(button.installation)
        button.client.session.check_alarm_status.assert_called_once_with(
            button.installation, "ref-123"
        )
        assert button.client.session.protom_response == "D"

    async def test_success_updates_alarm_entities(self):
        """Success: updates alarm entities via hass.services.async_call."""
        button = make_button()

        alarm_status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="T",
            protomResponseData="",
        )
        button.client.session.check_alarm = AsyncMock(return_value="ref-456")
        button.client.session.check_alarm_status = AsyncMock(return_value=alarm_status)

        with patch("custom_components.securitas.button.asyncio.sleep", new_callable=AsyncMock):
            await button.async_press()

        button.hass.services.async_call.assert_called_once_with(
            "homeassistant",
            "update_entity",
            {"entity_id": "alarm_control_panel.securitas_123"},
            blocking=True,
        )

    async def test_error_securitas_direct_error_caught(self):
        """SecuritasDirectError is caught and logged, no crash."""
        button = make_button()
        button.client.session.check_alarm = AsyncMock(
            side_effect=SecuritasDirectError("API timeout")
        )

        with patch("custom_components.securitas.button.asyncio.sleep", new_callable=AsyncMock):
            # Should not raise
            await button.async_press()

        # check_alarm_status should never have been called
        button.client.session.check_alarm_status.assert_not_called()

    async def test_error_during_check_alarm_status(self):
        """SecuritasDirectError during check_alarm_status is caught gracefully."""
        button = make_button()
        button.client.session.check_alarm = AsyncMock(return_value="ref-789")
        button.client.session.check_alarm_status = AsyncMock(
            side_effect=SecuritasDirectError("status timeout")
        )

        with patch("custom_components.securitas.button.asyncio.sleep", new_callable=AsyncMock):
            # Should not raise
            await button.async_press()

        # No update_entity call should happen
        button.hass.services.async_call.assert_not_called()

    async def test_asyncio_sleep_is_called(self):
        """asyncio.sleep is called between check_alarm and check_alarm_status."""
        button = make_button()

        alarm_status = CheckAlarmStatus(
            operation_status="OK",
            message="",
            status="",
            InstallationNumer="123456",
            protomResponse="D",
            protomResponseData="",
        )
        button.client.session.check_alarm = AsyncMock(return_value="ref-000")
        button.client.session.check_alarm_status = AsyncMock(return_value=alarm_status)

        with patch("custom_components.securitas.button.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await button.async_press()

        mock_sleep.assert_called_once_with(1)


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
        async_add_entities = MagicMock()

        await async_setup_entry(hass, entry, async_add_entities)

        buttons = async_add_entities.call_args[0][0]
        assert len(buttons) == 1
        assert isinstance(buttons[0], SecuritasRefreshButton)
        assert buttons[0]._attr_name == "Refresh Garage"
        assert buttons[0]._attr_unique_id == "refresh_button_333"

    async def test_update_flag_passed_to_async_add_entities(self):
        """async_add_entities is called with update_before_add=True."""
        from custom_components.securitas import SecuritasDirectDevice

        hass = MagicMock()
        hass.data = {}
        client = make_securitas_hub_mock()
        devices = [SecuritasDirectDevice(make_installation())]
        setup_integration_data(hass, client, devices=devices)

        entry = MagicMock()
        async_add_entities = MagicMock()

        await async_setup_entry(hass, entry, async_add_entities)

        # Second positional arg or keyword arg should be True
        assert async_add_entities.call_args[0][1] is True
