"""Tests for button entity (VerisureRefreshButton)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.securitas.button import (
    VerisureRefreshButton,
    async_setup_entry,
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
        """New entities use the canonical v4_securitas_direct.<num>_<type>
        form. Pre-v5 entities (with the older v4_refresh_button_<num>
        ordering) are rewritten to this form by migrate_unique_ids on
        first load — see tests/test_migrate_unique_ids.py.
        """
        button = make_button()
        assert button._attr_unique_id == "v4_securitas_direct.123456_refresh_button"

    def test_device_info_identifiers(self):
        """device_info contains correct identifiers, manufacturer, and model."""
        button = make_button()
        info = button._attr_device_info
        assert (DOMAIN, "v4_securitas_direct.123456") in info["identifiers"]  # type: ignore[typeddict-item]
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
    """VerisureRefreshButton.async_press is a deprecated thin wrapper that
    delegates to alarm_entity.async_manual_refresh.  The full refresh
    behaviour is exercised in TestAsyncManualRefresh in test_alarm_panel.py
    — here we only verify the delegation contract.
    """

    async def test_delegates_to_alarm_entity_manual_refresh(self):
        button = make_button()
        alarm_entity = MagicMock()
        alarm_entity.async_manual_refresh = AsyncMock()
        button.hass.data = {  # type: ignore[attr-defined]
            DOMAIN: {"alarm_entities": {button._installation.number: alarm_entity}}
        }

        await button.async_press()

        alarm_entity.async_manual_refresh.assert_awaited_once_with()

    async def test_forwards_context_to_alarm_entity(self):
        """The HA user/context that pressed the button is surfaced to the
        alarm entity so downstream activity-log injection attributes the
        action correctly."""
        button = make_button()
        ctx = MagicMock()
        button._context = ctx
        alarm_entity = MagicMock()
        alarm_entity.async_manual_refresh = AsyncMock()
        button.hass.data = {  # type: ignore[attr-defined]
            DOMAIN: {"alarm_entities": {button._installation.number: alarm_entity}}
        }

        await button.async_press()

        alarm_entity.async_set_context.assert_called_once_with(ctx)

    async def test_logs_deprecation_warning(self, caplog):
        button = make_button()
        alarm_entity = MagicMock()
        alarm_entity.async_manual_refresh = AsyncMock()
        button.hass.data = {  # type: ignore[attr-defined]
            DOMAIN: {"alarm_entities": {button._installation.number: alarm_entity}}
        }

        import logging

        with caplog.at_level(
            logging.WARNING, logger="custom_components.securitas.button"
        ):
            await button.async_press()

        assert any("deprecated" in r.message.lower() for r in caplog.records)
        assert any("refresh_alarm" in r.message for r in caplog.records)

    async def test_no_op_when_alarm_entity_missing(self):
        """If the alarm entity hasn't been registered yet (race during
        startup or after config-entry unload), the press is a no-op."""
        button = make_button()
        button.hass.data = {DOMAIN: {"alarm_entities": {}}}  # type: ignore[attr-defined]

        await button.async_press()  # must not raise

    async def test_no_crash_when_hass_is_none(self):
        button = make_button()
        button.hass = None

        await button.async_press()  # must not raise


# ===========================================================================
# async_setup_entry
# ===========================================================================


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    async def test_creates_one_button_per_device(self):
        """Creates one button per device in hass.data."""
        from custom_components.securitas import VerisureDevice

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
        from custom_components.securitas import VerisureDevice

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
        assert buttons[0]._attr_unique_id == "v4_securitas_direct.333_refresh_button"

    async def test_update_flag_passed_to_async_add_entities(self):
        """async_add_entities is called with update_before_add=True."""
        from custom_components.securitas import VerisureDevice

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
# Capture button unique_id pre-v5 schema (preserved across v5.0.2 upgrade)
# ===========================================================================


def test_capture_button_unique_id_uses_canonical_schema():
    from custom_components.securitas.button import VerisureCaptureButton
    from custom_components.securitas.verisure_owa_api.models import (
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
        == f"v4_securitas_direct.{installation.number}_capture_{camera_device.zone_id}"
    )
