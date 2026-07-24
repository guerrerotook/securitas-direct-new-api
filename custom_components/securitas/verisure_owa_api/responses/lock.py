"""Smart-lock GraphQL response envelopes."""

# pylint: disable=missing-class-docstring

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models import LockFeatures, SmartLock
from ..pydantic_utils import NullSafeBase as _NullSafeBase
from ._base import _ResMsgRef


class SmartlockConfigEnvelope(BaseModel):
    """Response envelope for xSGetSmartlockConfig."""

    class Data(BaseModel):
        xSGetSmartlockConfig: SmartLock

    data: Data


class DanalockConfigEnvelope(BaseModel):
    """Response envelope for xSGetDanalockConfig."""

    class Data(BaseModel):
        xSGetDanalockConfig: _ResMsgRef

    data: Data


class DanalockConfigStatusEnvelope(BaseModel):
    """Response envelope for xSGetDanalockConfigStatus."""

    class _Inner(_NullSafeBase):
        model_config = ConfigDict(populate_by_name=True)

        res: str = ""
        msg: str | None = None
        device_number: str | None = Field(default=None, validation_alias="deviceNumber")
        features: LockFeatures | None = None

    class Data(BaseModel):
        xSGetDanalockConfigStatus: DanalockConfigStatusEnvelope._Inner

    data: Data


class LockModeEnvelope(BaseModel):
    """Response envelope for xSGetLockCurrentMode."""

    class _Inner(_NullSafeBase):
        model_config = ConfigDict(populate_by_name=True)

        res: str = ""
        smartlock_info: list[dict[str, Any]] | None = Field(
            None, validation_alias="smartlockInfo"
        )

    class Data(BaseModel):
        xSGetLockCurrentMode: LockModeEnvelope._Inner

    data: Data


class ChangeLockModeEnvelope(BaseModel):
    """Response envelope for xSChangeSmartlockMode."""

    class Data(BaseModel):
        xSChangeSmartlockMode: _ResMsgRef

    data: Data


class ChangeLockModeStatusEnvelope(BaseModel):
    """Response envelope for xSChangeSmartlockModeStatus."""

    class _Inner(_NullSafeBase):
        model_config = ConfigDict(populate_by_name=True)

        res: str = ""
        msg: str | None = None
        protom_response: str | None = Field(
            default=None, validation_alias="protomResponse"
        )
        status: str | None = None

    class Data(BaseModel):
        xSChangeSmartlockModeStatus: ChangeLockModeStatusEnvelope._Inner

    data: Data
