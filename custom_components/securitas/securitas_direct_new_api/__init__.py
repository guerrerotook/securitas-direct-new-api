"""Interface with Securitas Direct alarms."""

import logging

from .apimanager import ApiManager, generate_device_id, generate_uuid  # noqa: F401
from .const import (  # noqa: F401
    ALARM_STATUS_POLL_DELAY,
    COMPOUND_COMMAND_STEPS,
    CommandType,
    PERI_ARMED_PROTO_CODES,
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
from .dataTypes import (  # noqa: F401
    ArmStatus,
    CheckAlarmStatus,
    DisarmStatus,
    Installation,
    OtpPhone,
    Service,
    SStatus,
    SmartLockMode,
    SmartLockModeStatus,
)
from .domains import ApiDomains  # noqa: F401
from .exceptions import (  # noqa: F401
    ArmingExceptionError,
    Login2FAError,
    LoginError,
    SecuritasDirectError,
)

_LOGGER = logging.getLogger(__name__)
