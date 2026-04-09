"""Securitas direct sentinel sensor."""

import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, SecuritasDirectDevice, SecuritasHub
from .const import SENTINEL_SERVICE_NAMES
from .entity import SecuritasEntity, schedule_initial_updates
from .securitas_direct_new_api import Installation, SecuritasDirectError
from .securitas_direct_new_api.dataTypes import AirQuality, Service

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=30)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct sentinel sensors based on config_entry.

    No API calls are made here beyond service discovery (already cached from
    __init__ setup).  Entities start with unknown state; the first periodic
    ``async_update`` populates values via rate-limited hub methods.
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    client: SecuritasHub = entry_data["hub"]
    sensors: list[SensorEntity] = []
    securitas_devices: list[SecuritasDirectDevice] = entry_data["devices"]

    for device in securitas_devices:
        try:
            services: list[Service] = await client.get_services(device.installation)
        except SecuritasDirectError as err:
            _LOGGER.warning(
                "Skipping installation %s for sensor setup: %s",
                device.installation.number,
                err.log_detail(),
            )
            continue
        first_sentinel_service: Service | None = None
        for service in services:
            if service.request in SENTINEL_SERVICE_NAMES:
                sensors.append(
                    SentinelTemperature(service, client, device.installation)
                )
                sensors.append(SentinelHumidity(service, client, device.installation))
                if first_sentinel_service is None:
                    first_sentinel_service = service
        # One pair of air quality entities per installation (not per service).
        # Air quality data is per-installation; the sentinel service is only
        # needed for zone discovery.
        if first_sentinel_service is not None:
            fetcher = AirQualityFetcher(
                first_sentinel_service, client, device.installation
            )
            sensors.append(SentinelAirQuality(fetcher, device.installation))
            sensors.append(SentinelAirQualityStatus(fetcher, device.installation))
    async_add_entities(sensors, False)

    schedule_initial_updates(hass, sensors)


class SentinelTemperature(SecuritasEntity, SensorEntity):
    """Sentinel temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        service: Service,
        client: SecuritasHub,
        installation: Installation,
    ) -> None:
        """Init the component."""
        super().__init__(installation, client)
        self._attr_unique_id = f"v4_{installation.number}_temperature_{service.id}"
        self._attr_name = f"{installation.alias} Temperature"
        self._service: Service = service

    async def async_update(self):
        """Update the sensor via the hub's rate-limited method."""
        if self.hass is None:
            return
        try:
            sentinel = await self._client.get_sentinel(
                self._installation, self._service
            )
        except SecuritasDirectError as err:
            _LOGGER.warning(
                "Error updating temperature for %s: %s",
                self._installation.number,
                err.log_detail(),
            )
            return
        self._attr_native_value = sentinel.temperature


class SentinelHumidity(SecuritasEntity, SensorEntity):
    """Sentinel Humidity sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        service: Service,
        client: SecuritasHub,
        installation: Installation,
    ) -> None:
        """Init the component."""
        super().__init__(installation, client)
        self._attr_unique_id = f"v4_{installation.number}_humidity_{service.id}"
        self._attr_name = f"{installation.alias} Humidity"
        self._service: Service = service

    async def async_update(self):
        """Update the sensor via the hub's rate-limited method."""
        if self.hass is None:
            return
        try:
            sentinel = await self._client.get_sentinel(
                self._installation, self._service
            )
        except SecuritasDirectError as err:
            _LOGGER.warning(
                "Error updating humidity for %s: %s",
                self._installation.number,
                err.log_detail(),
            )
            return
        self._attr_native_value = sentinel.humidity


AIR_QUALITY_LABELS: dict[str, str] = {
    "1": "Good",
    "2": "Fair",
    "3": "Poor",
}


class AirQualityFetcher:
    """Fetches air quality data for an installation.

    Both numeric and status entities share one fetcher so they use the same
    data.  Deduplication across update cycles is handled by the hub's
    time-based API cache (30s TTL) — no manual reset is needed.
    """

    def __init__(
        self,
        service: Service,
        client: SecuritasHub,
        installation: Installation,
    ) -> None:
        self._service = service
        self._client = client
        self._installation = installation

    async def fetch(self) -> AirQuality | None:
        """Fetch air quality data via the hub's cached API calls."""
        try:
            sentinel = await self._client.get_sentinel(
                self._installation, self._service
            )
        except SecuritasDirectError:
            return None
        zone = sentinel.zone if sentinel.zone else ""

        try:
            return await self._client.get_air_quality(self._installation, zone)
        except SecuritasDirectError:
            _LOGGER.debug(
                "[%s] Air quality data not available",
                self._installation.alias,
            )
            return None


class SentinelAirQuality(SecuritasEntity, SensorEntity):
    """Air Quality sensor — numeric value from the most recent hourly reading."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        fetcher: AirQualityFetcher,
        installation: Installation,
    ) -> None:
        super().__init__(installation, fetcher._client)
        self._fetcher = fetcher
        self._attr_unique_id = (
            f"v4_{installation.number}_airquality_{fetcher._service.id}"
        )
        self._attr_name = f"{installation.alias} Air Quality"

    async def async_update(self):
        """Update the sensor via the hub's rate-limited method."""
        if self.hass is None:
            return
        air_quality = await self._fetcher.fetch()
        if air_quality is not None and air_quality.value is not None:
            self._attr_native_value = air_quality.value


class SentinelAirQualityStatus(SecuritasEntity, SensorEntity):
    """Air Quality Status sensor — categorical status (Good/Fair/Poor/Bad)."""

    def __init__(
        self,
        fetcher: AirQualityFetcher,
        installation: Installation,
    ) -> None:
        super().__init__(installation, fetcher._client)
        self._fetcher = fetcher
        self._attr_unique_id = (
            f"v4_{installation.number}_airquality_status_{fetcher._service.id}"
        )
        self._attr_name = f"{installation.alias} Air Quality Status"

    async def async_update(self):
        """Update the sensor via the hub's rate-limited method."""
        if self.hass is None:
            return
        air_quality = await self._fetcher.fetch()
        if air_quality is not None:
            code = str(air_quality.status_current)
            label = AIR_QUALITY_LABELS.get(code)
            if label is None:
                _LOGGER.warning(
                    "Unknown air quality status code '%s' for %s — please report this",
                    code,
                    self._installation.number,
                )
                label = code
            self._attr_native_value = label
