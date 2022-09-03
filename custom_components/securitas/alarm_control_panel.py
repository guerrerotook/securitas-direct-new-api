"""Support for Securitas Direct (AKA Verisure EU) alarm control panels."""

import asyncio
import datetime
from datetime import timedelta
import logging

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
)

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import (
    DOMAIN,
    SecuritasDirectDevice,
    SecuritasHub,
)
from .securitas_direct_new_api.dataTypes import (
    ArmStatus,
    ArmType,
    CheckAlarmStatus,
    DisarmStatus,
    Installation,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=1200)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up MELCloud device sensors based on config_entry."""
    client: SecuritasHub = hass.data[DOMAIN][SecuritasHub.__name__]
    alarms = []
    securitas_devices: list[SecuritasDirectDevice] = hass.data[DOMAIN].get(
        entry.entry_id
    )
    for devices in securitas_devices:
        current_state: CheckAlarmStatus = await client.update_overview(
            devices.instalation
        )
        alarms.append(
            SecuritasAlarm(
                devices.instalation,
                state=current_state,
                digits=client.config.get(CONF_CODE),
                client=client,
                hass=hass,
            )
        )
    async_add_entities(alarms, True)


class SecuritasAlarm(alarm.AlarmControlPanelEntity):
    """Representation of a Securitas alarm status."""

    def __init__(
        self,
        installation: Installation,
        state: CheckAlarmStatus,
        digits: int,
        client: SecuritasHub,
        hass: HomeAssistant,
    ) -> None:
        """Initialize the Securitas alarm panel."""
        self._state: str = STATE_ALARM_DISARMED
        self._last_status: str = STATE_ALARM_DISARMED
        self._digits: int = digits
        self._changed_by = None
        self._device = installation.address
        self._entity_id = f"securitas_direct.{installation.number}"
        self._attr_unique_id = f"securitas_direct.{installation.number}"
        self._time: datetime.datetime = datetime.datetime.now()
        self._message = ""
        self.installation = installation
        self._attr_extra_state_attributes = {}
        self.client: SecuritasHub = client
        self.hass: HomeAssistant = hass

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer="Securitas Direct",
            model=installation.panel,
            name=installation.alias,
            hw_version=installation.type,
        )
        self.update_status_alarm(state)

    def __force_state(self, state: str):
        self._last_status = self._state
        self._state = state
        self.async_schedule_update_ha_state()
        # self.hass.states.set(self.entity_id, state)

    async def get_arm_state(self):
        """Get alarm state."""
        reference_id: str = self.client.session.check_alarm(self.installation)
        count: int = 1
        await asyncio.sleep(1)
        alarm_status: CheckAlarmStatus = await self.client.session.check_alarm_status(
            self.installation, reference_id, count
        )
        while alarm_status.status == "WAIT":
            await asyncio.sleep(1)
            count = count + 1
            alarm_status: CheckAlarmStatus = (
                await self.client.session.check_alarm_status(
                    self.installation, reference_id, count
                )
            )

    async def set_arm_state(self, state, attempts=3):
        """Send set arm state command."""
        if state == "DARM1":
            response = await self.client.session.disarm_alarm(
                self.installation, self._get_proto_status()
            )
            if response[0]:
                # check arming status
                await asyncio.sleep(1)
                count = 1
                disarm_status: DisarmStatus = (
                    await self.client.session.check_disarm_status(
                        self.installation,
                        response[1],
                        ArmType.TOTAL,
                        count,
                        self._get_proto_status(),
                    )
                )
                while disarm_status.operation_status == "WAIT":
                    count = count + 1
                    await asyncio.sleep(1)
                    disarm_status = await self.client.session.check_disarm_status(
                        self.installation,
                        response[1],
                        ArmType.TOTAL,
                        count,
                        self._get_proto_status(),
                    )
                self._attr_extra_state_attributes["message"] = disarm_status.message
                self._attr_extra_state_attributes[
                    "response_data"
                ] = disarm_status.protomResponseData
                self.update_status_alarm(
                    CheckAlarmStatus(
                        disarm_status.operation_status,
                        disarm_status.message,
                        disarm_status.status,
                        self.installation.number,
                        disarm_status.protomResponse,
                        disarm_status.protomResponseData,
                    )
                )

            else:
                _LOGGER.error(response[1])
        else:
            response = await self.client.session.arm_alarm(
                self.installation, state, self._get_proto_status()
            )
            if response[0]:
                # check arming status
                await asyncio.sleep(1)
                count = 1
                arm_status: ArmStatus = await self.client.session.check_arm_status(
                    self.installation,
                    response[1],
                    state,
                    count,
                    self._get_proto_status(),
                )
                while arm_status.operation_status == "WAIT":
                    count = count + 1
                    await asyncio.sleep(1)
                    arm_status = await self.client.session.check_arm_status(
                        self.installation,
                        response[1],
                        state,
                        count,
                        self._get_proto_status(),
                    )
                self._attr_extra_state_attributes["message"] = arm_status.message
                self._attr_extra_state_attributes[
                    "response_data"
                ] = arm_status.protomResponseData
                self.update_status_alarm(
                    CheckAlarmStatus(
                        arm_status.operation_status,
                        arm_status.message,
                        arm_status.status,
                        arm_status.InstallationNumer,
                        arm_status.protomResponse,
                        arm_status.protomResponseData,
                    )
                )
            else:
                _LOGGER.error(response[1])

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

    def _get_proto_status(self) -> str:
        """Get the string that represent the alarm status."""
        if self._last_status == STATE_ALARM_DISARMED:
            return "D"
        elif self._last_status == STATE_ALARM_ARMED_AWAY:
            return "T"
        elif self._last_status == STATE_ALARM_ARMED_NIGHT:
            return "Q"
        elif self._last_status == STATE_ALARM_ARMED_HOME:
            return "P"
        elif self._last_status == STATE_ALARM_ARMED_CUSTOM_BYPASS:
            return "E"
        else:
            return "D"

    def update_status_alarm(self, status: CheckAlarmStatus = None):
        """Update alarm status, from last alarm setting register or EST."""
        if status is not None and hasattr(status, "message"):
            self._message = status.message
            self._attr_extra_state_attributes["message"] = status.message
            self._attr_extra_state_attributes[
                "response_data"
            ] = status.protomResponseData
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
            elif (
                status.protomResponse == "E"  # PERI
                or status.protomResponse == "B"  # PERI + ARMED_HOME
                or status.protomResponse == "C"  # PERI + ARMED_NIGHT
                or status.protomResponse == "A"  # PERI + ARMED_AWAY
            ):
                self._state = STATE_ALARM_ARMED_CUSTOM_BYPASS

    async def async_update(self):
        """Update the status of the alarm based on the configuration."""
        alarm_status: CheckAlarmStatus = await self.client.update_overview(
            self.installation
        )
        self.update_status_alarm(alarm_status)

    async def async_alarm_disarm(self, code=None):
        """Send disarm command."""
        if (
            self.client.config.get(CONF_CODE, "") == ""
            or self.client.config.get(CONF_CODE, "") == code
        ):
            self.__force_state(STATE_ALARM_DISARMING)
            await self.set_arm_state("DARM1")

    async def async_alarm_arm_home(self, code=None):
        """Send arm home command."""
        self.__force_state(STATE_ALARM_ARMING)
        await self.set_arm_state("ARMDAY1")

    async def async_alarm_arm_away(self, code=None):
        """Send arm away command."""
        self.__force_state(STATE_ALARM_ARMING)
        await self.set_arm_state("ARM1")

    async def async_alarm_arm_night(self, code=None):
        """Send arm home command."""
        self.__force_state(STATE_ALARM_ARMING)
        await self.set_arm_state("ARMNIGHT1")

    async def async_alarm_arm_custom_bypass(self, code=None):
        """Send arm perimeter command."""
        self.__force_state(STATE_ALARM_ARMING)
        await self.set_arm_state("PERI1")

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
