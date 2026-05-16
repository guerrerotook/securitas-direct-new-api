"""Alarm-domain GraphQL response envelopes."""

# pylint: disable=missing-class-docstring

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..models import SStatus
from ..pydantic_utils import NullSafeBase as _NullSafeBase
from ._base import _OperationResult, _ResMsgRef


class CheckAlarmEnvelope(BaseModel):
    """Response envelope for xSCheckAlarm."""

    class Data(BaseModel):
        xSCheckAlarm: _ResMsgRef  # noqa: N815

    data: Data


class CheckAlarmStatusEnvelope(BaseModel):
    """Response envelope for xSCheckAlarmStatus."""

    class Data(BaseModel):
        xSCheckAlarmStatus: _OperationResult  # noqa: N815

    data: Data


class GeneralStatusEnvelope(BaseModel):
    """Response envelope for xSStatus."""

    class Data(BaseModel):
        xSStatus: SStatus  # noqa: N815

    data: Data


class ArmPanelEnvelope(BaseModel):
    """Response envelope for xSArmPanel."""

    class Data(BaseModel):
        xSArmPanel: _ResMsgRef  # noqa: N815

    data: Data


class ArmStatusEnvelope(BaseModel):
    """Response envelope for xSArmStatus."""

    class Data(BaseModel):
        xSArmStatus: _OperationResult  # noqa: N815

    data: Data


class DisarmPanelEnvelope(BaseModel):
    """Response envelope for xSDisarmPanel."""

    class Data(BaseModel):
        xSDisarmPanel: _ResMsgRef  # noqa: N815

    data: Data


class DisarmStatusEnvelope(BaseModel):
    """Response envelope for xSDisarmStatus."""

    class Data(BaseModel):
        xSDisarmStatus: _OperationResult  # noqa: N815

    data: Data


class GetExceptionsEnvelope(BaseModel):
    """Response envelope for xSGetExceptions."""

    class _ZoneException(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        status: str | None = None
        device_type: str | None = Field(default=None, validation_alias="deviceType")
        alias: str | None = None

    class _Inner(_NullSafeBase):
        res: str = ""
        msg: str | None = None
        exceptions: "list[GetExceptionsEnvelope._ZoneException] | None" = None

    class Data(BaseModel):
        xSGetExceptions: "GetExceptionsEnvelope._Inner"  # noqa: N815

    data: Data
