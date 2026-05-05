"""Support for Securitas Direct (AKA Verisure EU) alarm control panels."""

import datetime
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
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from . import (
    CONF_CODE_ARM_REQUIRED,
    CONF_FORCE_ARM_NOTIFICATIONS,
    CONF_NOTIFY_GROUP,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SecuritasDirectDevice,
    SecuritasHub,
    _notify,
)
from .coordinators import AlarmCoordinator, AlarmStatusData
from .entity import securitas_device_info
from .notification_translations import get_notification_strings
from .securitas_direct_new_api import (
    ArmingExceptionError,
    Installation,
    OperationStatus,
    PROTO_DISARMED,
    PROTO_TO_STATE,
    SecuritasDirectError,
    SecuritasState,
    STATE_TO_COMMAND,
)
from .securitas_direct_new_api.command_resolver import (
    AlarmState,
    CommandResolver,
    CommandStep,
    InteriorMode,
    PerimeterMode,
    PROTO_TO_ALARM_STATE,
    SECURITAS_STATE_TO_ALARM_STATE,
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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct based on config_entry.

    No API calls are made here.  Entities start with unknown state;
    the coordinator drives periodic updates.
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    client: SecuritasHub = entry_data["hub"]
    coordinator: AlarmCoordinator = entry_data["alarm_coordinator"]
    alarms = []
    securitas_devices: list[SecuritasDirectDevice] = entry_data["devices"]
    for devices in securitas_devices:
        alarms.append(
            CombinedSecuritasAlarmPanel(
                devices.installation,
                client=client,
                hass=hass,
                coordinator=coordinator,
            )
        )
    async_add_entities(alarms, False)
    hass.data[DOMAIN]["alarm_entities"] = {a.installation.number: a for a in alarms}

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


class BaseSecuritasAlarmPanel(  # type: ignore[override]
    CoordinatorEntity[AlarmCoordinator], alarm.AlarmControlPanelEntity
):
    """Representation of a Securitas alarm status."""

    _attr_has_entity_name = False

    def __init__(
        self,
        installation: Installation,
        client: SecuritasHub,
        hass: HomeAssistant,
        coordinator: AlarmCoordinator,
    ) -> None:
        """Initialize the Securitas alarm panel."""
        super().__init__(coordinator)
        self._installation = installation
        self._client = client
        self._attr_device_info: DeviceInfo = (  # type: ignore[override]
            securitas_device_info(installation)
        )
        self._state: str | None = None
        self._last_state: str | None = None
        self._device: str = installation.address
        self._attr_name = installation.alias
        self._attr_unique_id: str | None = f"v4_securitas_direct.{installation.number}"
        self._time: datetime.datetime = datetime.datetime.now()
        self._message: str = ""
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self.hass: HomeAssistant = hass
        self._has_peri = coordinator.has_peri
        self._has_annex = coordinator.has_annex
        self._last_proto_code: str | None = None
        self._resolver = CommandResolver(
            has_peri=self._has_peri,
            has_annex=self._has_annex,
        )

        # Build outgoing map: HA state -> API command string
        # Build incoming map: protomResponse code -> HA state
        # Build securitas state map: HA state -> SecuritasState (for resolver)
        self._command_map: dict[str, str] = {}
        self._status_map: dict[str, str] = {}
        self._securitas_state_map: dict[str, SecuritasState] = {}

        for ha_state, conf_key in HA_STATE_TO_CONF_KEY.items():
            sec_state_str = self._client.config.get(conf_key)
            if not sec_state_str:
                continue
            sec_state = SecuritasState(sec_state_str)
            if sec_state == SecuritasState.NOT_USED:
                continue
            self._command_map[ha_state] = STATE_TO_COMMAND[sec_state]
            self._securitas_state_map[ha_state] = sec_state
            for code, proto_state in PROTO_TO_STATE.items():
                if proto_state == sec_state and code not in self._status_map:
                    self._status_map[code] = ha_state
                    break
        scan_seconds = client.config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        # _update_interval is also used as the retention window for force-arm
        # context, so keep it at DEFAULT_SCAN_INTERVAL when polling is off.
        self._update_interval: timedelta = timedelta(
            seconds=scan_seconds if scan_seconds > 0 else DEFAULT_SCAN_INTERVAL
        )
        self._operation_in_progress: bool = False
        self._operation_epoch: int = 0
        self._code: str | None = client.config.get(CONF_CODE, None)
        self._attr_code_format: CodeFormat | None = None
        if self._code:
            self._attr_code_format = (
                CodeFormat.NUMBER if self._code.isdigit() else CodeFormat.TEXT
            )
        self._attr_code_arm_required: bool = (
            client.config.get(CONF_CODE_ARM_REQUIRED, False) if self._code else False
        )

        self._last_arm_result: OperationStatus | None = None

        # Force-arm context: stored when arming fails due to non-blocking
        # exceptions (e.g. open window).  Consumed on the next arm attempt to
        # override the exception.  Cleared on status refresh.
        self._force_context: dict[str, Any] | None = None
        self._mobile_action_unsub = None
        self._arming_event_unsub = None

    # -- Properties formerly from SecuritasEntity --------------------------

    @property
    def installation(self) -> Installation:
        """Return the installation."""
        return self._installation

    @property
    def client(self) -> SecuritasHub:
        """Return the client hub."""
        return self._client

    def _force_state(self, state: AlarmControlPanelState) -> None:
        """Force entity state and schedule HA update."""
        self._last_state = self._state
        self._state = state
        if self.hass is not None:
            self.async_schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register event listeners when added to HA."""
        await super().async_added_to_hass()
        if self._notifications_enabled:
            self._register_arming_exception_handler()
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
            self.hass.async_create_task(self.async_force_arm_cancel())

    async def async_will_remove_from_hass(self) -> None:
        """Unregister event listeners when removed from HA."""
        if self._arming_event_unsub:
            self._arming_event_unsub()
        if self._mobile_action_unsub:
            self._mobile_action_unsub()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        if self._operation_in_progress:
            return  # Skip stale updates during arm/disarm
        self._clear_force_context()
        if self.coordinator.data is not None:
            self._update_from_coordinator(self.coordinator.data)
        self.async_write_ha_state()

    def _update_from_coordinator(self, data: AlarmStatusData) -> None:
        """Update internal state from coordinator data."""
        status = data.status
        if not status.status:
            return
        # status.status is the proto code like "D", "T", etc.
        proto_code = status.status
        # Only update _last_proto_code when it is a known proto code
        if proto_code == PROTO_DISARMED or proto_code in PROTO_TO_STATE:
            self._last_proto_code = proto_code
        if proto_code == PROTO_DISARMED:
            self._state = AlarmControlPanelState.DISARMED
        elif proto_code in self._status_map:
            self._state = self._status_map[proto_code]
        else:
            self._state = AlarmControlPanelState.ARMED_CUSTOM_BYPASS
            _LOGGER.info(
                "Unmapped alarm status code '%s' from Securitas. "
                "Check your Alarm State Mappings in the integration options",
                proto_code,
            )

    def update_status_alarm(self, status: OperationStatus | None = None) -> None:
        """Update alarm status, from last alarm setting register or EST."""
        if status is not None and hasattr(status, "message"):
            self._message = status.message
            self._attr_extra_state_attributes["message"] = status.message
            self._attr_extra_state_attributes["response_data"] = (
                status.protom_response_data
            )

            if not status.protom_response:
                _LOGGER.debug(
                    "[%s] Received empty protomResponse"
                    " (operation_status: %s, message: %s, status: %s,"
                    " protomResponseData: %s), ignoring",
                    self.entity_id,
                    status.operation_status,
                    status.message,
                    status.status,
                    status.protom_response_data,
                )
                return
            # Only update _last_proto_code when protomResponse is a known proto
            # code.  Periodic polling uses xSStatus which returns values like
            # "ARMED_TOTAL" instead of proto codes; those must not overwrite
            # the last proto code or the resolver's state-based command
            # selection will break.
            if (
                status.protom_response == PROTO_DISARMED
                or status.protom_response in PROTO_TO_ALARM_STATE
            ):
                self._last_proto_code = status.protom_response
            if status.protom_response == PROTO_DISARMED:
                self._state = AlarmControlPanelState.DISARMED
            elif status.protom_response in self._status_map:
                self._state = self._status_map[status.protom_response]
            else:
                self._state = AlarmControlPanelState.ARMED_CUSTOM_BYPASS
                _LOGGER.info(
                    "Unmapped alarm status code '%s' from Securitas. "
                    "Check your Alarm State Mappings in the integration options",
                    status.protom_response,
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

    def _build_operation_status(self, result: OperationStatus) -> OperationStatus:
        """Build OperationStatus from an arm/disarm result."""
        return OperationStatus(
            operation_status=getattr(result, "operation_status", ""),
            message=getattr(result, "message", ""),
            protom_response=result.protom_response,
        )

    def _handle_arm_disarm_error(
        self, err: SecuritasDirectError, translation_key: str
    ) -> None:
        """Handle errors from arm or disarm operations."""
        if getattr(err, "http_status", None) == 403:
            self._set_waf_blocked(True)
        else:
            _notify(
                self.hass,
                f"{translation_key}_{self.installation.number}",
                translation_key,
                {"error": err.message},
            )

    async def _async_arm(
        self, state: AlarmControlPanelState, code: str | None = None
    ) -> None:
        """Arm the alarm in the specified mode."""
        if self._check_code_for_arm_if_required(code):
            self._force_state(AlarmControlPanelState.ARMING)
            await self.set_arm_state(state)

    async def _execute_transition(
        self,
        target: AlarmState,
        **force_params: str,
    ) -> OperationStatus:
        """Execute a state transition, retrying once if state was stale.

        After executing the resolved command sequence, checks whether the
        panel's actual state matches the target.  If not (e.g. because
        ``_last_proto_code`` was stale), updates the proto code from the
        real response and retries with the corrected current state.
        """
        result: OperationStatus | None = None

        for attempt in range(2):
            current = PROTO_TO_ALARM_STATE.get(
                self._last_proto_code or "D",
                AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF),
            )
            steps = self._resolver.resolve(current, target)

            if not steps:
                # Resolver says we're already in the target state.
                return OperationStatus(protom_response=self._last_proto_code or "D")

            for step in steps:
                result = await self._execute_step(step, **force_params)

            assert result is not None

            # Check whether we actually reached the target state.
            actual_proto = result.protom_response
            if actual_proto and actual_proto in PROTO_TO_ALARM_STATE:
                actual_state = PROTO_TO_ALARM_STATE[actual_proto]
                if actual_state == target:
                    return result

                if attempt == 0:
                    _LOGGER.warning(
                        "State mismatch: expected %s, got %s (proto %s). "
                        "Retrying with corrected state.",
                        target,
                        actual_state,
                        actual_proto,
                    )
                    self._last_proto_code = actual_proto
                    continue

            # No proto code to compare, or second attempt — accept as-is.
            return result

        assert result is not None
        return result

    async def _execute_step(
        self,
        step: CommandStep,
        **force_params: str,
    ) -> OperationStatus:
        """Execute a single command step, trying alternatives on failure."""
        last_err: SecuritasDirectError | None = None

        for command in step.commands:
            if command in self._resolver.unsupported:
                continue

            try:
                _LOGGER.info("Sending command: %s", command)
                if "+" in command:
                    # Multi-step: split and execute sequentially
                    sub_commands = command.split("+")
                    result: OperationStatus | None = None
                    for sub_cmd in sub_commands:
                        _LOGGER.info("Sending sub-command: %s", sub_cmd)
                        result = await self._send_single_command(
                            sub_cmd, **force_params
                        )
                        self._last_arm_result = result
                    assert result is not None
                    return result
                result = await self._send_single_command(command, **force_params)
                self._last_arm_result = result
                return result
            except ArmingExceptionError:
                raise  # Arming exceptions need special handling upstream
            except SecuritasDirectError as err:
                if err.http_status == 403:
                    _notify(
                        self.hass,
                        f"rate_limited_{self.installation.number}",
                        "rate_limited",
                    )
                    raise
                if err.http_status == 409:
                    raise  # Server busy — don't try alternatives
                if err.http_status is not None:
                    # GraphQL validation error (e.g. BAD_USER_INPUT) —
                    # command not in panel's enum, mark as unsupported
                    _LOGGER.info(
                        "Command %s not supported by panel (status %s),"
                        " trying next alternative: %s",
                        command,
                        err.http_status,
                        err.log_detail(),
                    )
                    self._resolver.mark_unsupported(command)
                else:
                    # Panel-level error (e.g. TECHNICAL_ERROR after polling) —
                    # panel communication failure, not a command issue.
                    # Don't try alternatives (they'll likely also fail).
                    raise
                last_err = err

        if last_err and last_err.http_status == 400:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unsupported_alarm_mode",
            ) from last_err
        if last_err:
            raise last_err
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="no_supported_command",
        )

    async def _send_single_command(
        self,
        command: str,
        **force_params: str,
    ) -> OperationStatus:
        """Send a single arm or disarm command to the API."""
        if command.startswith("D"):
            return await self.client.disarm_alarm(self.installation, command)
        return await self.client.arm_alarm(self.installation, command, **force_params)

    def _set_refresh_failed(self, failed: bool) -> None:
        """Track whether the last manual refresh timed out."""
        if failed:
            self._attr_extra_state_attributes["refresh_failed"] = True
        else:
            self._attr_extra_state_attributes.pop("refresh_failed", None)

    def _set_waf_blocked(self, blocked: bool) -> None:
        """Track WAF rate-limit state for the alarm card."""
        if blocked:
            self._attr_extra_state_attributes["waf_blocked"] = True
        else:
            if self._attr_extra_state_attributes.pop("waf_blocked", None):
                # Dismiss the rate-limited persistent notification — must match
                # the ID created by the `rate_limited` _notify call.
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        domain="persistent_notification",
                        service="dismiss",
                        service_data={
                            "notification_id": (
                                f"{DOMAIN}.rate_limited_{self.installation.number}"
                            ),
                        },
                    )
                )

    def _resolve_target_state(self, ha_state: str) -> AlarmState:
        """Override in each subclass: map an HA state name to a target AlarmState."""
        raise NotImplementedError

    def _extract_state(self, joint_state: AlarmState) -> AlarmControlPanelState | None:
        """Override in each subclass: pick the HA state to display for this axis."""
        raise NotImplementedError

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        if not self._check_code(code):
            return
        self._force_state(AlarmControlPanelState.DISARMING)
        self._operation_in_progress = True
        self._operation_epoch += 1
        try:
            target = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
            result = await self._execute_transition(target)
            self._set_waf_blocked(False)
            self.update_status_alarm(self._build_operation_status(result))
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except SecuritasDirectError as err:
            self._state = self._last_state
            _LOGGER.error(
                "Disarm failed for %s: %s", self.installation.number, err.log_detail()
            )
            self._handle_arm_disarm_error(err, "disarm_failed")
            self.async_write_ha_state()
        except HomeAssistantError:
            self._state = self._last_state
            self.async_write_ha_state()
            raise
        finally:
            self._operation_in_progress = False

    async def set_arm_state(
        self,
        mode: str,
        *,
        force_arming_remote_id: str | None = None,
        suid: str | None = None,
    ) -> None:
        """Set the arm state using the command resolver."""
        self._operation_in_progress = True
        self._operation_epoch += 1
        self._last_arm_result = OperationStatus()

        force_params: dict[str, str] = {}
        if force_arming_remote_id:
            force_params["force_arming_remote_id"] = force_arming_remote_id
        if suid:
            force_params["suid"] = suid

        try:
            target = self._resolve_target_state(mode)
            result = await self._execute_transition(target, **force_params)
            self._set_waf_blocked(False)
            self.update_status_alarm(self._build_operation_status(result))
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ArmingExceptionError as exc:
            self._set_force_context(exc, mode)
            self._state = self._last_state
            self._fire_arming_exception_event(exc, mode)
            self.async_write_ha_state()
        except SecuritasDirectError as err:
            if self._last_arm_result.protom_response:
                self.update_status_alarm(
                    self._build_operation_status(self._last_arm_result)
                )
            else:
                self._state = self._last_state
            _LOGGER.error(
                "Arm failed for %s: %s", self.installation.number, err.log_detail()
            )
            self._handle_arm_disarm_error(err, "arm_failed")
            self.async_write_ha_state()
        except HomeAssistantError:
            self._state = self._last_state
            self.async_write_ha_state()
            raise
        finally:
            self._operation_in_progress = False

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

    def _fire_arming_exception_event(
        self, exc: ArmingExceptionError, mode: str
    ) -> None:
        """Fire securitas_arming_exception event on the HA event bus."""
        zones = [e.get("alias", "unknown") for e in exc.exceptions]
        self.hass.bus.async_fire(
            "securitas_arming_exception",
            {
                "entity_id": self.entity_id,
                "mode": mode,
                "zones": zones,
                "details": {
                    "installation": self.installation.number,
                    "exceptions": exc.exceptions,
                },
            },
        )

    _FORCE_ARM_TTL = datetime.timedelta(seconds=180)

    def _clear_force_context(self, force: bool = False) -> None:
        """Clear stored force-arm context and related attributes.

        When called from coordinator updates (force=False), only clears if
        the context has aged past _FORCE_ARM_TTL (180s).  On expiry, the
        notification is updated to inform the user the alarm was not armed.
        """
        if not force and self._force_context is not None:
            age = datetime.datetime.now() - self._force_context["created_at"]
            if age < self._FORCE_ARM_TTL:
                return
            # Expired — update notification to inform user
            if self._notifications_enabled:
                self._notify_force_arm_expired()
        self._force_context = None
        self._attr_extra_state_attributes.pop("arm_exceptions", None)
        self._attr_extra_state_attributes.pop("force_arm_available", None)

    def _notify_force_arm_expired(self) -> None:
        """Update the persistent notification to indicate force-arm expired."""
        _notify(
            self.hass,
            f"arming_exception_{self.installation.number}",
            "force_arm_expired",
        )

    @property
    def _arming_exception_notification_id(self) -> str:
        """Return a per-installation persistent-notification ID."""
        return f"{DOMAIN}.arming_exception_{self.installation.number}"

    @property
    def _notifications_enabled(self) -> bool:
        """Return True if the built-in force-arm notification handler is active."""
        return self._client.config.get(CONF_FORCE_ARM_NOTIFICATIONS, True)

    def _register_arming_exception_handler(self) -> None:
        """Register event listener for built-in arming exception notifications."""

        @callback
        def _handle_arming_exception_event(event: Event) -> None:
            """Handle securitas_arming_exception event for this entity."""
            if event.data.get("entity_id") != self.entity_id:
                return
            self._notify_arm_exceptions_from_event(event)

        self._arming_event_unsub = self.hass.bus.async_listen(
            "securitas_arming_exception",
            _handle_arming_exception_event,
        )

    def _notify_arm_exceptions_from_event(self, event: Event) -> None:
        """Send notifications about arming exceptions from event data."""
        self.hass.async_create_task(self._async_notify_arm_exceptions(event))

    async def _async_notify_arm_exceptions(self, event: Event) -> None:
        """Send translated persistent + mobile notifications for an arming exception."""
        zones = event.data.get("zones", [])
        if zones:
            sensor_list = "\n".join(f"- {z}" for z in zones)
            short_details = ", ".join(zones)
        else:
            sensor_list = "- (unknown sensor)"
            short_details = "open sensor"

        entry = get_notification_strings(self.hass, "arm_blocked_open_sensors")
        title = entry.get("title", "")
        persistent_message = entry.get("message", "").replace(
            "{sensor_list}", sensor_list
        )
        mobile_message = entry.get("mobile_message", "").replace(
            "{sensor_list}", short_details
        )
        force_arm_label = entry.get("force_arm_action", "")
        cancel_label = entry.get("cancel_action", "")

        await self.hass.services.async_call(
            domain="persistent_notification",
            service="create",
            service_data={
                "title": title,
                "message": persistent_message,
                "notification_id": self._arming_exception_notification_id,
            },
        )

        notify_group = self.client.config.get(CONF_NOTIFY_GROUP)
        if notify_group:
            await self.hass.services.async_call(
                domain="notify",
                service=notify_group,
                service_data={
                    "title": title,
                    "message": mobile_message,
                    "data": {
                        "tag": self._arming_exception_notification_id,
                        "actions": [
                            {
                                "action": (
                                    f"SECURITAS_FORCE_ARM_{self.installation.number}"
                                ),
                                "title": force_arm_label,
                            },
                            {
                                "action": (
                                    "SECURITAS_CANCEL_FORCE_ARM"
                                    f"_{self.installation.number}"
                                ),
                                "title": cancel_label,
                            },
                        ],
                    },
                },
            )

    def _dismiss_arming_exception_notification(self) -> None:
        """Dismiss the persistent and mobile arming-exception notifications."""
        self.hass.async_create_task(
            self.hass.services.async_call(
                domain="persistent_notification",
                service="dismiss",
                service_data={
                    "notification_id": self._arming_exception_notification_id
                },
            )
        )
        # Clear mobile notification if notify group is configured
        notify_group = self.client.config.get(CONF_NOTIFY_GROUP)
        if notify_group:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    domain="notify",
                    service=notify_group,
                    service_data={
                        "message": "clear_notification",
                        "data": {
                            "tag": self._arming_exception_notification_id,
                        },
                    },
                )
            )

    async def async_force_arm_cancel(self) -> None:
        """Cancel a pending force-arm context.

        Called by the securitas.force_arm_cancel service. Clears the stored
        exception context and dismisses the arming-exception notification.
        """
        if self._force_context is None:
            _LOGGER.warning(
                "force_arm_cancel called for %s but no force context available",
                self.installation.number,
            )
            return
        _LOGGER.info("Force-arm cancelled by user")
        self._clear_force_context(force=True)
        if self._notifications_enabled:
            self._dismiss_arming_exception_notification()
        self.async_write_ha_state()

    async def async_force_arm(self) -> None:
        """Force-arm using stored exception context.

        Called by the securitas.force_arm service. Re-arms in the same mode
        that previously failed, passing the stored referenceId and suid to
        override non-blocking exceptions.
        """
        if self._force_context is None:
            _LOGGER.warning(
                "force_arm called for %s but no force context available",
                self.installation.number,
            )
            return
        mode = self._force_context["mode"]
        ref_id = self._force_context["reference_id"]
        suid = self._force_context["suid"]
        _LOGGER.info(
            "Force-arming: overriding previous exceptions %s",
            [e.get("alias") for e in self._force_context.get("exceptions", [])],
        )
        self._clear_force_context(force=True)
        if self._notifications_enabled:
            self._dismiss_arming_exception_notification()
        self._force_state(AlarmControlPanelState.ARMING)
        await self.set_arm_state(mode, force_arming_remote_id=ref_id, suid=suid)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""
        await self._async_arm(AlarmControlPanelState.ARMED_HOME, code)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""
        await self._async_arm(AlarmControlPanelState.ARMED_AWAY, code)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Send arm night command."""
        await self._async_arm(AlarmControlPanelState.ARMED_NIGHT, code)

    async def async_alarm_arm_custom_bypass(self, code: str | None = None) -> None:
        """Send arm perimeter command."""
        await self._async_arm(AlarmControlPanelState.ARMED_CUSTOM_BYPASS, code)

    async def async_alarm_arm_vacation(self, code: str | None = None) -> None:
        """Send arm vacation command."""
        await self._async_arm(AlarmControlPanelState.ARMED_VACATION, code)

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:  # type: ignore[override]
        """Return the state of the alarm."""
        if self._state is None:
            return None
        if isinstance(self._state, AlarmControlPanelState):
            return self._state
        # Fallback for any string state values
        try:
            return AlarmControlPanelState(self._state)
        except ValueError:
            return None

    @property
    def supported_features(self) -> AlarmControlPanelEntityFeature:  # type: ignore[override]
        """Return the list of supported features."""
        features = AlarmControlPanelEntityFeature(0)
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


class CombinedSecuritasAlarmPanel(BaseSecuritasAlarmPanel):
    """The household-intent panel — drives all three axes via mappings.

    Inherits all behavior from the base. Sub-panels (Interior, Perimeter,
    Annex) come in subsequent tasks.
    """

    def _resolve_target_state(self, ha_state: str) -> AlarmState:
        """Convert an HA alarm mode to an AlarmState using the securitas state map."""
        securitas_state = self._securitas_state_map.get(ha_state)
        if securitas_state is None:
            raise SecuritasDirectError(f"Unsupported alarm mode: {ha_state}")
        return SECURITAS_STATE_TO_ALARM_STATE[securitas_state]

    def _extract_state(self, joint_state: AlarmState) -> AlarmControlPanelState | None:
        """For the combined panel, map joint state back to HA via user mappings."""
        for ha_state, sec_state in self._securitas_state_map.items():
            if SECURITAS_STATE_TO_ALARM_STATE.get(sec_state) == joint_state:
                try:
                    return AlarmControlPanelState(ha_state)
                except ValueError:
                    return None
        return None


# Backwards-compat alias for tests and any external imports.
SecuritasAlarm = CombinedSecuritasAlarmPanel
