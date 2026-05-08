"""Shared inner result/operation/error fragments used by domain envelopes."""

# pylint: disable=missing-class-docstring

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..pydantic_utils import NullSafeBase as _NullSafeBase


class _ResMsg(_NullSafeBase):
    """Simple result + message pair."""

    res: str = ""
    msg: str | None = None


class _ResMsgRef(_NullSafeBase):
    """Result, message, and reference ID."""

    model_config = ConfigDict(populate_by_name=True)

    res: str = ""
    msg: str | None = None
    reference_id: str = Field(default="", validation_alias="referenceId")


class PanelError(BaseModel):
    """Error detail returned by panel operations."""

    model_config = ConfigDict(populate_by_name=True)

    code: str | None = None
    type: str | None = None
    allow_forcing: bool | None = Field(default=None, validation_alias="allowForcing")
    exceptions_number: int | None = Field(
        default=None, validation_alias="exceptionsNumber"
    )
    reference_id: str | None = Field(default=None, validation_alias="referenceId")
    suid: str | None = None


class _OperationResult(_NullSafeBase):
    """Result of an alarm or lock operation."""

    model_config = ConfigDict(populate_by_name=True)

    res: str = ""
    msg: str | None = None
    status: str | None = None
    numinst: str | None = None
    protom_response: str | None = Field(default=None, validation_alias="protomResponse")
    protom_response_date: str | None = Field(
        None, validation_alias="protomResponseDate"
    )
    request_id: str | None = Field(default=None, validation_alias="requestId")
    error: PanelError | None = None
