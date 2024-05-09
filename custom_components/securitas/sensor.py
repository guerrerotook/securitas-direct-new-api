"""Securitas direct sentinel sensor."""
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CONF_INSTALLATION_KEY, DOMAIN, SecuritasDirectDevice, SecuritasHub
from .constants import SentinelName
from .securitas_direct_new_api.dataTypes import AirQuality, Sentinel, Service

SCAN_INTERVAL = timedelta(minutes=30)

_AIR_QUALITY_INDEX_SENSOR_ATTRIBUTES_MAP = {
    "value": "value",
    "message": "message",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up MELCloud device sensors based on config_entry."""
    client: SecuritasHub = hass.data[DOMAIN][SecuritasHub.__name__]
    sensors = []
    securitas_devices: list[SecuritasDirectDevice] = hass.data[DOMAIN].get(
        CONF_INSTALLATION_KEY
    )

    sentinel_name: SentinelName = SentinelName()
    sentinel_confort_name = sentinel_name.get_sentinel_name(client.lang)
    for device in securitas_devices:
        services: list[Service] = await client.get_services(device.installation)
        for service in services:
            if service.request == sentinel_confort_name:
                sentinel_data: Sentinel = await client.session.get_sentinel_data(
                    service.installation, service
                )
                sensors.append(
                    SentinelTemperature(sentinel_data, service, client, device)
                )
                sensors.append(SentinelHumidity(sentinel_data, service, client, device))

                air_quality: AirQuality = await client.session.get_air_quality_data(
                    service.installation, service
                )
                sensors.append(
                    SentinelAirQuality(
                        air_quality, sentinel_data, service, client, device
                    )
                )
    async_add_entities(sensors, True)


class SentinelTemperature(SensorEntity):
    """Sentinel temperature sensor."""

    def __init__(
        self,
        sentinel: Sentinel,
        service: Service,
        client: SecuritasHub,
        parent_device: SecuritasDirectDevice,
    ) -> None:
        """Init the component."""
        self._update_sensor_data(sentinel)
        self._attr_unique_id = sentinel.alias + "_temperature_" + str(service.id)
        self._attr_name = "Temperature " + sentinel.alias.lower().capitalize()
        self._sentinel: Sentinel = sentinel
        self._service: Service = service
        self._client: SecuritasHub = client
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer="Temperature Sensor",
            model=str(service.id_service) if service.id_service is not None else None,
            name=service.description,
            via_device=parent_device,
        )

    async def async_update(self):
        """Update the status of the alarm based on the configuration."""
        sentinel_data: Sentinel = await self._client.session.get_sentinel_data(
            self._service.installation, self._service
        )
        self._update_sensor_data(sentinel_data)

    def _update_sensor_data(self, sentinel: Sentinel):
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_value = sentinel.temperature
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS


class SentinelHumidity(SensorEntity):
    """Sentinel Humidity sensor."""

    def __init__(
        self,
        sentinel: Sentinel,
        service: Service,
        client: SecuritasHub,
        parent_device: SecuritasDirectDevice,
    ) -> None:
        """Init the component."""
        self._update_sensor_data(sentinel)
        self._attr_unique_id = sentinel.alias + "_humidity_" + str(service.id)
        self._attr_name = "Humidity " + sentinel.alias.lower().capitalize()
        self._sentinel: Sentinel = sentinel
        self._service: Service = service
        self._client: SecuritasHub = client
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer="Humidity Sensor",
            model=str(service.id_service) if service.id_service is not None else None,
            name=service.description,
            via_device=parent_device,
        )

    async def async_update(self):
        """Update the status of the alarm based on the configuration."""
        sentinel_data: Sentinel = await self._client.session.get_sentinel_data(
            self._service.installation, self._service
        )
        self._update_sensor_data(sentinel_data)

    def _update_sensor_data(self, sentinel: Sentinel):
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_value = sentinel.humidity
        self._attr_native_unit_of_measurement = PERCENTAGE


class SentinelAirQuality(SensorEntity):
    """Sentinel Humidity sensor."""

    def __init__(
        self,
        air_quality: AirQuality,
        sentinel: Sentinel,
        service: Service,
        client: SecuritasHub,
        parent_device: SecuritasDirectDevice,
    ) -> None:
        """Init the component."""
        self._update_sensor_data(air_quality)
        self._attr_unique_id = sentinel.alias + "airquality_" + str(service.id)
        self._attr_name = "Air Quality " + sentinel.alias.lower().capitalize()
        self._air_quality: AirQuality = air_quality
        self._service: Service = service
        self._client: SecuritasHub = client
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer="Air Quality Sensor",
            model=str(service.id_service) if service.id_service is not None else None,
            name=service.description,
            via_device=parent_device,
        )

    async def async_update(self):
        """Update the status of the alarm based on the configuration."""
        air_quality: AirQuality = await self._client.session.get_air_quality_data(
            self._service.installation, self._service
        )
        self._update_sensor_data(air_quality)

    def _update_sensor_data(self, air_quality: AirQuality):
        self._attr_native_value = air_quality.message

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return the state attributes."""
        sensor_attributes: dict[str, Any] = {}
        sensor_attributes["message"] = self._air_quality.message
        sensor_attributes["value"] = self._air_quality.value

        return {
            _AIR_QUALITY_INDEX_SENSOR_ATTRIBUTES_MAP[key]: value
            for key, value in sensor_attributes.items()
            if key in _AIR_QUALITY_INDEX_SENSOR_ATTRIBUTES_MAP
        }
