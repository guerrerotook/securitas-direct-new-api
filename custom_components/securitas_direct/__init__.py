"""Support for Securitas Direct alarms."""
from datetime import timedelta
import logging
import threading
from time import sleep
from typing import List, Tuple

import voluptuous as vol

from homeassistant.const import (
    CONF_CODE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.helpers import discovery
import homeassistant.helpers.config_validation as cv
from homeassistant.util import Throttle

from .securitas_direct_new_api.apimanager import ApiManager
from .securitas_direct_new_api.dataTypes import CheckAlarmStatus, Installation

_LOGGER = logging.getLogger(__name__)

CONF_ALARM = "alarm"
CONF_CODE_DIGITS = "code_digits"
CONF_COUNTRY = "country"

DOMAIN = "securitas_direct"

MIN_SCAN_INTERVAL = timedelta(seconds=20)
DEFAULT_SCAN_INTERVAL = timedelta(seconds=40)

HUB = None

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Required(CONF_USERNAME): cv.string,
                vol.Optional(CONF_COUNTRY, default="ES"): cv.string,
                vol.Optional(CONF_ALARM, default=True): cv.boolean,
                vol.Optional(CONF_CODE_DIGITS, default=4): cv.positive_int,
                vol.Optional(CONF_CODE, default=""): cv.string,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): (
                    vol.All(cv.time_period, vol.Clamp(min=MIN_SCAN_INTERVAL))
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def setup(hass, config):
    """Set up the Securitas component."""
    global HUB
    HUB = SecuritasHub(config[DOMAIN])
    HUB.update_overview = Throttle(config[DOMAIN][CONF_SCAN_INTERVAL])(
        HUB.update_overview
    )
    if not HUB.login():
        return False
    hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, lambda event: HUB.logout())
    # for Installation in HUB.Installations:
    #    HUB.update_overview(Installation)
    for component in ("alarm_control_panel",):
        discovery.load_platform(hass, component, DOMAIN, {}, config)
    return True


class SecuritasHub:
    """A Securitas hub wrapper class."""

    def __init__(self, domain_config):
        """Initialize the Securitas hub."""
        self.overview: CheckAlarmStatus = {}
        self.config = domain_config
        self._lock = threading.Lock()
        country = domain_config[CONF_COUNTRY].upper()
        lang = country.lower() if country != "UK" else "en"
        self.session = ApiManager(
            domain_config[CONF_USERNAME],
            domain_config[CONF_PASSWORD],
            country=country,
            language=lang,
        )
        self.Installations: List[Installation] = []

    def login(self):
        """Login to Securitas."""
        succeed: Tuple[bool, str] = self.session.login()
        _LOGGER.debug("Log in Securitas: %s", succeed[0])
        if not succeed[0]:
            _LOGGER.error("Could not log in to Securitas: %s", succeed[1])
            return False
        self.Installations = self.session.listInstallations()
        return True

    def logout(self):
        """Logout from Securitas."""
        ret = self.session.logout()
        if not ret:
            _LOGGER.error("Could not log out from Securitas: %s", ret)
            return False
        return True

    def update_overview(self, Installation: Installation) -> CheckAlarmStatus:
        """Update the overview."""
        # self.overview = self.session.checkAlarm(Installation)

        referenceId: str = self.session.checkAlarm(Installation)
        if not referenceId:
            return None
        sleep(1)
        alarmStatus: CheckAlarmStatus = self.session.checkAlarmStatus(
            Installation, referenceId
        )
        if not alarmStatus:
            return None
        while alarmStatus.operationStatus == "WAIT":
            sleep(1)
            alarmStatus = self.session.checkAlarmStatus(Installation, referenceId)
            if not alarmStatus:
                return None
        return alarmStatus
