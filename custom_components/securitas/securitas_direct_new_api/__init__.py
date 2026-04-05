"""Interface with Securitas Direct alarms."""

import logging

from .apimanager import ApiManager, generate_device_id, generate_uuid  # noqa: F401
from .const import (  # noqa: F401
    CommandType,
    PERI_DEFAULTS,
    PERI_OPTIONS,
    PROTO_DISARMED,
    PROTO_TO_STATE,
    STD_DEFAULTS,
    STD_OPTIONS,
    STATE_LABELS,
    STATE_TO_COMMAND,
    SecuritasState,
)
from .models import (  # noqa: F401
    AirQuality,
    AlarmState,
    ArmCommand,
    Attribute,
    CameraDevice,
    Installation,
    InteriorMode,
    LockAutolock,
    LockFeatures,
    OperationStatus,
    OtpPhone,
    PerimeterMode,
    ProtoCode,
    Sentinel,
    Service,
    SStatus,
    SmartLock,
    SmartLockMode,
    SmartLockModeStatus,
    ThumbnailResponse,
    parse_proto_code,
)
from .domains import ApiDomains  # noqa: F401
from .exceptions import (  # noqa: F401
    AccountBlockedError,
    ArmingExceptionError,
    AuthenticationError,
    SecuritasDirectError,
    TwoFactorRequiredError,
)

_LOGGER = logging.getLogger(__name__)
