"""Sentinel environmental-sensor models."""

from __future__ import annotations

from pydantic import BaseModel


class Sentinel(BaseModel):
    """Sentinel environmental sensor status."""

    alias: str
    air_quality: str
    humidity: int
    temperature: int
    zone: str = ""


class AirQuality(BaseModel):
    """Air quality reading from xSAirQuality API."""

    value: int | None
    status_current: int = 0
