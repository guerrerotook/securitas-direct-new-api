"""GraphQL response envelope models for the Securitas Direct API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import Installation, LockFeatures, SmartLock, ThumbnailResponse


# ── Shared inner models ────────────────────────────────────────────────────────


class _ResMsg(BaseModel):
    """Simple result + message pair."""

    res: str
    msg: str | None = None


class _ResMsgRef(BaseModel):
    """Result, message, and reference ID."""

    model_config = ConfigDict(populate_by_name=True)

    res: str
    msg: str | None = None
    reference_id: str = Field(alias="referenceId")


class PanelError(BaseModel):
    """Error detail returned by panel operations."""

    model_config = ConfigDict(populate_by_name=True)

    code: str | None = None
    type: str | None = None
    allow_forcing: bool | None = Field(None, alias="allowForcing")
    exceptions_number: int | None = Field(None, alias="exceptionsNumber")
    reference_id: str | None = Field(None, alias="referenceId")
    suid: str | None = None


class _OperationResult(BaseModel):
    """Result of an alarm or lock operation."""

    model_config = ConfigDict(populate_by_name=True)

    res: str
    msg: str | None = None
    status: str | None = None
    numinst: str | None = None
    protom_response: str | None = Field(None, alias="protomResponse")
    protom_response_data: str | None = Field(None, alias="protomResponseDate")
    request_id: str | None = Field(None, alias="requestId")
    error: PanelError | None = None


class _GeneralStatus(BaseModel):
    """Current status of the alarm system."""

    model_config = ConfigDict(populate_by_name=True)

    status: str | None = None
    timestamp_update: str | None = Field(None, alias="timestampUpdate")
    wifi_connected: bool | None = Field(None, alias="wifiConnected")
    exceptions: list[dict[str, Any]] | None = None


# ── Auth envelopes ─────────────────────────────────────────────────────────────


class LoginEnvelope(BaseModel):
    """Response envelope for xSLoginToken."""

    class _Inner(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        res: str
        msg: str | None = None
        hash: str | None = None  # noqa: A003
        refresh_token: str | None = Field(None, alias="refreshToken")
        legals: Any | None = None
        change_password: bool | None = Field(None, alias="changePassword")
        need_device_authorization: bool | None = Field(
            None, alias="needDeviceAuthorization"
        )
        main_user: bool | None = Field(None, alias="mainUser")

    class Data(BaseModel):
        xSLoginToken: "LoginEnvelope._Inner"  # noqa: N815

    data: Data


class RefreshLoginEnvelope(BaseModel):
    """Response envelope for xSRefreshLogin."""

    class _Inner(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        res: str
        msg: str | None = None
        hash: str | None = None  # noqa: A003
        refresh_token: str | None = Field(None, alias="refreshToken")
        legals: Any | None = None
        change_password: bool | None = Field(None, alias="changePassword")
        need_device_authorization: bool | None = Field(
            None, alias="needDeviceAuthorization"
        )
        main_user: bool | None = Field(None, alias="mainUser")

    class Data(BaseModel):
        xSRefreshLogin: "RefreshLoginEnvelope._Inner"  # noqa: N815

    data: Data


class ValidateDeviceEnvelope(BaseModel):
    """Response envelope for xSValidateDevice."""

    class _Inner(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        res: str
        msg: str | None = None
        hash: str | None = None  # noqa: A003
        refresh_token: str | None = Field(None, alias="refreshToken")
        legals: Any | None = None

    class Data(BaseModel):
        xSValidateDevice: "ValidateDeviceEnvelope._Inner"  # noqa: N815

    data: Data


class SendOtpEnvelope(BaseModel):
    """Response envelope for xSSendOtp."""

    class Data(BaseModel):
        xSSendOtp: _ResMsg  # noqa: N815

    data: Data


# ── Installation & Services envelopes ─────────────────────────────────────────


class InstallationListEnvelope(BaseModel):
    """Response envelope for xSInstallations."""

    class _Inner(BaseModel):
        installations: list[Installation]

    class Data(BaseModel):
        xSInstallations: "InstallationListEnvelope._Inner"  # noqa: N815

    data: Data


class ServicesEnvelope(BaseModel):
    """Response envelope for xSSrv."""

    class _Installation(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        numinst: str | None = None
        capabilities: str | None = None
        services: list[dict[str, Any]] = Field(default_factory=list)
        config_repo_user: dict[str, Any] | None = Field(None, alias="configRepoUser")

    class _Inner(BaseModel):
        res: str
        msg: str | None = None
        installation: "ServicesEnvelope._Installation | None" = None

    class Data(BaseModel):
        xSSrv: "ServicesEnvelope._Inner"  # noqa: N815

    data: Data


# ── Alarm envelopes ───────────────────────────────────────────────────────────


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
        xSStatus: _GeneralStatus  # noqa: N815

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
        device_type: str | None = Field(None, alias="deviceType")
        alias: str | None = None

    class _Inner(BaseModel):
        res: str
        msg: str | None = None
        exceptions: "list[GetExceptionsEnvelope._ZoneException] | None" = None

    class Data(BaseModel):
        xSGetExceptions: "GetExceptionsEnvelope._Inner"  # noqa: N815

    data: Data


# ── Lock envelopes ────────────────────────────────────────────────────────────


class SmartlockConfigEnvelope(BaseModel):
    """Response envelope for xSGetSmartlockConfig."""

    class Data(BaseModel):
        xSGetSmartlockConfig: SmartLock  # noqa: N815

    data: Data


class DanalockConfigEnvelope(BaseModel):
    """Response envelope for xSGetDanalockConfig."""

    class Data(BaseModel):
        xSGetDanalockConfig: _ResMsgRef  # noqa: N815

    data: Data


class DanalockConfigStatusEnvelope(BaseModel):
    """Response envelope for xSGetDanalockConfigStatus."""

    class _Inner(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        res: str
        msg: str | None = None
        device_number: str | None = Field(None, alias="deviceNumber")
        features: LockFeatures | None = None

    class Data(BaseModel):
        xSGetDanalockConfigStatus: "DanalockConfigStatusEnvelope._Inner"  # noqa: N815

    data: Data


class LockModeEnvelope(BaseModel):
    """Response envelope for xSGetLockCurrentMode."""

    class _Inner(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        res: str
        smartlock_info: list[dict[str, Any]] | None = Field(None, alias="smartlockInfo")

    class Data(BaseModel):
        xSGetLockCurrentMode: "LockModeEnvelope._Inner"  # noqa: N815

    data: Data


class ChangeLockModeEnvelope(BaseModel):
    """Response envelope for xSChangeSmartlockMode."""

    class Data(BaseModel):
        xSChangeSmartlockMode: _ResMsgRef  # noqa: N815

    data: Data


class ChangeLockModeStatusEnvelope(BaseModel):
    """Response envelope for xSChangeSmartlockModeStatus."""

    class _Inner(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        res: str
        msg: str | None = None
        protom_response: str | None = Field(None, alias="protomResponse")
        status: str | None = None

    class Data(BaseModel):
        xSChangeSmartlockModeStatus: "ChangeLockModeStatusEnvelope._Inner"  # noqa: N815

    data: Data


# ── Camera envelopes ──────────────────────────────────────────────────────────


class DeviceListEnvelope(BaseModel):
    """Response envelope for xSDeviceList."""

    class _Inner(BaseModel):
        res: str
        devices: list[dict[str, Any]] | None = None

    class Data(BaseModel):
        xSDeviceList: "DeviceListEnvelope._Inner"  # noqa: N815

    data: Data


class RequestImagesEnvelope(BaseModel):
    """Response envelope for xSRequestImages."""

    class Data(BaseModel):
        xSRequestImages: _ResMsgRef  # noqa: N815

    data: Data


class RequestImagesStatusEnvelope(BaseModel):
    """Response envelope for xSRequestImagesStatus."""

    class _Inner(BaseModel):
        res: str
        msg: str | None = None
        numinst: str | None = None
        status: str | None = None

    class Data(BaseModel):
        xSRequestImagesStatus: "RequestImagesStatusEnvelope._Inner"  # noqa: N815

    data: Data


class ThumbnailEnvelope(BaseModel):
    """Response envelope for xSGetThumbnail."""

    class Data(BaseModel):
        xSGetThumbnail: ThumbnailResponse  # noqa: N815

    data: Data


class PhotoImagesEnvelope(BaseModel):
    """Response envelope for xSGetPhotoImages."""

    class _Inner(BaseModel):
        devices: list[dict[str, Any]] | None = None

    class Data(BaseModel):
        xSGetPhotoImages: "PhotoImagesEnvelope._Inner"  # noqa: N815

    data: Data


# ── Sentinel envelopes ────────────────────────────────────────────────────────


class SentinelEnvelope(BaseModel):
    """Response envelope for xSComfort."""

    class _Inner(BaseModel):
        res: str
        devices: list[dict[str, Any]] | None = None
        forecast: dict[str, Any] | None = None

    class Data(BaseModel):
        xSComfort: "SentinelEnvelope._Inner"  # noqa: N815

    data: Data


class AirQualityEnvelope(BaseModel):
    """Response envelope for xSAirQuality."""

    class _Inner(BaseModel):
        res: str
        data: dict[str, Any] | None = None

    class Data(BaseModel):
        xSAirQuality: "AirQualityEnvelope._Inner"  # noqa: N815

    data: Data


# ── Error envelopes ───────────────────────────────────────────────────────────


class GraphQLErrorData(BaseModel):
    """Structured data payload inside a GraphQL error."""

    model_config = ConfigDict(populate_by_name=True)

    reason: str | None = None
    status: int | None = None
    need_device_authorization: bool | None = Field(
        None, alias="needDeviceAuthorization"
    )
    auth_otp_hash: str | None = Field(None, alias="auth-otp-hash")
    auth_phones: list[dict[str, Any]] | None = Field(None, alias="auth-phones")


class GraphQLError(BaseModel):
    """A single GraphQL error object."""

    message: str
    data: GraphQLErrorData | None = None


class ErrorResponse(BaseModel):
    """Top-level GraphQL error response."""

    errors: list[GraphQLError]
