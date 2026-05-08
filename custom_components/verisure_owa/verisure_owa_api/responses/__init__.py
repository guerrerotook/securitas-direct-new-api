"""GraphQL response envelope models for the Verisure OWA API.

Re-exports every public envelope so existing call sites that import from
``verisure_owa_api.responses`` keep working after the per-domain split.
"""

from ._base import _OperationResult, _ResMsg, _ResMsgRef, PanelError
from .activity import ActivityEnvelope
from .alarm import (
    ArmPanelEnvelope,
    ArmStatusEnvelope,
    CheckAlarmEnvelope,
    CheckAlarmStatusEnvelope,
    DisarmPanelEnvelope,
    DisarmStatusEnvelope,
    GeneralStatusEnvelope,
    GetExceptionsEnvelope,
)
from .auth import (
    LoginEnvelope,
    RefreshLoginEnvelope,
    SendOtpEnvelope,
    ValidateDeviceEnvelope,
)
from .camera import (
    DeviceListEnvelope,
    PhotoImagesEnvelope,
    RequestImagesEnvelope,
    RequestImagesStatusEnvelope,
    ThumbnailEnvelope,
)
from .errors import ErrorResponse, GraphQLError, GraphQLErrorData
from .installation import InstallationListEnvelope, ServicesEnvelope
from .lock import (
    ChangeLockModeEnvelope,
    ChangeLockModeStatusEnvelope,
    DanalockConfigEnvelope,
    DanalockConfigStatusEnvelope,
    LockModeEnvelope,
    SmartlockConfigEnvelope,
)
from .sentinel import AirQualityEnvelope, SentinelEnvelope

__all__ = [
    "ActivityEnvelope",
    "AirQualityEnvelope",
    "ArmPanelEnvelope",
    "ArmStatusEnvelope",
    "ChangeLockModeEnvelope",
    "ChangeLockModeStatusEnvelope",
    "CheckAlarmEnvelope",
    "CheckAlarmStatusEnvelope",
    "DanalockConfigEnvelope",
    "DanalockConfigStatusEnvelope",
    "DeviceListEnvelope",
    "DisarmPanelEnvelope",
    "DisarmStatusEnvelope",
    "ErrorResponse",
    "GeneralStatusEnvelope",
    "GetExceptionsEnvelope",
    "GraphQLError",
    "GraphQLErrorData",
    "InstallationListEnvelope",
    "LockModeEnvelope",
    "LoginEnvelope",
    "PanelError",
    "PhotoImagesEnvelope",
    "RefreshLoginEnvelope",
    "RequestImagesEnvelope",
    "RequestImagesStatusEnvelope",
    "SendOtpEnvelope",
    "SentinelEnvelope",
    "ServicesEnvelope",
    "SmartlockConfigEnvelope",
    "ThumbnailEnvelope",
    "ValidateDeviceEnvelope",
    "_OperationResult",
    "_ResMsg",
    "_ResMsgRef",
]
