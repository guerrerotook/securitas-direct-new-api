"""Panel-activity timeline response envelopes."""

# pylint: disable=missing-class-docstring

from __future__ import annotations

from pydantic import BaseModel

from ..models import ActivityEvent


class ActivityEnvelope(BaseModel):
    """Response envelope for xSActV2 (alarm panel activity timeline)."""

    class _Inner(BaseModel):
        reg: list[ActivityEvent] | None = None

    class Data(BaseModel):
        xSActV2: ActivityEnvelope._Inner

    data: Data
