"""Tests for button entity (VerisureRefreshButton)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.verisure_owa.button import (
    VerisureRefreshButton,
    async_setup_entry,
)
from custom_components.verisure_owa import DOMAIN
from custom_components.verisure_owa.verisure_owa_api.exceptions import (
    OperationTimeoutError,
    VerisureOwaError,
)
from custom_components.verisure_owa.verisure_owa_api.models import (
    OperationStatus,
)

from tests.conftest import (
    make_installation,
    make_securitas_hub_mock,
    setup_integration_data,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_button(entry_id: str = "test-entry-id") -> VerisureRefreshButton:
    """Create a VerisureRefreshButton with mocked dependencies."""
    installation = make_installation()
    client = make_securitas_hub_mock()
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.async_entity_ids = MagicMock(
        return_value=["alarm_control_panel.securitas_123"]
    )
    hass.services = AsyncMock()
    return VerisureRefreshButton(installation, client, hass, entry_id)


# ===========================================================================
# __init__
# ===========================================================================


class TestVerisureRefreshButtonInit:
    """Tests for VerisureRefreshButton.__init__."""

    def test_name_is_short_form_without_alias(self):
        """Refresh button name is the verb only; alias is on the device."""
        button = make_button()
        assert button._attr_name == "Refresh"

    def test_has_entity_name_is_true(self):
        button = make_button()
        assert button._attr_has_entity_name is True

    def test_unique_id_format(self):
        """unique_id follows the v5 schema."""
        button = make_button()
        assert button._attr_unique_id == "v5_verisure_owa.123456_refresh_button"

    def test_device_info_identifiers(self):
        """device_info contains correct identifiers, manufacturer, and model."""
        button = make_button()
        info = button._attr_device_info
        assert (DOMAIN, "v5_verisure_owa.123456") in info["identifiers"]  # type: ignore[typeddict-item]
        assert info["manufacturer"] == "Verisure"  # type: ignore[typeddict-item]
        assert info["model"] == "SDVFAST"  # type: ignore[typeddict-item]
        assert info["name"] == "Home"  # type: ignore[typeddict-item]
        assert info["hw_version"] == "PLUS"  # type: ignore[typeddict-item]

    def test_stores_client_reference(self):
        """Button stores the client (VerisureHub) reference."""
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
class TestVerisureRefreshButtonAsyncPress:
    """Tests for VerisureRefreshButton.async_press."""

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
        """async_press sets waf_blocked on 403 error and triggers a translated rate-limit notification."""
        button = make_button()
        err = VerisureOwaError("blocked", http_status=403)
        button._client.refresh_alarm_status = AsyncMock(side_effect=err)
        alarm_entity = MagicMock()
        button.hass.data = {  # type: ignore[attr-defined]
            DOMAIN: {"alarm_entities": {button._installation.number: alarm_entity}}
        }

        with patch(
            "custom_components.verisure_owa.button._async_notify",
            AsyncMock(),
        ) as mock_async_notify:
            await button.async_press()

        alarm_entity._set_waf_blocked.assert_called_with(True)
        mock_async_notify.assert_awaited_once_with(
            button.hass,
            f"rate_limited_{button._installation.number}",
            "rate_limited",
        )

    async def test_no_crash_when_hass_is_none(self):
        """async_press does not crash when hass is None."""
        button = make_button()
        button.hass = None

        # Should not raise
        await button.async_press()


# ===========================================================================
# async_setup_entry
# ===========================================================================


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    async def test_creates_one_button_per_device(self):
        """Creates one button per device in hass.data."""
        from custom_components.verisure_owa import VerisureDevice

        hass = MagicMock()
        hass.data = {}
        client = make_securitas_hub_mock()
        inst1 = make_installation(number="111", alias="Office")
        inst2 = make_installation(number="222", alias="Warehouse")
        devices = [VerisureDevice(inst1), VerisureDevice(inst2)]
        setup_integration_data(hass, client, devices=devices)

        entry = MagicMock()
        entry.entry_id = "test-entry-id"
        async_add_entities = MagicMock()

        await async_setup_entry(hass, entry, async_add_entities)

        async_add_entities.assert_called_once()
        buttons = async_add_entities.call_args[0][0]
        assert len(buttons) == 2

    async def test_calls_async_add_entities_with_correct_buttons(self):
        """Calls async_add_entities with VerisureRefreshButton instances."""
        from custom_components.verisure_owa import VerisureDevice

        hass = MagicMock()
        hass.data = {}
        client = make_securitas_hub_mock()
        inst = make_installation(number="333", alias="Garage")
        devices = [VerisureDevice(inst)]
        setup_integration_data(hass, client, devices=devices)

        entry = MagicMock()
        entry.entry_id = "test-entry-id"
        async_add_entities = MagicMock()

        await async_setup_entry(hass, entry, async_add_entities)

        buttons = async_add_entities.call_args[0][0]
        assert len(buttons) == 1
        assert isinstance(buttons[0], VerisureRefreshButton)
        assert buttons[0]._attr_name == "Refresh"
        assert buttons[0]._attr_unique_id == "v5_verisure_owa.333_refresh_button"

    async def test_update_flag_passed_to_async_add_entities(self):
        """async_add_entities is called with update_before_add=True."""
        from custom_components.verisure_owa import VerisureDevice

        hass = MagicMock()
        hass.data = {}
        client = make_securitas_hub_mock()
        devices = [VerisureDevice(make_installation())]
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


class TestHassNoneGuardsButton:
    """Verify button entity bails out when hass is None (after removal)."""

    async def test_async_press_skips_when_hass_is_none(self):
        button = make_button()
        button.hass = None  # type: ignore[attr-defined]

        # Should not raise or call any API methods
        await button.async_press()


# ===========================================================================
# Capture button unique_id v5 schema
# ===========================================================================


def test_capture_button_unique_id_uses_v5_schema():
    from custom_components.verisure_owa.button import VerisureCaptureButton
    from custom_components.verisure_owa.verisure_owa_api.models import (
        CameraDevice,
    )

    installation = make_installation()
    camera_device = CameraDevice(
        id="c1",
        code=1,
        zone_id="YR08",
        name="Hall",
        device_type="YR",
        serial_number="sn",
    )
    hub = make_securitas_hub_mock()
    btn = VerisureCaptureButton(hub, installation, camera_device)
    assert (
        btn._attr_unique_id
        == f"v5_verisure_owa.{installation.number}_capture_{camera_device.zone_id}"
    )
