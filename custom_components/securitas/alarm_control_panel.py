"""Support for Securitas Direct (AKA Verisure EU) alarm control panels."""

import asyncio
import datetime
from datetime import timedelta
import logging
from typing import Any

import homeassistant.components.alarm_control_panel as alarm
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntityFeature,
    CodeFormat,
)
from homeassistant.components.alarm_control_panel.const import AlarmControlPanelState
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CODE, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from . import (
    CONF_INSTALLATION_KEY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SecuritasDirectDevice,
    SecuritasHub,
)
from .securitas_direct_new_api import (
    ArmStatus,
    CheckAlarmStatus,
    CommandType,
    DisarmStatus,
    Installation,
    SecDirAlarmState,
    SecuritasDirectError,
)

STD_STATE_MAP = {
    AlarmControlPanelState.DISARMED: SecDirAlarmState.TOTAL_DISARMED,
    AlarmControlPanelState.ARMED_AWAY: SecDirAlarmState.TOTAL_ARMED,
    AlarmControlPanelState.ARMED_NIGHT: SecDirAlarmState.NIGHT_ARMED,
    AlarmControlPanelState.ARMED_HOME: SecDirAlarmState.INTERIOR_PARTIAL,
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS: SecDirAlarmState.EXTERIOR_ARMED,
}
PERI_STATE_MAP = {
    AlarmControlPanelState.DISARMED: SecDirAlarmState.TOTAL_DISARMED,
    AlarmControlPanelState.ARMED_AWAY: SecDirAlarmState.TOTAL_ARMED,
    AlarmControlPanelState.ARMED_NIGHT: SecDirAlarmState.INTERIOR_PARTIAL_AND_PERI,
    AlarmControlPanelState.ARMED_HOME: SecDirAlarmState.INTERIOR_PARTIAL,
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS: SecDirAlarmState.EXTERIOR_ARMED,
}

STATE_MAP = {
    CommandType.STD: STD_STATE_MAP,
    CommandType.PERI: PERI_STATE_MAP,
}

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=20)


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
        client: SecuritasHub,
        hass: HomeAssistant,
    ) -> None:
        """Initialize the Securitas alarm panel."""
        self._state: str = AlarmControlPanelState.DISARMED
        self._last_status: str = AlarmControlPanelState.DISARMED
        self._changed_by: str = ""
        self._device: str = installation.address
        self.entity_id: str = f"securitas_direct.{installation.number}"
        self._attr_unique_id: str = f"securitas_direct.{installation.number}"
        self._time: datetime.datetime = datetime.datetime.now()
        self._message: str = ""
        self.installation: Installation = installation
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self.client: SecuritasHub = client
        self.state_map = STATE_MAP[self.client.command_type]
        self.hass: HomeAssistant = hass
        self._update_interval: timedelta = timedelta(
            seconds=client.config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        self._update_unsub = async_track_time_interval(
            hass, self.async_update_status, self._update_interval
        )

        self._attr_device_info: DeviceInfo = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer="Securitas Direct",
            model=installation.panel,
            name=installation.alias,
            hw_version=installation.type,
        )
        self.update_status_alarm(state)

    def __force_state(self, state: str) -> None:
        self._last_status = self._state
        self._state = state
        self.async_schedule_update_ha_state()

    def _notify_error(self, title: str, message: str) -> None:
        """Notify user with persistent notification."""
        self.hass.async_create_task(
            self.hass.services.async_call(
                domain="persistent_notification",
                service="create",
                service_data={
                    "title": title,
                    "message": message,
                    "notification_id": f"{DOMAIN}.{title.replace(' ', '_')}",
                },
            )
        )

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self.installation.alias

    @property
    def code_format(self) -> CodeFormat:
        """Return one or more digits/characters."""
        return CodeFormat.NUMBER

    @property
    def code_arm_required(self) -> bool:
        """Whether the code is required for arm actions."""
        return False

    @property
    def changed_by(self) -> str:
        """Return the last change triggered by."""
        return self._changed_by

    async def get_arm_state(self) -> CheckAlarmStatus:
        """Get alarm state."""
        reference_id: str = await self.client.session.check_alarm(self.installation)
        await asyncio.sleep(1)
        alarm_status: CheckAlarmStatus = await self.client.session.check_alarm_status(
            self.installation, reference_id
        )
        return alarm_status

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from Home Assistant."""
        if self._update_unsub:
            self._update_unsub()  # Unsubscribe from updates

    async def async_update(self) -> None:
        """Update the status of the alarm based on the configuration. This is called when HA reloads."""
        await self.async_update_status()

    async def async_update_status(self, now=None) -> None:
        """Update the status of the alarm."""
        alarm_status: CheckAlarmStatus = CheckAlarmStatus()
        try:
            alarm_status = await self.client.update_overview(self.installation)
        except SecuritasDirectError as err:
            _LOGGER.info(err.args)
            self._state = self._last_status  # mantener último estado conocido
        else:
            self.update_status_alarm(alarm_status)
            self.async_write_ha_state()

    def update_status_alarm(self, status: CheckAlarmStatus | None = None) -> None:
        """Update alarm status, from last alarm setting register or EST."""
        if status is not None and hasattr(status, "message"):
            self._message = status.message
            self._attr_extra_state_attributes["message"] = status.message
            self._attr_extra_state_attributes["response_data"] = (
                status.protomResponseData
            )
            # self._time = datetime.datetime.fromisoformat(status.protomResponseData)

            if status.protomResponse == "D":
                self._state = AlarmControlPanelState.DISARMED
            elif status.protomResponse == "T":
                self._state = AlarmControlPanelState.ARMED_AWAY
            elif status.protomResponse == "Q":
                self._state = AlarmControlPanelState.ARMED_NIGHT
            elif status.protomResponse == "P":
                self._state = AlarmControlPanelState.ARMED_HOME
            elif status.protomResponse in ("E", "B", "C", "A"):
                self._state = AlarmControlPanelState.ARMED_CUSTOM_BYPASS

    def check_code(self, code=None) -> bool:
        """Check that the code entered in the panel matches the code in the config."""

        result: bool = False

        if (
            self.client.config.get(CONF_CODE, "") == ""
            or str(self.client.config.get(CONF_CODE, "")) == str(code)
            or self.client.config.get(CONF_CODE, None) is None
        ):
            result = True
        else:
            _LOGGER.info("PIN doesn't match")

        return result

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        if self.check_code(code):
            self.__force_state(AlarmControlPanelState.DISARMING)
            disarm_status: DisarmStatus = DisarmStatus()
            try:
                disarm_status = await self.client.session.disarm_alarm(
                    self.installation
                )
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
            except SecuritasDirectError as err:
                _LOGGER.error("Error disarming alarm: %s", err)
                self._state = self._last_status
                self._notify_error("Error disarming", str(err))

    async def set_arm_state(self, mode: str) -> None:
        """Send set arm state command."""
        self.__force_state(AlarmControlPanelState.ARMING)
        try:
            arm_status: ArmStatus = await self.client.session.arm_alarm(
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
        except SecuritasDirectError as err:
            _LOGGER.error("Error arming alarm: %s", err)
            self._state = self._last_status
            self._notify_error("Error arming", str(err))

    async def async_alarm_arm_home(self, code: str | None = None):
        """Send arm home command."""
        if self.check_code(code):
            await self.set_arm_state(AlarmControlPanelState.ARMED_HOME)

    async def async_alarm_arm_away(self, code: str | None = None):
        """Send arm away command."""
        if self.check_code(code):
            await self.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

    async def async_alarm_arm_night(self, code: str | None = None):
        """Send arm night command."""
        if self.check_code(code):
            await self.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

    async def async_alarm_arm_custom_bypass(self, code: str | None = None):
        """Send arm perimeter command."""
        if self.check_code(code):
            await self.set_arm_state(AlarmControlPanelState.ARMED_CUSTOM_BYPASS)

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return the state of the alarm."""
        try:
            return getattr(AlarmControlPanelState, self._state.upper())
        except AttributeError:
            return None

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return (
            AlarmControlPanelEntityFeature.ARM_HOME
            | AlarmControlPanelEntityFeature.ARM_AWAY
            | AlarmControlPanelEntityFeature.ARM_NIGHT
            | AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS
        )
