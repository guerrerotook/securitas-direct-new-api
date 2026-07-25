"""Sentinel/air-quality response envelopes."""

# pylint: disable=missing-class-docstring

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..pydantic_utils import NullSafeBase as _NullSafeBase


class SentinelEnvelope(BaseModel):
    """Response envelope for xSComfort."""

    class _Inner(_NullSafeBase):
        res: str = ""
        devices: list[dict[str, Any]] | None = None
        forecast: dict[str, Any] | None = None

    class Data(BaseModel):
        xSComfort: SentinelEnvelope._Inner

    data: Data


class AirQualityEnvelope(BaseModel):
    """Response envelope for xSAirQuality."""

    class _Inner(_NullSafeBase):
        res: str = ""
        data: dict[str, Any] | None = None

    class Data(BaseModel):
        xSAirQuality: AirQualityEnvelope._Inner

    data: Data
