"""Tests for binary sensor platform (WifiConnectedSensor)."""

import pytest
from unittest.mock import MagicMock

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from custom_components.securitas.binary_sensor import WifiConnectedSensor
from custom_components.securitas.coordinators import AlarmCoordinator, AlarmStatusData
from custom_components.securitas.securitas_direct_new_api.models import SStatus

from tests.conftest import make_installation

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_sensor(
    installation_overrides: dict | None = None,
) -> WifiConnectedSensor:
    """Create a WifiConnectedSensor with mocked dependencies."""
    installation = make_installation(**(installation_overrides or {}))
    coordinator = MagicMock(spec=AlarmCoordinator)
    coordinator.data = None
    sensor = WifiConnectedSensor(coordinator, installation)
    sensor.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    return sensor


# ===========================================================================
# __init__
# ===========================================================================


class TestWifiConnectedSensorInit:
    """Tests for WifiConnectedSensor.__init__."""

    def test_unique_id_format(self):
        sensor = make_sensor()
        assert sensor._attr_unique_id == "v4_123456_wifi_connected"

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
# is_on property (coordinator-driven)
# ===========================================================================


class TestIsOnProperty:
    """Tests for WifiConnectedSensor.is_on property."""

    def test_returns_none_when_coordinator_data_is_none(self):
        """is_on returns None when coordinator has no data yet."""
        sensor = make_sensor()
        sensor.coordinator.data = None

        assert sensor.is_on is None

    def test_returns_true_when_wifi_connected(self):
        """is_on returns True when wifi_connected is True."""
        sensor = make_sensor()
        sensor.coordinator.data = AlarmStatusData(
            status=SStatus(wifi_connected=True),
        )

        assert sensor.is_on is True

    def test_returns_false_when_wifi_disconnected(self):
        """is_on returns False when wifi_connected is False."""
        sensor = make_sensor()
        sensor.coordinator.data = AlarmStatusData(
            status=SStatus(wifi_connected=False),
        )

        assert sensor.is_on is False

    def test_returns_none_when_wifi_connected_is_none(self):
        """is_on returns None when wifi_connected field is None."""
        sensor = make_sensor()
        sensor.coordinator.data = AlarmStatusData(
            status=SStatus(wifi_connected=None),
        )

        assert sensor.is_on is None
