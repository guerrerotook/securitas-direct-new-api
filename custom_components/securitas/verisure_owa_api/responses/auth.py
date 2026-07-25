"""Auth-flow GraphQL response envelopes."""

# pylint: disable=missing-class-docstring

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..pydantic_utils import NullSafeBase as _NullSafeBase
from ._base import _ResMsg


class LoginEnvelope(BaseModel):
    """Response envelope for xSLoginToken."""

    class _Inner(_NullSafeBase):
        model_config = ConfigDict(populate_by_name=True)

        res: str = ""
        msg: str | None = None
        hash: str | None = None
        refresh_token: str | None = Field(default=None, validation_alias="refreshToken")
        legals: Any | None = None
        change_password: bool | None = Field(
            default=None, validation_alias="changePassword"
        )
        need_device_authorization: bool | None = Field(
            None, validation_alias="needDeviceAuthorization"
        )
        main_user: bool | None = Field(default=None, validation_alias="mainUser")

    class Data(BaseModel):
        xSLoginToken: LoginEnvelope._Inner

    data: Data


class RefreshLoginEnvelope(BaseModel):
    """Response envelope for xSRefreshLogin."""

    class _Inner(_NullSafeBase):
        model_config = ConfigDict(populate_by_name=True)

        res: str = ""
        msg: str | None = None
        hash: str | None = None
        refresh_token: str | None = Field(default=None, validation_alias="refreshToken")
        legals: Any | None = None
        change_password: bool | None = Field(
            default=None, validation_alias="changePassword"
        )
        need_device_authorization: bool | None = Field(
            None, validation_alias="needDeviceAuthorization"
        )
        main_user: bool | None = Field(default=None, validation_alias="mainUser")

    class Data(BaseModel):
        xSRefreshLogin: RefreshLoginEnvelope._Inner

    data: Data


class ValidateDeviceEnvelope(BaseModel):
    """Response envelope for xSValidateDevice."""

    class _Inner(_NullSafeBase):
        model_config = ConfigDict(populate_by_name=True)

        res: str = ""
        msg: str | None = None
        hash: str | None = None
        refresh_token: str | None = Field(default=None, validation_alias="refreshToken")
        legals: Any | None = None

    class Data(BaseModel):
        xSValidateDevice: ValidateDeviceEnvelope._Inner

    data: Data


class SendOtpEnvelope(BaseModel):
    """Response envelope for xSSendOtp."""

    class Data(BaseModel):
        xSSendOtp: _ResMsg

    data: Data
