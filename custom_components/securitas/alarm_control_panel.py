"""Support for Securitas Direct (AKA Verisure EU) alarm control panels."""

import asyncio
import datetime
from datetime import timedelta
import logging

import homeassistant.components.alarm_control_panel as alarm
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntityFeature,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_CODE,
    CONF_SCAN_INTERVAL,
    STATE_ALARM_ARMED_AWAY,
    STATE_ALARM_ARMED_CUSTOM_BYPASS,
    STATE_ALARM_ARMED_HOME,
    STATE_ALARM_ARMED_NIGHT,
    STATE_ALARM_ARMING,
    STATE_ALARM_DISARMED,
    STATE_ALARM_DISARMING,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from . import (
    CONF_ENABLE_CODE,
    CONF_INSTALLATION_KEY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SecuritasDirectDevice,
    SecuritasHub,
)
from .securitas_direct_new_api import (
    CheckAlarmStatus,
    CommandType,
    Installation,
    SecDirAlarmState,
    SecuritasDirectError,
)

STD_STATE_MAP = {
    STATE_ALARM_DISARMED: SecDirAlarmState.TOTAL_DISARMED,
    STATE_ALARM_ARMED_AWAY: SecDirAlarmState.TOTAL_ARMED,
    STATE_ALARM_ARMED_NIGHT: SecDirAlarmState.NIGHT_ARMED,
    STATE_ALARM_ARMED_HOME: SecDirAlarmState.INTERIOR_PARTIAL,
    STATE_ALARM_ARMED_CUSTOM_BYPASS: SecDirAlarmState.EXTERIOR_ARMED,
}
PERI_STATE_MAP = {
    STATE_ALARM_DISARMED: SecDirAlarmState.TOTAL_DISARMED,
    STATE_ALARM_ARMED_AWAY: SecDirAlarmState.TOTAL_ARMED,
    STATE_ALARM_ARMED_NIGHT: SecDirAlarmState.INTERIOR_PARTIAL_AND_PERI,
    STATE_ALARM_ARMED_HOME: SecDirAlarmState.INTERIOR_PARTIAL,
    STATE_ALARM_ARMED_CUSTOM_BYPASS: SecDirAlarmState.EXTERIOR_ARMED,
}

STATE_MAP = {
    CommandType.STD: STD_STATE_MAP,
    CommandType.PERI: PERI_STATE_MAP,
}

_LOGGER = logging.getLogger(__name__)
# SCAN_INTERVAL = timedelta(seconds=1200)  # FIXME: is this used?


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct based on config_entry."""
    client: SecuritasHub = hass.data[DOMAIN][SecuritasHub.__name__]
    alarms = []
    securitas_devices: list[SecuritasDirectDevice] = hass.data[DOMAIN].get(
        CONF_INSTALLATION_KEY
    )
    for devices in securitas_devices:
        current_state: CheckAlarmStatus = await client.update_overview(
            devices.installation
        )
        alarms.append(
            SecuritasAlarm(
                devices.installation,
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
        self._digits: int = digits  # FIXME: never used
        self._changed_by = None
        self._device = installation.address
        self._entity_id = f"securitas_direct.{installation.number}"
        self._attr_unique_id = f"securitas_direct.{installation.number}"
        self._time: datetime.datetime = datetime.datetime.now()
        self._message = ""
        self.installation = installation
        self._attr_extra_state_attributes = {}
        self.client: SecuritasHub = client
        self.state_map = STATE_MAP[self.client.command_type]
        self.hass: HomeAssistant = hass
        self._update_interval = timedelta(
            seconds=client.config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        self._update_unsub = async_track_time_interval(
            hass, self.async_update_status, self._update_interval
        )

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

    async def get_arm_state(self) -> CheckAlarmStatus:
        """Get alarm state."""
        reference_id: str = self.client.session.check_alarm(self.installation)
        await asyncio.sleep(1)
        alarm_status: CheckAlarmStatus = await self.client.session.check_alarm_status(
            self.installation, reference_id
        )
        return alarm_status

    async def async_will_remove_from_hass(self):
        """When entity will be removed from Home Assistant."""
        if self._update_unsub:
            self._update_unsub()  # Unsubscribe from updates

    async def async_update_status(self, now=None):
        """Update the status of the alarm."""
        try:
            alarm_status = await self.client.update_overview(self.installation)
        except SecuritasDirectError as err:
            _LOGGER.info(err.args)
        else:
            self.update_status_alarm(alarm_status)
            self.async_write_ha_state()

    def _notify_error(self, notification_id, title: str, message: str) -> None:
        """Notify user with persistent notification."""
        self.hass.async_create_task(
            self.hass.services.async_call(
                domain="persistent_notification",
                service="create",
                service_data={
                    "title": title,
                    "message": message,
                    "notification_id": f"{DOMAIN}.{notification_id}",
                },
            )
        )

    async def set_arm_state(self, mode, attempts=3) -> None:
        """Send set arm state command."""

        arm_status = await self.client.session.arm_alarm(
            self.installation, self.state_map[mode]
        )

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
        return CodeFormat.NUMBER

    @property
    def code_arm_required(self):
        """Whether the code is required for arm actions."""
        return False

    @property
    def changed_by(self):
        """Return the last change triggered by."""
        return self._changed_by

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
                self._state = STATE_ALARM_DISARMED
            elif status.protomResponse == "T":
                self._state = STATE_ALARM_ARMED_AWAY
            elif status.protomResponse == "Q":
                self._state = STATE_ALARM_ARMED_NIGHT
            elif status.protomResponse == "P":
                self._state = STATE_ALARM_ARMED_HOME
            elif status.protomResponse in ("E", "B", "C", "A"):
                self._state = STATE_ALARM_ARMED_CUSTOM_BYPASS

    async def async_update(self):
        """Update the status of the alarm based on the configuration."""
        alarm_status: CheckAlarmStatus = await self.client.update_overview(
            self.installation
        )
        self.update_status_alarm(alarm_status)

    def check_code(self, code=None) -> bool:
        """Check that the code entered in the panel matches the code in the config."""

        result: bool = False

        if (
            self.client.config.get(CONF_CODE, "") == ""
            or str(self.client.config.get(CONF_CODE, "")) == str(code)
            or self.client.config.get(CONF_CODE, None) is None
        ):
            result = True

        if not self.client.config_entry.data.get(CONF_ENABLE_CODE, True):
            result = True

        return result

    async def async_alarm_disarm(self, code=None):
        """Send disarm command."""
        if self.check_code(code):
            self.__force_state(STATE_ALARM_DISARMING)
            disarm_status = await self.client.session.disarm_alarm(self.installation)

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

    async def async_alarm_arm_home(self, code=None):
        """Send arm home command."""
        if self.check_code(code):
            self.__force_state(STATE_ALARM_ARMING)
            await self.set_arm_state(STATE_ALARM_ARMED_HOME)

    async def async_alarm_arm_away(self, code=None):
        """Send arm away command."""
        if self.check_code(code):
            self.__force_state(STATE_ALARM_ARMING)
            await self.set_arm_state(STATE_ALARM_ARMED_AWAY)

    async def async_alarm_arm_night(self, code=None):
        """Send arm home command."""
        if self.check_code(code):
            self.__force_state(STATE_ALARM_ARMING)
            await self.set_arm_state(STATE_ALARM_ARMED_NIGHT)

    async def async_alarm_arm_custom_bypass(self, code=None):
        """Send arm perimeter command."""
        if self.check_code(code):
            self.__force_state(STATE_ALARM_ARMING)
            await self.set_arm_state(STATE_ALARM_ARMED_CUSTOM_BYPASS)

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return (
            AlarmControlPanelEntityFeature.ARM_HOME
            | AlarmControlPanelEntityFeature.ARM_AWAY
            | AlarmControlPanelEntityFeature.ARM_NIGHT
            | AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS
        )
