"""Tests for button entity (SecuritasRefreshButton)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.securitas.button import SecuritasRefreshButton, async_setup_entry
from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    OperationStatus,
)
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
)
from custom_components.securitas import DOMAIN

from tests.conftest import (
    make_installation,
    make_securitas_hub_mock,
    setup_integration_data,
)


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
        assert (DOMAIN, "securitas_direct.123456") in info["identifiers"]  # type: ignore[typeddict-item]
        assert info["manufacturer"] == "Securitas Direct"  # type: ignore[typeddict-item]
        assert info["model"] == "SDVFAST"  # type: ignore[typeddict-item]
        assert info["name"] == "Home"  # type: ignore[typeddict-item]
        assert info["hw_version"] == "PLUS"  # type: ignore[typeddict-item]

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

    async def test_success_calls_refresh_alarm_status(self):
        """Success: calls hub.refresh_alarm_status, sets protom_response."""
        button = make_button()

        alarm_status = OperationStatus(
            operation_status="OK",
            message="All good",
            status="",
            installation_number="123456",
            protomResponse="D",
            protomResponseData="",
        )
        button.client.refresh_alarm_status = AsyncMock(return_value=alarm_status)

        await button.async_press()

        button.client.refresh_alarm_status.assert_called_once_with(button.installation)
        assert button.client.session.protom_response == "D"

    async def test_success_triggers_alarm_entity_update(self):
        """Success: triggers state update on the alarm entity for this installation."""
        button = make_button()

        alarm_status = OperationStatus(
            operation_status="OK",
            message="",
            status="",
            installation_number="123456",
            protomResponse="T",
            protomResponseData="",
        )
        button.client.refresh_alarm_status = AsyncMock(return_value=alarm_status)

        # Set up alarm entity lookup
        alarm_entity = MagicMock()
        button.hass.data = {DOMAIN: {"alarm_entities": {"123456": alarm_entity}}}  # type: ignore[attr-defined]

        await button.async_press()

        alarm_entity.async_schedule_update_ha_state.assert_called_once_with(
            force_refresh=True
        )

    async def test_error_securitas_direct_error_caught(self):
        """SecuritasDirectError is caught and logged, no crash."""
        button = make_button()
        button.client.refresh_alarm_status = AsyncMock(
            side_effect=SecuritasDirectError("API timeout")
        )

        # Should not raise
        await button.async_press()

    async def test_403_creates_persistent_notification(self):
        """403 error creates a rate-limited persistent notification."""
        button = make_button()
        button.client.refresh_alarm_status = AsyncMock(
            side_effect=SecuritasDirectError("HTTP 403", http_status=403)
        )

        await button.async_press()

        button.hass.services.async_call.assert_called_once()  # type: ignore[attr-defined]
        call_kwargs = button.hass.services.async_call.call_args  # type: ignore[attr-defined]
        assert call_kwargs[1]["domain"] == "persistent_notification"
        assert call_kwargs[1]["service"] == "create"
        assert "Rate limited" in call_kwargs[1]["service_data"]["title"]

    async def test_403_sets_waf_blocked_on_alarm_entity(self):
        """403 on button press sets waf_blocked on the alarm entity."""
        button = make_button()
        button.client.refresh_alarm_status = AsyncMock(
            side_effect=SecuritasDirectError("HTTP 403", http_status=403)
        )

        # Set up a mock alarm entity accessible via hass.data
        mock_alarm = MagicMock()
        mock_alarm._set_waf_blocked = MagicMock()
        mock_alarm.async_write_ha_state = MagicMock()
        button.hass.data = {  # type: ignore[attr-defined]
            DOMAIN: {"alarm_entities": {button.installation.number: mock_alarm}}
        }

        await button.async_press()

        mock_alarm._set_waf_blocked.assert_called_once_with(True)
        mock_alarm.async_write_ha_state.assert_called_once()

    async def test_403_without_alarm_entity_does_not_crash(self):
        """403 when no alarm entity is registered still works (just notification)."""
        button = make_button()
        button.client.refresh_alarm_status = AsyncMock(
            side_effect=SecuritasDirectError("HTTP 403", http_status=403)
        )
        button.hass.data = {}  # type: ignore[attr-defined]

        await button.async_press()

        # Should not crash, notification still created
        button.hass.services.async_call.assert_called_once()  # type: ignore[attr-defined]

    async def test_non_403_error_does_not_create_notification(self):
        """Non-403 errors are logged but do not create persistent notifications."""
        button = make_button()
        button.client.refresh_alarm_status = AsyncMock(
            side_effect=SecuritasDirectError("Network error")
        )

        await button.async_press()

        button.hass.services.async_call.assert_not_called()  # type: ignore[attr-defined]


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

        button.client.refresh_alarm_status.assert_not_called()  # type: ignore[attr-defined]
