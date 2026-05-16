"""Camera domain models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CameraDevice(BaseModel):
    """A camera device from xSDeviceList (QR, YR, YP, or QP cameras)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    code: int = 0
    zone_id: str = Field(default="", validation_alias="zoneId")
    name: str = ""
    device_type: str = Field(default="", validation_alias="type")
    serial_number: str | None = Field(default=None, validation_alias="serialNumber")


class ThumbnailResponse(BaseModel):
    """Response from xSGetThumbnail."""

    model_config = ConfigDict(populate_by_name=True)

    id_signal: str | None = Field(default=None, validation_alias="idSignal")
    device_code: str | None = Field(default=None, validation_alias="deviceCode")
    device_alias: str | None = Field(default=None, validation_alias="deviceAlias")
    timestamp: str | None = None
    signal_type: str | None = Field(default=None, validation_alias="signalType")
    image: str | None = None
