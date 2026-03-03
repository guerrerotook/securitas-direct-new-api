"""Securitas direct sentinel sensor."""

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

import logging

from . import CONF_INSTALLATION_KEY, DOMAIN, SecuritasDirectDevice, SecuritasHub
from .constants import SentinelName
from .securitas_direct_new_api import Installation, SecuritasDirectError, SStatus
from .securitas_direct_new_api.dataTypes import AirQuality, Sentinel, Service

_LOGGER = logging.getLogger(__name__)

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

                try:
                    air_quality: AirQuality = await client.session.get_air_quality_data(
                        service.installation, service, zone=sentinel_data.zone
                    )
                except SecuritasDirectError:
                    _LOGGER.warning(
                        "Air quality data not available for installation %s",
                        service.installation.number,
                    )
                else:
                    sensors.append(
                        SentinelAirQuality(
                            air_quality, sentinel_data, service, client, device
                        )
                    )
    # Add diagnostic sensors for each installation
    for device in securitas_devices:
        try:
            status: SStatus = await client.session.check_general_status(
                device.installation
            )
        except SecuritasDirectError:
            _LOGGER.warning(
                "Could not get diagnostic data for installation %s",
                device.installation.number,
            )
            continue

        if status.keep_alive_day is not None:
            sensors.append(DiagnosticKeepAliveDay(device.installation, client, status))
        if status.confort_message is not None:
            sensors.append(
                DiagnosticComfortMessage(device.installation, client, status)
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
        self._zone: str = sentinel.zone
        self._service: Service = service
        self._client: SecuritasHub = client
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer="Air Quality Sensor",
            model=str(service.id_service) if service.id_service is not None else None,
            name=service.description,
        )

    async def async_update(self):
        """Update the air quality sensor."""
        air_quality: AirQuality = await self._client.session.get_air_quality_data(
            self._service.installation, self._service, zone=self._zone
        )
        self._update_sensor_data(air_quality)

    def _update_sensor_data(self, air_quality: AirQuality):
        self._attr_native_value = air_quality.message

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:  # type: ignore[override]
        """Return the state attributes."""
        sensor_attributes: dict[str, Any] = {}
        sensor_attributes["message"] = self._air_quality.message
        sensor_attributes["value"] = self._air_quality.value

        return {
            _AIR_QUALITY_INDEX_SENSOR_ATTRIBUTES_MAP[key]: value
            for key, value in sensor_attributes.items()
            if key in _AIR_QUALITY_INDEX_SENSOR_ATTRIBUTES_MAP
        }


class DiagnosticKeepAliveDay(SensorEntity):
    """Keep-alive day diagnostic sensor."""

    def __init__(
        self,
        installation: Installation,
        client: SecuritasHub,
        status: SStatus,
    ) -> None:
        self._attr_name = f"Keep Alive Day {installation.alias}"
        self._attr_unique_id = f"securitas_direct.{installation.number}_keep_alive_day"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_value = status.keep_alive_day
        self._installation = installation
        self._client = client
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"securitas_direct.{installation.number}")},
            manufacturer="Securitas Direct",
            model=installation.panel,
            name=installation.alias,
            hw_version=installation.type,
        )

    async def async_update(self) -> None:
        try:
            status = await self._client.session.check_general_status(self._installation)
            self._attr_native_value = status.keep_alive_day
        except SecuritasDirectError as err:
            _LOGGER.error("Error updating keep alive day: %s", err)


class DiagnosticComfortMessage(SensorEntity):
    """Comfort message diagnostic sensor."""

    def __init__(
        self,
        installation: Installation,
        client: SecuritasHub,
        status: SStatus,
    ) -> None:
        self._attr_name = f"Comfort {installation.alias}"
        self._attr_unique_id = f"securitas_direct.{installation.number}_comfort_message"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_value = status.confort_message
        self._installation = installation
        self._client = client
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"securitas_direct.{installation.number}")},
            manufacturer="Securitas Direct",
            model=installation.panel,
            name=installation.alias,
            hw_version=installation.type,
        )

    async def async_update(self) -> None:
        try:
            status = await self._client.session.check_general_status(self._installation)
            self._attr_native_value = status.confort_message
        except SecuritasDirectError as err:
            _LOGGER.error("Error updating comfort message: %s", err)
