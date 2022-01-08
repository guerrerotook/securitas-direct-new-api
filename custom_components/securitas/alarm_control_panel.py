"""Support for Securitas Direct (AKA Verisure EU) alarm control panels."""

import datetime
from datetime import timedelta
import logging
from time import sleep

import homeassistant.components.alarm_control_panel as alarm
from homeassistant.components.alarm_control_panel.const import (
    SUPPORT_ALARM_ARM_AWAY,
    SUPPORT_ALARM_ARM_CUSTOM_BYPASS,
    SUPPORT_ALARM_ARM_HOME,
    SUPPORT_ALARM_ARM_NIGHT,
)
from homeassistant.const import (  # STATE_UNAVAILABLE,; STATE_UNKNOWN,
    CONF_CODE,
    STATE_ALARM_ARMED_AWAY,
    STATE_ALARM_ARMED_CUSTOM_BYPASS,
    STATE_ALARM_ARMED_HOME,
    STATE_ALARM_ARMED_NIGHT,
    STATE_ALARM_ARMING,
    STATE_ALARM_DISARMED,
    STATE_ALARM_DISARMING,
    STATE_ALARM_TRIGGERED,
)

from . import CONF_ALARM, CONF_CODE_DIGITS, HUB as hub
from .securitas_direct_new_api.dataTypes import (
    ArmStatus,
    ArmType,
    CheckAlarmStatus,
    Installation,
)

# from securitas import SecuritasAPIClient

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=1200)

# some reported by @furetto72@Italy
SECURITAS_STATUS = {
    STATE_ALARM_DISARMED: ["0", ("1", "32")],
    STATE_ALARM_ARMED_HOME: ["P", ("311", "202")],
    STATE_ALARM_ARMED_NIGHT: [("Q", "C"), ("46",)],
    STATE_ALARM_ARMED_AWAY: [("1", "A"), ("2", "31")],
    STATE_ALARM_ARMED_CUSTOM_BYPASS: ["3", ("204",)],
    STATE_ALARM_TRIGGERED: ["???", ("13", "24")],
}


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Securitas platform."""
    alarms = []
    if int(hub.config.get(CONF_ALARM, 1)):
        for item in hub.installations:
            current_state: CheckAlarmStatus = hub.update_overview(
                item, no_throttle=True
            )
            alarms.append(
                SecuritasAlarm(
                    item, state=current_state, digits=hub.config.get(CONF_CODE_DIGITS)
                )
            )
    add_entities(alarms)


def set_arm_state(state, code=None):
    """Send set arm state command."""
    # hub.session.api_call(state)
    _LOGGER.error("Securitas: esternal set arm state %s", state)
    # sleep(2)
    # hub.update_overview(no_throttle=True)


class SecuritasAlarm(alarm.AlarmControlPanelEntity):
    """Representation of a Securitas alarm status."""

    def __init__(
        self, installation: Installation, state: CheckAlarmStatus, digits: int
    ) -> None:
        """Initialize the Securitas alarm panel."""
        self._state: str = STATE_ALARM_DISARMED
        self._last_status: str = STATE_ALARM_DISARMED
        self._digits: int = digits
        self._changed_by = None
        self._device = installation.address
        self.entity_id = f"securitas_direct.{installation.number}"
        self._attr_unique_id = f"securitas_direct.{installation.number}"
        self._time: datetime.datetime = datetime.datetime.now()
        self._message = ""
        self.installation = installation
        self.update_status_alarm(state)

    def __force_state(self, state):
        self._last_status = self._state
        self._state = state
        self.hass.states.set(self.entity_id, state)

    def get_arm_state(self):
        """Get alarm state."""
        referenceId: str = hub.session.check_alarm(self.installation)
        sleep(1)
        alarm_status: CheckAlarmStatus = hub.session.check_alarm_status(
            self.installation, referenceId
        )
        while alarm_status.status == "WAIT":
            sleep(1)
            alarm_status: CheckAlarmStatus = hub.session.check_alarm_status(
                self.installation, referenceId
            )

    def set_arm_state(self, state, attempts=3):
        """Send set arm state command."""
        if state == "DARM1":
            response = hub.session.disarm_alarm(
                self.installation, self._getProtoStatus()
            )
            if response[0]:
                # check arming status
                sleep(1)
                count = 1
                arm_status: ArmStatus = hub.session.check_disarm_status(
                    self.installation,
                    response[1],
                    ArmType.TOTAL,
                    count,
                    self._getProtoStatus(),
                )
                while arm_status.status == "WAIT":
                    count = count + 1
                    sleep(1)
                    arm_status = hub.session.check_disarm_status(
                        self.installation, response[1], ArmType.TOTAL, count
                    )
                self._state = STATE_ALARM_DISARMED
            else:
                _LOGGER.error(response[1])
        else:
            response = hub.session.arm_alarm(
                self.installation, state, self._getProtoStatus()
            )
            if response[0]:
                # check arming status
                sleep(1)
                count = 1
                arm_status: ArmStatus = hub.session.check_arm_status(
                    self.installation, response[1], state, count, self._getProtoStatus()
                )
                while arm_status.status == "WAIT":
                    count = count + 1
                    sleep(1)
                    arm_status = hub.session.check_arm_status(
                        self.installation, response[1], ArmType.TOTAL, count
                    )
                self._state = STATE_ALARM_ARMED_AWAY
            else:
                _LOGGER.error(response[1])
        self.schedule_update_ha_state()
        # hub.update_overview(no_throttle=True)

    @property
    def name(self):
        """Return the name of the device."""
        return self.installation.alias

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def code_format(self):
        """Return one or more digits/characters."""
        return alarm.FORMAT_NUMBER

    @property
    def code_arm_required(self):
        """Whether the code is required for arm actions."""
        return False

    @property
    def changed_by(self):
        """Return the last change triggered by."""
        return self._changed_by

    def _getProtoStatus(self) -> str:
        if self._last_status == STATE_ALARM_DISARMED:
            return "D"
        elif self._last_status == STATE_ALARM_ARMED_AWAY:
            return "T"
        elif self._last_status == STATE_ALARM_ARMED_NIGHT:
            return "Q"
        elif self._last_status == STATE_ALARM_ARMED_HOME:
            return "P"
        else:
            return "D"

    def update_status_alarm(self, status: CheckAlarmStatus = None):
        """Update alarm status, from last alarm setting register or EST."""
        if status is not None:
            self._message = status.message
            # self._time = datetime.datetime.fromisoformat(status.protomResponseData)

            if status.protomResponse == "D":
                # disarmed
                self._state = STATE_ALARM_DISARMED
            elif status.protomResponse == "T":
                self._state = STATE_ALARM_ARMED_AWAY
            elif status.protomResponse == "Q":
                self._state = STATE_ALARM_ARMED_NIGHT
            elif status.protomResponse == "P":
                self._state = STATE_ALARM_ARMED_HOME
            elif status.protomResponse == "E":
                self._state = STATE_ALARM_ARMED_CUSTOM_BYPASS

    def update(self):
        """Update the status of the alarm based on the configuration."""
        alarmStatus: CheckAlarmStatus = hub.update_overview(
            self.installation, no_throttle=True
        )
        self.update_status_alarm(alarmStatus)

    def alarm_disarm(self, code=None):
        """Send disarm command."""
        if hub.config.get(CONF_CODE, "") == "" or hub.config.get(CONF_CODE, "") == code:
            self.__force_state(STATE_ALARM_DISARMING)
            self.set_arm_state("DARM1")

    def alarm_arm_home(self, code=None):
        """Send arm home command."""
        self.__force_state(STATE_ALARM_ARMING)
        self.set_arm_state("ARMDAY1")

    def alarm_arm_away(self, code=None):
        """Send arm away command."""
        self.__force_state(STATE_ALARM_ARMING)
        self.set_arm_state("ARM1")

    def alarm_arm_night(self, code=None):
        """Send arm home command."""
        self.__force_state(STATE_ALARM_ARMING)
        self.set_arm_state("ARMNIGHT1")

    def alarm_arm_custom_bypass(self, code=None):
        """Send arm perimeter command."""
        self.__force_state(STATE_ALARM_ARMING)
        self.set_arm_state("PERI1")

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return (
            SUPPORT_ALARM_ARM_HOME
            | SUPPORT_ALARM_ARM_AWAY
            | SUPPORT_ALARM_ARM_NIGHT
            | SUPPORT_ALARM_ARM_HOME
            | SUPPORT_ALARM_ARM_CUSTOM_BYPASS
        )
