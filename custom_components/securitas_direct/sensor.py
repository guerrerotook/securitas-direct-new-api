"""Securitas direct sentinel sensor."""
from datetime import timedelta

from homeassistant.components.securitas_direct.securitas_direct_new_api.dataTypes import (
    Sentinel,
    Service,
)
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import PERCENTAGE, TEMP_CELSIUS

from . import CONF_ALARM, HUB as hub

SCAN_INTERVAL = timedelta(minutes=30)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Securitas platform."""
    sensors = []
    if int(hub.config.get(CONF_ALARM, 1)):
        for item in hub.sentinel_services:
            sentinel_data: Sentinel = hub.session.get_sentinel_data(
                item.installation, item
            )
            sensors.append(SentinelTemperature(sentinel_data, item))
            sensors.append(SentinelHumidity(sentinel_data, item))
    add_entities(sensors)


class SentinelTemperature(SensorEntity):
    """Sentinel temperature sensor."""

    def __init__(self, sentinel: Sentinel, service: Service) -> None:
        """Init the component."""
        self._update_sensor_data(sentinel)
        self._attr_unique_id = sentinel.alias + "_temperature_" + str(service.id)
        self._attr_name = "Temperature " + sentinel.alias.lower().capitalize()
        self._sentinel: Sentinel = sentinel
        self._service: Service = service

    def update(self):
        """Update the status of the alarm based on the configuration."""
        sentinel_data: Sentinel = hub.session.get_sentinel_data(
            self._service.installation, self._service
        )
        self._update_sensor_data(sentinel_data)

    def _update_sensor_data(self, sentinel: Sentinel):
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_value = sentinel.temperature
        self._attr_native_unit_of_measurement = TEMP_CELSIUS


class SentinelHumidity(SensorEntity):
    """Sentinel Humidity sensor."""

    def __init__(self, sentinel: Sentinel, service: Service) -> None:
        """Init the component."""
        self._update_sensor_data(sentinel)
        self._attr_unique_id = sentinel.alias + "_humidity_" + str(service.id)
        self._attr_name = "Humidity " + sentinel.alias.lower().capitalize()
        self._sentinel: Sentinel = sentinel
        self._service: Service = service

    def update(self):
        """Update the status of the alarm based on the configuration."""
        sentinel_data: Sentinel = hub.session.get_sentinel_data(
            self._service.installation, self._service
        )
        self._update_sensor_data(sentinel_data)

    def _update_sensor_data(self, sentinel: Sentinel):
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_native_value = sentinel.humidity
        self._attr_native_unit_of_measurement = PERCENTAGE
