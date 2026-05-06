"""Securitas Direct sensors — sentinel environmental data and activity log."""

import base64
import logging
from collections.abc import Callable
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .coordinators import ActivityCoordinator, SentinelCoordinator
from .entity import securitas_device_info
from .events import attach_activity_listener
from .securitas_direct_new_api import Installation
from .securitas_direct_new_api.models import ActivityEvent

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct sensors based on config_entry.

    No API calls are made here.  Entities start with unknown state;
    coordinators drive periodic updates.
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    sensors: list[SensorEntity] = []

    sentinel_coord: SentinelCoordinator | None = entry_data["sentinel_coordinator"]
    if sentinel_coord is not None:
        sentinel_installation: Installation = sentinel_coord.installation
        service_id: int = sentinel_coord.service.id
        sensors.extend(
            [
                SentinelTemperature(sentinel_coord, sentinel_installation, service_id),
                SentinelHumidity(sentinel_coord, sentinel_installation, service_id),
                SentinelAirQuality(sentinel_coord, sentinel_installation, service_id),
                SentinelAirQualityStatus(
                    sentinel_coord, sentinel_installation, service_id
                ),
            ]
        )

    activity_coord: ActivityCoordinator | None = entry_data.get("activity_coordinator")
    if activity_coord is not None:
        sensors.append(ActivityLogSensor(activity_coord, activity_coord.installation))
        platform = async_get_current_platform()
        # Refresh button — FOREGROUND-priority refresh of the timeline.
        platform.async_register_entity_service(
            "refresh_activity_log",
            {},
            "async_manual_refresh",
        )
        # On-demand historical image fetch for image-request events.
        # Returns base64 JPEG via the response so the card can render inline.
        platform.async_register_entity_service(
            "fetch_activity_image",
            {
                vol.Required("id_signal"): str,
                vol.Required("signal_type"): vol.All(vol.Coerce(str)),
            },
            "async_fetch_image",
            supports_response=SupportsResponse.ONLY,
        )

    if sensors:
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


# Cap on the `events` attribute — bounds HA's recorder writes per state change.
_ACTIVITY_LOG_LIMIT = 30


def _sniff_image_mime(data: bytes) -> str:
    """Return the image MIME type derived from magic bytes; default jpeg."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # Fall back — browsers tend to MIME-sniff data URLs anyway.
    return "image/jpeg"


class ActivityLogSensor(  # type: ignore[override]
    CoordinatorEntity[ActivityCoordinator],
    SensorEntity,
):
    """Surfaces the alarm panel's xSActV2 timeline as a sensor.

    State is the alias of the most recent event ("Armed", "Alarm", ...).
    The `events` attribute holds the last 30 entries for dashboard viewing;
    `latest` exposes the full top entry.  Automations should use the
    `securitas_activity` event bus rather than reading these attributes.
    """

    _attr_has_entity_name = False
    _attr_icon = "mdi:format-list-bulleted"

    def __init__(
        self,
        coordinator: ActivityCoordinator,
        installation: Installation,
    ) -> None:
        super().__init__(coordinator)
        self._installation = installation
        self._attr_device_info = securitas_device_info(installation)
        self._attr_unique_id = f"v4_{installation.number}_activity_log"
        self._attr_name = f"{installation.alias} Activity Log"
        # Memoise extra_state_attributes — HA reads it from the recorder, the
        # frontend, the template engine, and websocket subscribers, often
        # several times per state update.  Cached by coordinator.data identity.
        self._attrs_cache_key: int | None = None
        self._attrs_cache: dict[str, Any] = {"events": []}
        self._bus_listener_unsub: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Wire bus emission once the sensor is in HA.

        Attaching the listener here (rather than in `async_setup_entry`)
        keeps the coordinator's periodic-refresh timer tied to the sensor's
        lifetime — without a sensor the coordinator stays idle, which avoids
        leaking timers in test setups that skip platform forwarding.
        """
        # Restore HA-side injected events from disk before the listener
        # triggers the first refresh — this way, persisted entries appear
        # in `data.events` from the very first render.
        await self.coordinator.async_load_persisted()
        await super().async_added_to_hass()
        self._bus_listener_unsub = attach_activity_listener(
            self.hass, self.coordinator, self._installation.number
        )

    async def async_will_remove_from_hass(self) -> None:
        """Detach the bus listener when the sensor is removed."""
        if self._bus_listener_unsub is not None:
            self._bus_listener_unsub()
            self._bus_listener_unsub = None
        await super().async_will_remove_from_hass()

    async def async_manual_refresh(self) -> None:
        """Service entrypoint for the card's refresh button."""
        await self.coordinator.async_manual_refresh()

    async def async_fetch_image(
        self, id_signal: str, signal_type: str
    ) -> dict[str, str]:
        """Service entrypoint: fetch the image for one image-request event.

        Returns a dict with ``image_b64`` (base64-encoded image bytes, empty
        if unavailable) and ``mime_type`` (sniffed from the bytes' magic).
        """
        try:
            image_bytes = await self.coordinator.async_fetch_event_image(
                id_signal, signal_type
            )
        except Exception:  # pylint: disable=broad-exception-caught
            _LOGGER.warning(
                "Failed to fetch activity image for id_signal=%s",
                id_signal,
                exc_info=True,
            )
            return {"image_b64": "", "mime_type": ""}
        if not image_bytes:
            return {"image_b64": "", "mime_type": ""}
        return {
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
            "mime_type": _sniff_image_mime(image_bytes),
        }

    @property
    def native_value(self) -> str | None:  # type: ignore[override]
        data = self.coordinator.data
        if data is None or not data.events:
            return None
        return self._format_state(data.events[0])

    @staticmethod
    def _format_state(event: ActivityEvent) -> str:
        """Render an event as ``"<alias> (by <user>|(<device>)) at HH:MM"``."""
        parts = [event.alias]
        if event.verisure_user:
            parts.append(f"by {event.verisure_user}")
        elif event.device_name:
            parts.append(f"({event.device_name})")
        # The API returns "YYYY-MM-DD HH:MM:SS" in panel-local time.  Slice
        # to HH:MM rather than parsing — there is no timezone to interpret.
        if event.time and len(event.time) >= 16:
            parts.append(f"at {event.time[11:16]}")
        return " ".join(parts)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:  # type: ignore[override]
        data = self.coordinator.data
        cache_key = id(data) if data is not None else None
        if cache_key == self._attrs_cache_key:
            return self._attrs_cache
        if data is None or not data.events:
            attrs: dict[str, Any] = {"events": []}
        else:
            events = data.events[:_ACTIVITY_LOG_LIMIT]
            attrs = {
                "latest": events[0].model_dump(),
                "events": [ev.model_dump() for ev in events],
            }
        self._attrs_cache_key = cache_key
        self._attrs_cache = attrs
        return attrs
