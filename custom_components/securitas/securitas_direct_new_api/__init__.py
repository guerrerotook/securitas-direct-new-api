"""Interface with Securitas Direct alarms."""

import logging

from .apimanager import ApiManager, generate_device_id, generate_uuid
from .const import SecDirAlarmState, CommandType
from .dataTypes import CheckAlarmStatus, Installation, OtpPhone, Service, SStatus
from .exceptions import Login2FAError, LoginError, SecuritasDirectError

_LOGGER = logging.getLogger(__name__)
