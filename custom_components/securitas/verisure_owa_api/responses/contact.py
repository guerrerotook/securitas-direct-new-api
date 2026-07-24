"""Magnetic contact GraphQL response envelopes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..models import ContactState
from ..pydantic_utils import NullSafeBase as _NullSafeBase


class ContactStatusEnvelope(BaseModel):
    """Response envelope for xSGetDSRDevicesInfo."""

    class _Inner(_NullSafeBase):
        model_config = ConfigDict(populate_by_name=True)

        res: str = ""
        arm_status: str | int | None = Field(default=None, validation_alias="armStatus")
        timestamp: str | None = None
        devices: list[ContactState] | None = None

    class Data(BaseModel):
        xSGetDSRDevicesInfo: "ContactStatusEnvelope._Inner"  # noqa: N815

    data: Data
