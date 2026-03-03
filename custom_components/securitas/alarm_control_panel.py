"""Support for Securitas Direct (AKA Verisure EU) alarm control panels."""

import asyncio
import datetime
import re
from datetime import timedelta
import logging
from typing import Any

import homeassistant.components.alarm_control_panel as alarm
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntityFeature,  # type: ignore[attr-defined]
    CodeFormat,  # type: ignore[attr-defined]
)
from homeassistant.components.alarm_control_panel.const import AlarmControlPanelState
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CODE, CONF_SCAN_INTERVAL
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.exceptions import ServiceValidationError

from . import (
    CONF_CODE_ARM_REQUIRED,
    CONF_INSTALLATION_KEY,
    CONF_NOTIFY_GROUP,
    CONF_PERI_ALARM,
    DEFAULT_PERI_ALARM,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SecuritasDirectDevice,
    SecuritasHub,
)
from .securitas_direct_new_api import (
    ALARM_STATUS_POLL_DELAY,
    ArmingExceptionError,
    ArmStatus,
    CheckAlarmStatus,
    COMPOUND_COMMAND_STEPS,
    DisarmStatus,
    Installation,
    PERI_ARMED_PROTO_CODES,
    PROTO_DISARMED,
    PROTO_TO_STATE,
    SecuritasDirectError,
    SecuritasState,
    STATE_TO_COMMAND,
)

# Map HA alarm state names to config keys
HA_STATE_TO_CONF_KEY: dict[str, str] = {
    AlarmControlPanelState.ARMED_HOME: "map_home",
    AlarmControlPanelState.ARMED_AWAY: "map_away",
    AlarmControlPanelState.ARMED_NIGHT: "map_night",
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS: "map_custom",
    AlarmControlPanelState.ARMED_VACATION: "map_vacation",
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

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "force_arm",
        {},
        "async_force_arm",
    )
    platform.async_register_entity_service(
        "force_arm_cancel",
        {},
        "async_force_arm_cancel",
    )


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
        self._device: str = installation.address
        self.entity_id: str = f"securitas_direct.{installation.number}"
        self._attr_unique_id: str | None = f"securitas_direct.{installation.number}"
        self._time: datetime.datetime = datetime.datetime.now()
        self._message: str = ""
        self.installation: Installation = installation
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self.client: SecuritasHub = client
        self.hass: HomeAssistant = hass
        self._has_peri = self.client.config.get(CONF_PERI_ALARM, DEFAULT_PERI_ALARM)
        self._use_multi_step: bool = False
        self._last_proto_code: str | None = None

        # Build outgoing map: HA state -> API command string
        # Build incoming map: protomResponse code -> HA state
        self._command_map: dict[str, str] = {}
        self._status_map: dict[str, str] = {}

        for ha_state, conf_key in HA_STATE_TO_CONF_KEY.items():
            sec_state_str = self.client.config.get(conf_key)
            if not sec_state_str:
                continue
            sec_state = SecuritasState(sec_state_str)
            if sec_state == SecuritasState.NOT_USED:
                continue
            self._command_map[ha_state] = STATE_TO_COMMAND[sec_state]
            for code, proto_state in PROTO_TO_STATE.items():
                if proto_state == sec_state and code not in self._status_map:
                    self._status_map[code] = ha_state
                    break
        self._update_interval: timedelta = timedelta(
            seconds=client.config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        self._update_unsub = async_track_time_interval(
            hass, self.async_update_status, self._update_interval
        )
        self._operation_in_progress: bool = False
        self._code: str | None = client.config.get(CONF_CODE, None)
        self._attr_code_format: CodeFormat | None = None
        if self._code:
            self._attr_code_format = (
                CodeFormat.NUMBER if self._code.isdigit() else CodeFormat.TEXT
            )
        self._attr_code_arm_required: bool = (
            client.config.get(CONF_CODE_ARM_REQUIRED, False) if self._code else False
        )

        # Force-arm context: stored when arming fails due to non-blocking
        # exceptions (e.g. open window).  Consumed on the next arm attempt to
        # override the exception.  Cleared on status refresh.
        self._force_context: dict[str, Any] | None = None
        self._mobile_action_unsub = None

        self._attr_device_info: DeviceInfo | None = DeviceInfo(
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
        notification_id = re.sub(r"\W+", "_", title.lower()).strip("_")
        self.hass.async_create_task(
            self.hass.services.async_call(
                domain="persistent_notification",
                service="create",
                service_data={
                    "title": title,
                    "message": message,
                    "notification_id": f"{DOMAIN}.{notification_id}_{self.installation.number}",
                },
            )
        )

    @property
    def name(self) -> str:  # type: ignore[override]
        """Return the name of the device."""
        return self.installation.alias

    async def get_arm_state(self) -> CheckAlarmStatus:
        """Get alarm state."""
        reference_id: str = await self.client.session.check_alarm(self.installation)
        await asyncio.sleep(ALARM_STATUS_POLL_DELAY)
        alarm_status: CheckAlarmStatus = await self.client.session.check_alarm_status(
            self.installation, reference_id
        )
        return alarm_status

    async def async_added_to_hass(self) -> None:
        """Register mobile notification action listener when added to HA."""
        self._mobile_action_unsub = self.hass.bus.async_listen(
            "mobile_app_notification_action",
            self._handle_mobile_action,
        )

    @callback
    def _handle_mobile_action(self, event: Event) -> None:
        """Handle Force Arm / Cancel taps from mobile notification."""
        action = event.data.get("action")
        num = self.installation.number
        if action == f"SECURITAS_FORCE_ARM_{num}":
            self.hass.async_create_task(self.async_force_arm())
        elif action == f"SECURITAS_CANCEL_FORCE_ARM_{num}":
            self._clear_force_context(force=True)
            self.async_write_ha_state()
            self._dismiss_arming_exception_notification()

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from Home Assistant."""
        if self._update_unsub:
            self._update_unsub()
        if self._mobile_action_unsub:
            self._mobile_action_unsub()

    async def async_update(self) -> None:
        """Update the status of the alarm based on the configuration. This is called when HA reloads."""
        await self.async_update_status()

    async def async_update_status(self, now=None) -> None:
        """Update the status of the alarm."""
        if self._operation_in_progress:
            _LOGGER.debug("Skipping status poll - arm/disarm operation in progress")
            return
        self._clear_force_context()
        alarm_status: CheckAlarmStatus = CheckAlarmStatus()
        try:
            alarm_status = await self.client.update_overview(self.installation)
        except SecuritasDirectError as err:
            _LOGGER.warning(
                "Error updating alarm status: %s",
                err.args[0] if err.args else err,
            )
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

            if not status.protomResponse:
                _LOGGER.debug("Received empty protomResponse from Securitas, ignoring")
                return
            # Only update _last_proto_code when protomResponse is a known proto
            # code.  When check_alarm_panel is disabled, protomResponse may
            # contain non-proto values like "ARMED_TOTAL" from xSStatus; those
            # must not overwrite the last proto code or the perimeter-armed
            # detection in _send_disarm_command() will break.
            if (
                status.protomResponse == PROTO_DISARMED
                or status.protomResponse in PROTO_TO_STATE
            ):
                self._last_proto_code = status.protomResponse
            if status.protomResponse == PROTO_DISARMED:
                self._state = AlarmControlPanelState.DISARMED
            elif status.protomResponse in self._status_map:
                self._state = self._status_map[status.protomResponse]
            else:
                self._state = AlarmControlPanelState.ARMED_CUSTOM_BYPASS
                _LOGGER.info(
                    "Unmapped alarm status code '%s' from Securitas. "
                    "Check your Alarm State Mappings in the integration options",
                    status.protomResponse,
                )

    def _check_code_for_arm_if_required(self, code: str | None) -> bool:
        """Check the code only if arming requires a code and a PIN is configured."""
        if not self._code or not self.code_arm_required:
            return True
        return self._check_code(code)

    def _check_code(self, code: str | None) -> bool:
        """Check that the code entered in the panel matches the code in the config."""
        result: bool = not self._code or self._code == code
        if not result:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_pin_code",
                translation_placeholders={
                    "entity_id": self.entity_id,
                },
            )
        return result

    async def _send_disarm_command(self) -> DisarmStatus:
        """Send the appropriate disarm command based on current state.

        If perimeter is configured and currently armed, tries DARM1DARMPERI
        first.  If that fails (or the panel is known to need multi-step
        commands), falls back to DARM1 which disarms everything on panels
        that don't support compound commands.
        """
        if not self._has_peri or self._last_proto_code not in PERI_ARMED_PROTO_CODES:
            return await self.client.session.disarm_alarm(self.installation, "DARM1")

        if self._use_multi_step:
            return await self.client.session.disarm_alarm(self.installation, "DARM1")

        try:
            return await self.client.session.disarm_alarm(
                self.installation, "DARM1DARMPERI"
            )
        except SecuritasDirectError as err:
            if err.http_status == 409:
                raise
            self._use_multi_step = True
            _LOGGER.info(
                "Combined disarm (DARM1DARMPERI) not supported by panel, "
                "switching to simple disarm (DARM1) for this session"
            )
            return await self.client.session.disarm_alarm(self.installation, "DARM1")

    async def _send_arm_command(self, command: str, **kwargs: str) -> ArmStatus:
        """Send an arm command, auto-detecting multi-step requirement.

        For compound commands (e.g. ARMNIGHT1PERI1), tries as a single API
        call first.  If that fails, splits into sequential steps and
        remembers the decision for the rest of the session.

        During multi-step execution, ``_last_arm_result`` is updated after
        each successful step so the caller can inspect partial state if a
        later step fails.
        """
        self._last_arm_result = ArmStatus()

        if command not in COMPOUND_COMMAND_STEPS:
            result = await self.client.session.arm_alarm(
                self.installation, command, **kwargs
            )
            self._last_arm_result = result
            return result

        if not self._use_multi_step:
            try:
                result = await self.client.session.arm_alarm(
                    self.installation, command, **kwargs
                )
                self._last_arm_result = result
                return result
            except SecuritasDirectError as err:
                if err.http_status == 409:
                    raise
                self._use_multi_step = True
                _LOGGER.info(
                    "Compound arm command (%s) not supported by panel, "
                    "switching to multi-step for this session",
                    command,
                )

        # Multi-step: send each step sequentially.
        # Force params (forceArmingRemoteId / suid) are passed to every step
        # because we don't know which step produced the original exception —
        # both interior and perimeter sensors can trigger ArmingExceptionError.
        # The API ignores force params that don't match a prior exception.
        for step in COMPOUND_COMMAND_STEPS[command]:
            self._last_arm_result = await self.client.session.arm_alarm(
                self.installation, step, **kwargs
            )
        return self._last_arm_result

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        if self._check_code(code):
            self.__force_state(AlarmControlPanelState.DISARMING)
            disarm_status: DisarmStatus = DisarmStatus()
            try:
                self._operation_in_progress = True
                disarm_status = await self._send_disarm_command()
            except SecuritasDirectError as err:
                err_msg = str(err.args[0]) if err.args else str(err)
                self._notify_error("Securitas: Error disarming", err_msg)
                _LOGGER.error("Disarm failed: %s", err_msg)
                self._state = self._last_status
                self.async_write_ha_state()
                return
            finally:
                self._operation_in_progress = False

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
            self.async_write_ha_state()

    async def set_arm_state(
        self,
        mode: str,
        *,
        force_arming_remote_id: str | None = None,
        suid: str | None = None,
    ) -> None:
        """Send set arm state command.

        If the alarm is already in an armed state, disarm first before
        re-arming.  This is required because the Securitas API treats
        interior and perimeter as independent axes — e.g. sending ARMDAY1
        while the perimeter is armed leaves the perimeter armed, so
        transitioning from Partial+Perimeter to Partial would silently fail.

        When force_arming_remote_id and suid are provided (via the
        force_arm service), the arm request overrides non-blocking
        exceptions from a previous failed attempt.
        """
        command = self._command_map.get(mode)
        if command is None:
            _LOGGER.error("No command configured for mode %s", mode)
            return

        self._operation_in_progress = True
        try:
            force_params: dict[str, str] = {}
            if force_arming_remote_id is not None:
                force_params = {
                    "force_arming_remote_id": force_arming_remote_id,
                    "suid": suid or "",
                }

            # Disarm first if previously in a confirmed armed state.
            # Note: self._state is already ARMING (set by caller via
            # __force_state), so check _last_status for the actual prior state.
            if self._last_status in (
                AlarmControlPanelState.ARMED_HOME,
                AlarmControlPanelState.ARMED_AWAY,
                AlarmControlPanelState.ARMED_NIGHT,
                AlarmControlPanelState.ARMED_CUSTOM_BYPASS,
                AlarmControlPanelState.ARMED_VACATION,
            ):
                try:
                    await self._send_disarm_command()
                except SecuritasDirectError as err:
                    _LOGGER.warning(
                        "Failed to disarm before re-arming (last_status: %s, alarm "
                        "may already be disarmed), continuing with arm: %s",
                        self._last_status,
                        err.args[0] if err.args else err,
                    )
                else:
                    await asyncio.sleep(ALARM_STATUS_POLL_DELAY)

            try:
                arm_status = await self._send_arm_command(command, **force_params)
            except ArmingExceptionError as exc:
                self._set_force_context(exc, mode)
                self._state = self._last_status
                self.async_write_ha_state()
                self._notify_arm_exceptions(exc)
                return
            except SecuritasDirectError as err:
                err_msg = str(err.args[0]) if err.args else str(err)
                _LOGGER.error("Arm failed: %s", err_msg)
                if "does not exist" in err_msg:
                    body = (
                        "The alarm panel does not support the requested"
                        f" state (command {command})"
                    )
                else:
                    body = f"Error sending arm command ({command}): {err_msg}"
                self._notify_error("Securitas: Arming failed", body)
                partial = self._last_arm_result
                if partial.protomResponse:
                    # A prior step succeeded — reflect the partial state.
                    self.update_status_alarm(
                        CheckAlarmStatus(
                            partial.operation_status,
                            partial.message,
                            partial.status,
                            partial.InstallationNumer,
                            partial.protomResponse,
                            partial.protomResponseData,
                        )
                    )
                    self.async_write_ha_state()
                else:
                    self._state = self._last_status
                    self.async_write_ha_state()
                return
        finally:
            self._operation_in_progress = False

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
        self.async_write_ha_state()

    def _set_force_context(self, exc: ArmingExceptionError, mode: str) -> None:
        """Store force-arm context from an arming exception."""
        self._force_context = {
            "reference_id": exc.reference_id,
            "suid": exc.suid,
            "mode": mode,
            "exceptions": exc.exceptions,
            "created_at": datetime.datetime.now(),
        }
        self._attr_extra_state_attributes["arm_exceptions"] = [
            e.get("alias", "unknown") for e in exc.exceptions
        ]
        self._attr_extra_state_attributes["force_arm_available"] = True

    def _clear_force_context(self, force: bool = False) -> None:
        """Clear stored force-arm context and related attributes.

        When called from async_update_status (force=False), only clears if
        the context has aged past one scan interval.  HA triggers an immediate
        status refresh after every service call, so without this guard the
        context would be wiped before the user can re-arm.
        """
        if not force and self._force_context is not None:
            age = datetime.datetime.now() - self._force_context["created_at"]
            if age < self._update_interval:
                return
        self._force_context = None
        self._attr_extra_state_attributes.pop("arm_exceptions", None)
        self._attr_extra_state_attributes.pop("force_arm_available", None)

    @property
    def _arming_exception_notification_id(self) -> str:
        """Return a per-installation persistent-notification ID."""
        return f"{DOMAIN}.arming_exception_{self.installation.number}"

    def _notify_arm_exceptions(self, exc: ArmingExceptionError) -> None:
        """Send notifications about arming exceptions."""
        if exc.exceptions:
            sensor_list = "\n".join(
                f"- {e.get('alias', 'unknown')}" for e in exc.exceptions
            )
            short_details = ", ".join(e.get("alias", "unknown") for e in exc.exceptions)
        else:
            sensor_list = "- (unknown sensor)"
            short_details = "open sensor"

        title = "Securitas: Arm blocked — open sensor(s)"
        persistent_message = (
            f"Arming was blocked because the following sensor(s) are open:\n"
            f"{sensor_list}\n\n"
            f"To arm anyway, call the **securitas.force_arm** service, "
            f"or tap **Force Arm** on your mobile notification."
        )
        mobile_message = f"Arm blocked — open sensor(s): {short_details}. Arm anyway?"

        self.hass.async_create_task(
            self.hass.services.async_call(
                domain="persistent_notification",
                service="create",
                service_data={
                    "title": title,
                    "message": persistent_message,
                    "notification_id": self._arming_exception_notification_id,
                },
            )
        )

        # Notify configured group if set (Companion App with action buttons)
        notify_group = self.client.config.get(CONF_NOTIFY_GROUP)
        if notify_group:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    domain="notify",
                    service=notify_group,
                    service_data={
                        "title": title,
                        "message": mobile_message,
                        "data": {
                            "actions": [
                                {
                                    "action": f"SECURITAS_FORCE_ARM_{self.installation.number}",
                                    "title": "Force Arm",
                                },
                                {
                                    "action": f"SECURITAS_CANCEL_FORCE_ARM_{self.installation.number}",
                                    "title": "Cancel",
                                },
                            ],
                        },
                    },
                )
            )

    def _dismiss_arming_exception_notification(self) -> None:
        """Dismiss the persistent arming-exception notification."""
        self.hass.async_create_task(
            self.hass.services.async_call(
                domain="persistent_notification",
                service="dismiss",
                service_data={
                    "notification_id": self._arming_exception_notification_id
                },
            )
        )

    async def async_force_arm_cancel(self) -> None:
        """Cancel a pending force-arm context.

        Called by the securitas.force_arm_cancel service. Clears the stored
        exception context and dismisses the arming-exception notification.
        """
        if self._force_context is None:
            _LOGGER.warning("force_arm_cancel called but no force context available")
            return
        _LOGGER.info("Force-arm cancelled by user")
        self._clear_force_context(force=True)
        self._dismiss_arming_exception_notification()
        self.async_write_ha_state()

    async def async_force_arm(self) -> None:
        """Force-arm using stored exception context.

        Called by the securitas.force_arm service. Re-arms in the same mode
        that previously failed, passing the stored referenceId and suid to
        override non-blocking exceptions.
        """
        if self._force_context is None:
            _LOGGER.warning("force_arm called but no force context available")
            return
        mode = self._force_context["mode"]
        ref_id = self._force_context["reference_id"]
        suid = self._force_context["suid"]
        _LOGGER.info(
            "Force-arming: overriding previous exceptions %s",
            [e.get("alias") for e in self._force_context.get("exceptions", [])],
        )
        self._clear_force_context(force=True)
        self._dismiss_arming_exception_notification()
        self.__force_state(AlarmControlPanelState.ARMING)
        await self.set_arm_state(mode, force_arming_remote_id=ref_id, suid=suid)

    async def async_alarm_arm_home(self, code: str | None = None):
        """Send arm home command."""
        if self._check_code_for_arm_if_required(code):
            self.__force_state(AlarmControlPanelState.ARMING)
            await self.set_arm_state(AlarmControlPanelState.ARMED_HOME)

    async def async_alarm_arm_away(self, code: str | None = None):
        """Send arm away command."""
        if self._check_code_for_arm_if_required(code):
            self.__force_state(AlarmControlPanelState.ARMING)
            await self.set_arm_state(AlarmControlPanelState.ARMED_AWAY)

    async def async_alarm_arm_night(self, code: str | None = None):
        """Send arm night command."""
        if self._check_code_for_arm_if_required(code):
            self.__force_state(AlarmControlPanelState.ARMING)
            await self.set_arm_state(AlarmControlPanelState.ARMED_NIGHT)

    async def async_alarm_arm_custom_bypass(self, code: str | None = None):
        """Send arm perimeter command."""
        if self._check_code_for_arm_if_required(code):
            self.__force_state(AlarmControlPanelState.ARMING)
            await self.set_arm_state(AlarmControlPanelState.ARMED_CUSTOM_BYPASS)

    async def async_alarm_arm_vacation(self, code: str | None = None):
        """Send arm vacation command."""
        if self._check_code_for_arm_if_required(code):
            self.__force_state(AlarmControlPanelState.ARMING)
            await self.set_arm_state(AlarmControlPanelState.ARMED_VACATION)

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:  # type: ignore[override]
        """Return the state of the alarm."""
        try:
            return getattr(AlarmControlPanelState, self._state.upper())
        except AttributeError:
            return None

    @property
    def supported_features(self) -> int:  # type: ignore[override]
        """Return the list of supported features."""
        features = 0
        if AlarmControlPanelState.ARMED_HOME in self._command_map:
            features |= AlarmControlPanelEntityFeature.ARM_HOME
        if AlarmControlPanelState.ARMED_AWAY in self._command_map:
            features |= AlarmControlPanelEntityFeature.ARM_AWAY
        if AlarmControlPanelState.ARMED_NIGHT in self._command_map:
            features |= AlarmControlPanelEntityFeature.ARM_NIGHT
        if AlarmControlPanelState.ARMED_CUSTOM_BYPASS in self._command_map:
            features |= AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS
        if AlarmControlPanelState.ARMED_VACATION in self._command_map:
            features |= AlarmControlPanelEntityFeature.ARM_VACATION
        return features
