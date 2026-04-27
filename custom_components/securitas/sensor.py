"""Securitas direct sentinel sensor."""

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .coordinators import SentinelCoordinator
from .entity import securitas_device_info
from .securitas_direct_new_api import Installation

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct sentinel sensors based on config_entry.

    No API calls are made here.  Entities start with unknown state;
    the coordinator drives periodic updates.
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: SentinelCoordinator | None = entry_data["sentinel_coordinator"]

    if coordinator is None:
        return

    installation: Installation = coordinator.installation
    service_id: int = coordinator.service.id

    sensors: list[SensorEntity] = [
        SentinelTemperature(coordinator, installation, service_id),
        SentinelHumidity(coordinator, installation, service_id),
        SentinelAirQuality(coordinator, installation, service_id),
        SentinelAirQualityStatus(coordinator, installation, service_id),
    ]
    async_add_entities(sensors, False)


class SentinelTemperature(  # type: ignore[override]
    CoordinatorEntity[SentinelCoordinator],
    SensorEntity,
):
    """Sentinel temperature sensor."""

    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: SentinelCoordinator,
        installation: Installation,
        service_id: int,
    ) -> None:
        """Init the component."""
        super().__init__(coordinator)
        self._attr_device_info = securitas_device_info(installation)
        self._attr_unique_id = f"v4_{installation.number}_temperature_{service_id}"
        self._attr_name = f"{installation.alias} Temperature"

    @property
    def native_value(self) -> float | None:  # type: ignore[override]
        """Return the temperature from coordinator data."""
        if self.coordinator.data is None or self.coordinator.data.sentinel is None:
            return None
        return self.coordinator.data.sentinel.temperature


class SentinelHumidity(  # type: ignore[override]
    CoordinatorEntity[SentinelCoordinator],
    SensorEntity,
):
    """Sentinel Humidity sensor."""

    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        coordinator: SentinelCoordinator,
        installation: Installation,
        service_id: int,
    ) -> None:
        """Init the component."""
        super().__init__(coordinator)
        self._attr_device_info = securitas_device_info(installation)
        self._attr_unique_id = f"v4_{installation.number}_humidity_{service_id}"
        self._attr_name = f"{installation.alias} Humidity"

    @property
    def native_value(self) -> float | None:  # type: ignore[override]
        """Return the humidity from coordinator data."""
        if self.coordinator.data is None or self.coordinator.data.sentinel is None:
            return None
        return self.coordinator.data.sentinel.humidity


AIR_QUALITY_LABELS: dict[str, str] = {
    "1": "Good",
    "2": "Fair",
    "3": "Poor",
}


class SentinelAirQuality(  # type: ignore[override]
    CoordinatorEntity[SentinelCoordinator],
    SensorEntity,
):
    """Air Quality sensor — numeric value from the most recent hourly reading."""

    _attr_has_entity_name = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SentinelCoordinator,
        installation: Installation,
        service_id: int,
    ) -> None:
        """Init the component."""
        super().__init__(coordinator)
        self._attr_device_info = securitas_device_info(installation)
        self._attr_unique_id = f"v4_{installation.number}_airquality_{service_id}"
        self._attr_name = f"{installation.alias} Air Quality"

    @property
    def native_value(self) -> int | None:  # type: ignore[override]
        """Return the air quality value from coordinator data."""
        if self.coordinator.data is None or self.coordinator.data.air_quality is None:
            return None
        return self.coordinator.data.air_quality.value


class SentinelAirQualityStatus(  # type: ignore[override]
    CoordinatorEntity[SentinelCoordinator],
    SensorEntity,
):
    """Air Quality Status sensor — categorical status (Good/Fair/Poor/Bad)."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: SentinelCoordinator,
        installation: Installation,
        service_id: int,
    ) -> None:
        """Init the component."""
        super().__init__(coordinator)
        self._attr_device_info = securitas_device_info(installation)
        self._attr_unique_id = (
            f"v4_{installation.number}_airquality_status_{service_id}"
        )
        self._attr_name = f"{installation.alias} Air Quality Status"

    @property
    def native_value(self) -> str | None:  # type: ignore[override]
        """Return the air quality status label from coordinator data."""
        if self.coordinator.data is None or self.coordinator.data.air_quality is None:
            return None
        return self._status_label(self.coordinator.data.air_quality.status_current)

    @staticmethod
    def _status_label(status_current: int) -> str:
        """Map numeric status_current to a text label."""
        code = str(status_current)
        label = AIR_QUALITY_LABELS.get(code)
        if label is None:
            _LOGGER.warning(
                "Unknown air quality status code '%s' — please report this",
                code,
            )
            label = code
        return label
