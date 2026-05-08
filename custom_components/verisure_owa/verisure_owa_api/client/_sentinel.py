"""Sentinel domain: comfort sensors and air-quality."""

from __future__ import annotations

import logging

from ..graphql_queries import AIR_QUALITY_QUERY, SENTINEL_QUERY
from ..models import AirQuality, Installation, Sentinel, Service
from ..responses import AirQualityEnvelope, SentinelEnvelope
from ._base import _ClientBase

_LOGGER = logging.getLogger(__name__)


class _SentinelMixin(_ClientBase):
    """Sentinel and air-quality reads."""

    async def get_sentinel_data(
        self,
        installation: Installation,
        service: Service,
    ) -> Sentinel:
        """Get sentinel environmental sensor data.

        Args:
            installation: The installation to query.
            service: The sentinel service (uses first attribute for zone).

        Returns:
            Sentinel with temperature, humidity, and air quality.
        """
        content = {
            "operationName": "Sentinel",
            "variables": {
                "numinst": installation.number,
            },
            "query": SENTINEL_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "Sentinel",
            SentinelEnvelope,
            installation=installation,
        )
        comfort_data = envelope.data.xSComfort
        empty = Sentinel(alias="", air_quality="", humidity=0, temperature=0)

        if not service.attributes or not isinstance(service.attributes, list):
            _LOGGER.warning("No attributes found for sentinel service %s", service.id)
            return empty

        zone = service.attributes[0].value
        devices = comfort_data.devices or []
        target_device = None
        for device in devices:
            if device.get("zone") == zone:
                target_device = device
                break

        if target_device is None:
            return empty

        air_quality_code = target_device["status"].get("airQualityCode")
        return Sentinel(
            alias=target_device["alias"],
            air_quality=str(air_quality_code) if air_quality_code is not None else "",
            humidity=int(target_device["status"]["humidity"]),
            temperature=int(target_device["status"]["temperature"]),
            zone=target_device.get("zone", ""),
        )

    async def get_air_quality_data(
        self,
        installation: Installation,
        zone: str,
    ) -> AirQuality | None:
        """Get air quality data from xSAirQuality API.

        Args:
            installation: The installation to query.
            zone: Zone identifier string.

        Returns:
            AirQuality with latest reading, or None if no data available.
        """
        content = {
            "operationName": "AirQuality",
            "variables": {
                "numinst": installation.number,
                "zone": zone,
            },
            "query": AIR_QUALITY_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "AirQuality",
            AirQualityEnvelope,
            installation=installation,
        )
        aq_inner = envelope.data.xSAirQuality
        aq_data = aq_inner.data
        if aq_data is None:
            return None

        # hours may be null for some installations while status is still valid
        value: int | None = None
        hours = aq_data.get("hours") or []
        if hours:
            try:
                value = int(hours[-1].get("value", 0))
            except (ValueError, TypeError):
                pass

        status = aq_data.get("status", {})
        return AirQuality(
            value=value,
            status_current=int(status.get("current", 0)),
        )
