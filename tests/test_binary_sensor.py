"""Tests for binary sensor platform (WifiConnectedSensor)."""

import pytest
from unittest.mock import MagicMock

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from custom_components.securitas.binary_sensor import WifiConnectedSensor
from custom_components.securitas.securitas_direct_new_api.dataTypes import SStatus

from tests.conftest import make_installation, make_securitas_hub_mock

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_sensor(
    installation_overrides: dict | None = None,
) -> WifiConnectedSensor:
    """Create a WifiConnectedSensor with mocked dependencies."""
    installation = make_installation(**(installation_overrides or {}))
    client = make_securitas_hub_mock()
    client.xsstatus = {}
    sensor = WifiConnectedSensor(client, installation)
    sensor.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    return sensor


# ===========================================================================
# __init__
# ===========================================================================


class TestWifiConnectedSensorInit:
    """Tests for WifiConnectedSensor.__init__."""

    def test_unique_id_format(self):
        sensor = make_sensor()
        assert sensor._attr_unique_id == "123456_wifi_connected"

    def test_name_includes_installation_alias(self):
        sensor = make_sensor()
        assert sensor._attr_name == "Home WiFi Connected"

    def test_name_uses_custom_alias(self):
        sensor = make_sensor(installation_overrides={"alias": "Office"})
        assert sensor._attr_name == "Office WiFi Connected"

    def test_device_class_is_connectivity(self):
        sensor = make_sensor()
        assert sensor._attr_device_class == BinarySensorDeviceClass.CONNECTIVITY

    def test_entity_category_is_diagnostic(self):
        sensor = make_sensor()
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_should_poll_is_false(self):
        sensor = make_sensor()
        assert sensor._attr_should_poll is False


# ===========================================================================
# _handle_update
# ===========================================================================


class TestHandleUpdate:
    """Tests for WifiConnectedSensor._handle_update."""

    def test_ignores_update_for_different_installation(self):
        """Update for a different installation number is ignored."""
        sensor = make_sensor()
        sensor._handle_update("999999")

        sensor.async_write_ha_state.assert_not_called()  # type: ignore[attr-defined]

    def test_updates_is_on_when_wifi_connected_true(self):
        """Sets _attr_is_on to True when wifi_connected is True."""
        sensor = make_sensor()
        sensor._client.xsstatus["123456"] = SStatus(wifi_connected=True)

        sensor._handle_update("123456")

        assert sensor._attr_is_on is True
        sensor.async_write_ha_state.assert_called_once()  # type: ignore[attr-defined]

    def test_updates_is_on_when_wifi_connected_false(self):
        """Sets _attr_is_on to False when wifi_connected is False."""
        sensor = make_sensor()
        sensor._client.xsstatus["123456"] = SStatus(wifi_connected=False)

        sensor._handle_update("123456")

        assert sensor._attr_is_on is False
        sensor.async_write_ha_state.assert_called_once()  # type: ignore[attr-defined]

    def test_no_update_when_wifi_connected_is_none(self):
        """Does NOT update state when wifi_connected is None."""
        sensor = make_sensor()
        sensor._client.xsstatus["123456"] = SStatus(wifi_connected=None)

        sensor._handle_update("123456")

        sensor.async_write_ha_state.assert_not_called()  # type: ignore[attr-defined]

    def test_no_update_when_status_missing_from_xsstatus(self):
        """Does NOT update state when installation number not in xsstatus dict."""
        sensor = make_sensor()
        # xsstatus is empty — no entry for "123456"

        sensor._handle_update("123456")

        sensor.async_write_ha_state.assert_not_called()  # type: ignore[attr-defined]
