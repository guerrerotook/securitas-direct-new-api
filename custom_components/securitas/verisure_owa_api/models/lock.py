"""Smart-lock domain models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..pydantic_utils import NullSafeBase as _NullSafeBase


class LockAutolock(BaseModel):
    """Lock auto-lock configuration."""

    active: bool | None = None
    timeout: str | int | None = None


class LockFeatures(BaseModel):
    """Lock feature configuration."""

    model_config = ConfigDict(populate_by_name=True)

    hold_back_latch_time: int = Field(default=0, validation_alias="holdBackLatchTime")
    calibration_type: int = Field(default=0, validation_alias="calibrationType")
    autolock: LockAutolock | None = None


class SmartLock(_NullSafeBase):
    """Smart lock discovery response."""

    model_config = ConfigDict(populate_by_name=True)

    res: str | None = None
    location: str | None = None
    device_id: str = Field(default="", validation_alias="deviceId")
    reference_id: str = Field(default="", validation_alias="referenceId")
    zone_id: str = Field(default="", validation_alias="zoneId")
    serial_number: str = Field(default="", validation_alias="serialNumber")
    family: str = ""
    label: str = ""
    features: LockFeatures | None = None


class SmartLockMode(_NullSafeBase):
    """Smart lock mode and status."""

    model_config = ConfigDict(populate_by_name=True)

    res: str | None = None
    lock_status: str = Field(default="", validation_alias="lockStatus")
    device_id: str = Field(default="", validation_alias="deviceId")
    status_timestamp: str = Field(default="", validation_alias="statusTimestamp")


class SmartLockModeStatus(_NullSafeBase):
    """Smart lock mode change operation status."""

    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(default="", validation_alias="requestId")
    message: str = Field(default="", validation_alias="msg")
    protom_response: str = Field(default="", validation_alias="protomResponse")
    status: str = ""
