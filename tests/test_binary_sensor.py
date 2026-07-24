"""Tests for binary sensor platform (WifiConnectedSensor)."""

from unittest.mock import MagicMock

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from custom_components.securitas.binary_sensor import (
    ContactOpeningSensor,
    WifiConnectedSensor,
)
from custom_components.securitas.coordinators import (
    AlarmCoordinator,
    AlarmStatusData,
    ContactCoordinator,
    ContactData,
)
from custom_components.securitas.verisure_owa_api.models import (
    ContactDevice,
    ContactState,
    SStatus,
    TimedValue,
)

from tests.conftest import make_installation


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
        assert sensor._attr_unique_id == "v4_securitas_direct.123456_wifi_connected"

    def test_name_is_short_form_without_alias(self):
        """Modern pattern: device name carries the alias; entity name is the suffix only."""
        sensor = make_sensor()
        assert sensor._attr_name == "WiFi Connected"

    def test_name_is_alias_independent(self):
        """Changing the alias does not change the entity name (it lives on the device)."""
        sensor = make_sensor(installation_overrides={"alias": "Office"})
        assert sensor._attr_name == "WiFi Connected"

    def test_has_entity_name_is_true(self):
        sensor = make_sensor()
        assert sensor._attr_has_entity_name is True

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


def make_contact_sensor() -> ContactOpeningSensor:
    """Create a magnetic opening sensor with mocked dependencies."""
    installation = make_installation()
    coordinator = MagicMock(spec=ContactCoordinator)
    coordinator.data = None
    sensor = ContactOpeningSensor(
        coordinator,
        installation,
        ContactDevice(
            id="1",
            code=1,
            zone_id="MG01",
            name="Porte entrée",
            device_type="MG",
        ),
    )
    sensor.async_write_ha_state = MagicMock()  # type: ignore[method-assign]
    return sensor


class TestContactOpeningSensor:
    """Tests for Verisure magnetic contact entities."""

    def test_entity_metadata(self) -> None:
        sensor = make_contact_sensor()

        assert sensor._attr_unique_id == "v4_securitas_direct.123456_contact_MG01"
        assert sensor._attr_name == "Porte entrée"
        assert sensor._attr_device_class == BinarySensorDeviceClass.OPENING
        assert sensor._attr_should_poll is False

    def test_unknown_before_first_refresh(self) -> None:
        sensor = make_contact_sensor()

        assert sensor.is_on is None

    def test_open_contact_is_on(self) -> None:
        sensor = make_contact_sensor()
        sensor.coordinator.data = ContactData(
            states={
                "MG01": ContactState(
                    zone_id="MG01",
                    magnetic_state=TimedValue(value="open"),
                )
            }
        )

        assert sensor.is_on is True

    def test_closed_contact_is_off(self) -> None:
        sensor = make_contact_sensor()
        sensor.coordinator.data = ContactData(
            states={
                "MG01": ContactState(
                    zone_id="MG01",
                    magnetic_state=TimedValue(value="closed"),
                )
            }
        )

        assert sensor.is_on is False

    def test_missing_or_unrecognized_state_is_unknown(self) -> None:
        sensor = make_contact_sensor()
        sensor.coordinator.data = ContactData(
            states={
                "MG01": ContactState(
                    zone_id="MG01",
                    magnetic_state=TimedValue(value="unavailable"),
                )
            }
        )

        assert sensor.is_on is None
