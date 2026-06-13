"""Base Verisure OWA alarm panel: coordinator integration, arm/disarm
flow, force-arm context, and arming-exception notifications.

Sub-panels (Combined, Interior, Perimeter, Annex) live in _panels.py and
inherit the bulk of their behaviour from BaseVerisureOwaAlarmPanel here.
"""

from __future__ import annotations

from collections.abc import Callable
import datetime
from datetime import timedelta
import logging
from typing import Any
import uuid

import homeassistant.components.alarm_control_panel as alarm
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntityFeature,  # type: ignore[attr-defined]
    CodeFormat,  # type: ignore[attr-defined]
)
from homeassistant.components.alarm_control_panel.const import AlarmControlPanelState
from homeassistant.const import CONF_CODE, CONF_SCAN_INTERVAL
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .. import (
    CONF_CODE_ARM_REQUIRED,
    CONF_FORCE_ARM_NOTIFICATIONS,
    CONF_NOTIFY_GROUP,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    VerisureHub,
    _async_notify,
    _notify,
)
from ..const import (
    CIRCUIT_ANNEX,
    CIRCUIT_INTERIOR,
    CIRCUIT_PERIMETER,
    CONF_OPERATION_POLL_TIMEOUT,
    CONF_UNSUPPORTED_COMMANDS,
    DEFAULT_OPERATION_POLL_TIMEOUT,
)
from ..coordinators import AlarmCoordinator, AlarmStatusData
from ..entity import VerisureEntity
from ..events import (
    ARMING_EXCEPTION_DISMISSED_EVENT_TYPE,
    ARMING_EXCEPTION_EVENT_TYPE,
    DISMISSAL_REASON_INTEGRATION_RELOAD,
    DISMISSAL_REASON_USER_ARM,
    DISMISSAL_REASON_USER_DISARM,
    FORCE_ARM_EXPIRED_EVENT_TYPE,
    DismissalReason,
    fire_event,
    inject_ha_event,
)
from ..notification_translations import get_notification_strings
from ..verisure_owa_api import (
    ArmingExceptionError,
    Installation,
    OperationStatus,
    PROTO_DISARMED,
    PROTO_TO_STATE,
    STATE_LABELS,
    STATE_TO_COMMAND,
    VerisureOwaError,
    VerisureOwaState,
    is_proto_letter,
)
from ..verisure_owa_api.exceptions import OperationTimeoutError
from ..verisure_owa_api.__version__ import __url__ as _PROJECT_URL
from ..verisure_owa_api.command_resolver import (
    ALARM_STATE_TO_PROTO,
    AlarmState,
    AnnexMode,
    CommandResolver,
    CommandStep,
    InteriorMode,
    PerimeterMode,
    PROTO_TO_ALARM_STATE,
)
from ..verisure_owa_api.models import ActivityCategory, ActivityException

# Map HA alarm state names to config keys
HA_STATE_TO_CONF_KEY: dict[str, str] = {
    AlarmControlPanelState.ARMED_HOME: "map_home",
    AlarmControlPanelState.ARMED_AWAY: "map_away",
    AlarmControlPanelState.ARMED_NIGHT: "map_night",
    AlarmControlPanelState.ARMED_CUSTOM_BYPASS: "map_custom",
    AlarmControlPanelState.ARMED_VACATION: "map_vacation",
}

_LOGGER = logging.getLogger(__name__)


def _read_unsupported_for_installation(
    config: dict[str, Any], installation_number: str
) -> list[str]:
    """Pull this installation's persisted unsupported-commands list.

    ``config[CONF_UNSUPPORTED_COMMANDS]`` may be in one of three shapes:

    - **Missing / empty** — return ``[]``.
    - **Dict** (current format, keyed by ``installation.number`` as str) —
      return that installation's slot, or ``[]`` if it has none.
    - **List** (v5.0.1-pre legacy format, a single flat list applied to
      every installation on the entry) — return the list verbatim. Each
      installation reading the legacy format sees the same rejections;
      they get re-keyed under their own slot by ``_persist_unsupported``
      on the next write.
    """
    raw = config.get(CONF_UNSUPPORTED_COMMANDS)
    if isinstance(raw, dict):
        return list(raw.get(installation_number, []))
    if isinstance(raw, list):
        return list(raw)
    return []


def build_partial_disarm_target(current: AlarmState, circuits: list[str]) -> AlarmState:
    """Build an AlarmState that disarms ``circuits`` and keeps the rest.

    Unknown circuit names are silently ignored — the caller validates
    against ``LOCK_CIRCUITS``.
    """
    return AlarmState(
        interior=(
            InteriorMode.OFF if CIRCUIT_INTERIOR in circuits else current.interior
        ),
        perimeter=(
            PerimeterMode.OFF if CIRCUIT_PERIMETER in circuits else current.perimeter
        ),
        annex=(AnnexMode.OFF if CIRCUIT_ANNEX in circuits else current.annex),
    )


class BaseVerisureOwaAlarmPanel(  # type: ignore[override]
    VerisureEntity,
    CoordinatorEntity[AlarmCoordinator],
    alarm.AlarmControlPanelEntity,
):
    """Representation of a Verisure alarm status."""

    _attr_has_entity_name = False
    # The combined Main panel exposes a user-editable mapping per HA alarm
    # state, so a panel-rejected command is a config issue — the rejection
    # notification points the user at the mappings UI. Sub-panels override
    # this to False (no mapping; the right action is to drop the feature).
    _is_mappable: bool = True

    def __init__(
        self,
        installation: Installation,
        client: VerisureHub,
        hass: HomeAssistant,
        coordinator: AlarmCoordinator,
    ) -> None:
        """Initialize the Verisure alarm panel."""
        CoordinatorEntity.__init__(self, coordinator)  # type: ignore[arg-type]
        VerisureEntity.__init__(self, installation, client)
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
        # Last proto code we warned about; dedupes the per-poll spam.
        self._last_unmapped_logged: str | None = None
        self._resolver = CommandResolver(
            has_peri=self._has_peri,
            unsupported=_read_unsupported_for_installation(
                self._client.config, installation.number
            ),
        )

        # Build outgoing map: HA state -> API command string
        # Build incoming map: protomResponse code -> HA state
        # Build state map: HA state -> VerisureOwaState (for resolver)
        self._command_map: dict[str, str] = {}
        self._status_map: dict[str, str] = {}
        self._securitas_state_map: dict[str, VerisureOwaState] = {}

        for ha_state, conf_key in HA_STATE_TO_CONF_KEY.items():
            sec_state_str = self._client.config.get(conf_key)
            if not sec_state_str:
                continue
            sec_state = VerisureOwaState(sec_state_str)
            if sec_state == VerisureOwaState.NOT_USED:
                continue
            # Annex-bearing targets reach the panel via the multi-step
            # CommandResolver (ARMANNEX1/DARMANNEX1 + interior/peri commands)
            # rather than the flat STATE_TO_COMMAND wire mapping. The map is
            # only consulted for supported_features membership, so an empty
            # placeholder for annex targets is enough.
            self._command_map[ha_state] = STATE_TO_COMMAND.get(sec_state, "")
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
        self._force_arm_expiry_unsub: Callable[[], None] | None = None
        self._mobile_action_unsub = None
        self._arming_event_unsub_new = None
        self._force_arm_expired_event_unsub = None
        self._arming_exception_dismissed_event_unsub = None
        self._last_handled_event_id: str | None = None

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
        """Handle Force Arm / Cancel taps from mobile notification.

        The action names retain the SECURITAS_ prefix for the v5 deprecation
        window: this integration both sends them (see _async_notify_arm_exceptions)
        and listens for them here, but a user could have a custom automation
        hooked to mobile_app_notification_action matching these strings.
        Renamed to VERISURE_OWA_FORCE_ARM_<num> in v6 with release-note
        guidance for affected users.
        """
        action = event.data.get("action")
        num = self.installation.number
        if action == f"SECURITAS_FORCE_ARM_{num}":
            self.hass.async_create_task(self.async_force_arm())
        elif action == f"SECURITAS_CANCEL_FORCE_ARM_{num}":
            self.hass.async_create_task(self.async_force_arm_cancel())

    async def async_will_remove_from_hass(self) -> None:
        """Unregister event listeners when removed from HA."""
        # Reload-path safety net: if context is still alive at teardown,
        # the new entity created post-reload would start fresh with no
        # context. Fire dismissed event so user automations see the loss.
        if self._force_context is not None:
            self._fire_arming_exception_dismissed_event(
                reason=DISMISSAL_REASON_INTEGRATION_RELOAD,
                new_mode=None,
            )
        # Cancel the expiry timer to avoid late callbacks on a torn-down entity.
        self._cancel_force_arm_expiry()
        if self._arming_event_unsub_new:
            self._arming_event_unsub_new()
        if self._force_arm_expired_event_unsub:
            self._force_arm_expired_event_unsub()
        if self._arming_exception_dismissed_event_unsub:
            self._arming_exception_dismissed_event_unsub()
        if self._mobile_action_unsub:
            self._mobile_action_unsub()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        if self._operation_in_progress:
            return  # Skip stale updates during arm/disarm
        if self.coordinator.data is not None:
            self._update_from_coordinator(self.coordinator.data)
        self.async_write_ha_state()

    def _update_from_coordinator(self, data: AlarmStatusData) -> None:
        """Update internal state from coordinator data."""
        # Refresh resolver capabilities — they may have been populated late
        # (e.g. transient API error at startup, retry succeeds on first refresh).
        self._resolver.update_capabilities(has_peri=self.coordinator.has_peri)
        status = data.status
        if not status.status:
            return
        # status.status is the proto code like "D", "T", etc.
        proto_code = status.status
        # Store any well-formed proto code (single uppercase letter), even ones
        # we don't yet model — this keeps _last_proto_code truthful so the next
        # arm/disarm refuses cleanly instead of acting on a stale cached state.
        if is_proto_letter(proto_code):
            self._last_proto_code = proto_code
        # A fresh authoritative status reconciles any provisional
        # (accepted-but-unconfirmed) arm/disarm: clear the flag and dismiss
        # the unconfirmed notification. (#508)
        if self._attr_extra_state_attributes.get("state_provisional"):
            self._set_state_provisional(False)
            self.hass.async_create_task(
                self.hass.services.async_call(
                    domain="persistent_notification",
                    service="dismiss",
                    service_data={
                        "notification_id": (
                            f"{DOMAIN}.operation_unconfirmed_"
                            f"{self.installation.number}"
                        ),
                    },
                )
            )
        if proto_code == PROTO_DISARMED:
            self._state = AlarmControlPanelState.DISARMED
            self._last_unmapped_logged = None
        elif proto_code in self._status_map:
            self._state = self._status_map[proto_code]
            self._last_unmapped_logged = None
        else:
            self._state = AlarmControlPanelState.ARMED_CUSTOM_BYPASS
            self._log_unmapped_proto_code(proto_code)

    def _log_unmapped_proto_code(self, proto_code: str) -> None:
        """Warn that the panel reported a state HA can't represent.

        Distinguishes two cases so the user (or a maintainer reading logs)
        knows whether to fix their config or file a bug:

        - Code is in PROTO_TO_STATE but no HA button maps to that state
          (the user just needs to bind a button in options).
        - Code isn't in PROTO_TO_STATE at all — the integration doesn't
          know this state, please report.

        Deduped per entity: we only re-log when the unmapped code changes,
        so a panel sitting in the unmapped state doesn't spam every poll.
        """
        if self._last_unmapped_logged == proto_code:
            return
        self._last_unmapped_logged = proto_code
        sec_state = PROTO_TO_STATE.get(proto_code)
        if sec_state is not None:
            label = STATE_LABELS.get(sec_state, sec_state.value)
            _LOGGER.warning(
                "[%s installation=%s] Unmapped alarm state: Verisure reports "
                "'%s' (proto code '%s'). None of the buttons on the main "
                "control panel are mapped to it. Map a button in Settings → "
                "Devices & Services → Verisure OWA → Configure → Alarm State "
                "Mappings, or HA will keep showing this as 'armed_custom_bypass'.",
                self.entity_id,
                self.installation.number,
                label,
                proto_code,
            )
        else:
            _LOGGER.warning(
                "[%s installation=%s] Unmapped alarm state: Verisure proto "
                "code '%s' is not recognised by this integration. Please "
                "report at %s.",
                self.entity_id,
                self.installation.number,
                proto_code,
                _PROJECT_URL,
            )

    def _store_operation_status_metadata(self, status: OperationStatus | None) -> bool:
        """Store message + response_data on this entity from an operation status.

        Returns True if ``status.protom_response`` is a non-empty string and the
        caller should derive ``_state`` from it.  Returns False to short-circuit
        (no status, no message attribute, or empty protom_response).

        Also updates ``_last_proto_code`` when protom_response has the proto-code
        shape (single uppercase letter).  Periodic polling uses xSStatus which
        returns values like "ARMED_TOTAL" instead of proto codes; those must not
        overwrite the last proto code or the resolver's state-based command
        selection will break.
        """
        if status is None or not hasattr(status, "message"):
            return False
        self._message = status.message
        self._attr_extra_state_attributes["message"] = status.message
        self._attr_extra_state_attributes["response_data"] = status.protom_response_date
        if not status.protom_response:
            _LOGGER.debug(
                "[%s] Received empty protomResponse"
                " (operation_status: %s, message: %s, status: %s,"
                " protomResponseDate: %s), ignoring",
                self.entity_id,
                status.operation_status,
                status.message,
                status.status,
                status.protom_response_date,
            )
            return False
        if is_proto_letter(status.protom_response):
            self._last_proto_code = status.protom_response
        return True

    def update_status_alarm(self, status: OperationStatus | None = None) -> None:
        """Update alarm status, from last alarm setting register or EST."""
        if not self._store_operation_status_metadata(status):
            return
        assert status is not None  # narrowed by _store_operation_status_metadata
        if status.protom_response == PROTO_DISARMED:
            self._state = AlarmControlPanelState.DISARMED
            self._last_unmapped_logged = None
        elif status.protom_response in self._status_map:
            self._state = self._status_map[status.protom_response]
            self._last_unmapped_logged = None
        else:
            self._state = AlarmControlPanelState.ARMED_CUSTOM_BYPASS
            self._log_unmapped_proto_code(status.protom_response)

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
        self, err: VerisureOwaError, translation_key: str
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
            await self._dismiss_pending_force_context_on_siblings(
                reason=DISMISSAL_REASON_USER_ARM,
                new_mode=state,
            )
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

        Refuses to act when the panel's current state is unknown (no poll
        seen yet, or a proto code we don't model).  Acting on an unknown
        current state would silently no-op the disarm path (issue #441) or
        send incorrect transitions on the arm path.
        """
        if self._last_proto_code is None:
            raise VerisureOwaError(
                "Alarm state not yet known. "
                "Please wait for the first status poll and try again."
            )
        if self._last_proto_code not in PROTO_TO_ALARM_STATE:
            raise VerisureOwaError(
                f"Alarm is in unknown state '{self._last_proto_code}'. "
                f"Please open an issue at {_PROJECT_URL}/issues "
                "including this state code."
            )

        result: OperationStatus | None = None

        for attempt in range(2):
            current = PROTO_TO_ALARM_STATE[self._last_proto_code]
            steps = self._resolver.resolve(current, target)

            if not steps:
                # Resolver says we're already in the target state.
                return OperationStatus(protom_response=self._last_proto_code)

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
        last_err: VerisureOwaError | None = None

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
            except VerisureOwaError as err:
                if err.http_status == 403:
                    _notify(
                        self.hass,
                        f"rate_limited_{self.installation.number}",
                        "rate_limited",
                    )
                    raise
                if err.http_status == 409:
                    raise  # Server busy — don't try alternatives
                if err.http_status in (400, 404):
                    # The Verisure OWA API uses two HTTP statuses for
                    # "this command is not in the panel's enum":
                    #   - 400 BAD_USER_INPUT — surfaced when the panel's
                    #     ArmCodeRequest / DisarmCodeRequest enum doesn't
                    #     include the requested code at all (the GraphQL
                    #     server validates the variable up front).
                    #   - 404 "Requested data not found" — surfaced by the
                    #     panel itself when it doesn't recognise the
                    #     compound disarm command (e.g. Spanish panels that
                    #     don't accept DARM1DARMPERI from night+perimeter).
                    # Both are permanent panel-side rejections of *this*
                    # specific command. Mark unsupported, persist, and try
                    # the next alternative in the step.
                    #
                    # We deliberately do NOT blacklist for other 4xx
                    # (401 auth-blip, 422 validation hiccup, 429 rate-limit,
                    # 451 legal-block, etc.) — those are transient or
                    # environmental and persisting them would permanently
                    # disable an arming mode the user actually has, just
                    # because the panel was briefly unreachable. Propagate
                    # the error so the caller sees the transient failure
                    # without polluting unsupported_commands.
                    _LOGGER.info(
                        "Command %s not supported by panel (status %s),"
                        " trying next alternative: %s",
                        command,
                        err.http_status,
                        err.log_detail(),
                    )
                    self._resolver.mark_unsupported(command)
                    self._persist_unsupported()
                else:
                    # Any other 4xx (transient auth, rate-limit, etc.) or
                    # 5xx server error — not a "command not valid" case.
                    # Don't blacklist; don't try alternatives (they'll
                    # likely also fail the same way).
                    raise
                last_err = err

        if last_err and last_err.http_status in (400, 404):
            # Sub-panels have no user-editable mapping — point the user at
            # the auto-disabled feature; mappable Main panel still points
            # them at the mappings UI.
            key = (
                "unsupported_alarm_mode"
                if self._is_mappable
                else "unsupported_alarm_mode_subpanel"
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=key,
                translation_placeholders={"tried": ", ".join(step.commands)},
            ) from last_err
        if last_err:
            raise last_err
        # All step.commands were already in resolver.unsupported (e.g. a
        # second click on a mode whose only command we rejected last time).
        # On sub-panels this normally shouldn't happen — the button should
        # already be hidden by supported_features — but if the UI still
        # offered it, surface the same "disabled on this sub-panel" message
        # rather than pointing at the (missing) mappings UI.
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=(
                "no_supported_command"
                if self._is_mappable
                else "unsupported_alarm_mode_subpanel"
            ),
            translation_placeholders={"tried": ", ".join(step.commands)},
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

    def _persist_unsupported(self) -> None:
        """Write the resolver's unsupported set to entry.data and refresh state.

        Persisting means the resolver starts pre-loaded on the next setup, so
        a sub-panel mode disabled by a 400 stays disabled across HA restarts.
        Writing to entry.data via async_update_entry also triggers the update
        listener; CONF_UNSUPPORTED_COMMANDS isn't options-managed so the
        listener no-ops there.

        Persisted shape is ``{<installation.number>: [<commands>...]}`` so
        a legacy entry that covers multiple installations (no
        ``CONF_INSTALLATION`` set, so ``_fetch_and_cache_installations``
        returns them all) doesn't cross-contaminate sibling panels: each
        panel reads only its own slot at setup, and persisting only
        rewrites its own slot. The legacy flat-list format is migrated
        on first write — the existing list is associated with THIS
        installation's slot, since the legacy resolver-init read it for
        this installation.

        The entity registry's cached ``supported_features`` is normally
        refreshed from inside ``_async_write_ha_state``, but empirically
        that path doesn't always propagate the change to the entity
        registry for sub-panels (the Main panel's registry does update —
        sub-panels' don't). Update the registry explicitly so the
        frontend's now-unreachable button drops out of the card.
        """
        entry = getattr(self._client, "config_entry", None)
        if entry is None:
            return
        installation_num = self._installation.number
        existing = entry.data.get(CONF_UNSUPPORTED_COMMANDS)
        if isinstance(existing, dict):
            current_map: dict[str, list[str]] = {
                k: list(v) for k, v in existing.items()
            }
        elif isinstance(existing, list):
            # Legacy flat-list format from v5.0.1-pre. The bare list was
            # applied to every installation's resolver on read; migrate
            # by attributing it to THIS installation's slot. Siblings that
            # also need it will repopulate their own slot the next time
            # they hit a rejection.
            current_map = {installation_num: list(existing)}
        else:
            current_map = {}
        new_list = sorted(self._resolver.unsupported)
        if current_map.get(installation_num) == new_list:
            return
        new_map = {**current_map, installation_num: new_list}
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_UNSUPPORTED_COMMANDS: new_map}
        )
        self._recompute_supported_features()
        self._force_registry_supported_features()
        self.async_write_ha_state()

    def _force_registry_supported_features(self) -> None:
        """Push the current ``supported_features`` value into the entity registry.

        HA's auto-update path inside ``_async_write_ha_state`` should do this,
        but for sub-panels it doesn't fire reliably — leaving the persisted
        registry value stale and the rejected button still rendering on the
        card. Updating the registry directly keeps the two in sync.
        """
        from homeassistant.helpers import entity_registry as er

        if not self.entity_id:
            return
        registry = er.async_get(self.hass)
        if registry.async_get(self.entity_id) is None:
            return
        registry.async_update_entity(
            self.entity_id,
            supported_features=int(self.supported_features),
        )

    def _recompute_supported_features(self) -> None:
        """Override in sub-panels to refresh ``_attr_supported_features`` from
        the resolver. No-op on the Combined Main panel where features are
        driven by the user's state mapping rather than panel capabilities.
        """

    async def async_manual_refresh(self) -> None:
        """Full alarm-status refresh via CheckAlarm + poll.

        Authoritative round-trip with the panel, not just a lightweight
        xSStatus read.  Backs both the `verisure_owa.refresh_alarm`
        entity service and the deprecated VerisureRefreshButton.
        """
        try:
            alarm_status = await self._client.refresh_alarm_status(self._installation)
            self._client.client.protom_response = alarm_status.protom_response
            _LOGGER.info(
                "Status of the Alarm via API: %s installation id: %s",
                alarm_status.protom_response,
                self._installation.number,
            )
            self._set_refresh_failed(False)
            self.async_write_ha_state()
            self.async_schedule_update_ha_state(force_refresh=True)
        except OperationTimeoutError as err:
            _LOGGER.warning("Refresh timed out for %s", self._installation.number)
            self._set_refresh_failed(True)
            self.async_write_ha_state()
            await inject_ha_event(
                self.hass,
                self._installation,
                category=ActivityCategory.COMMUNICATION_FAILED,
                alias=f"Refresh timed out: {err}",
                context=self._context,
            )
        except VerisureOwaError as err:
            _LOGGER.error(
                "Error refreshing alarm status for %s: %s",
                self._installation.number,
                err.log_detail(),
            )
            if getattr(err, "http_status", None) == 403:
                await _async_notify(
                    self.hass,
                    f"rate_limited_{self._installation.number}",
                    "rate_limited",
                )
                self._set_waf_blocked(True)
                self.async_write_ha_state()
            await inject_ha_event(
                self.hass,
                self._installation,
                category=ActivityCategory.COMMUNICATION_FAILED,
                alias=f"Refresh failed: {err}",
                context=self._context,
            )

    def _set_refresh_failed(self, failed: bool) -> None:
        """Track whether the last manual refresh timed out."""
        if failed:
            self._attr_extra_state_attributes["refresh_failed"] = True
        else:
            self._attr_extra_state_attributes.pop("refresh_failed", None)

    def _set_state_provisional(self, provisional: bool) -> None:
        """Flag the entity state as provisional (accepted-but-unconfirmed)."""
        if provisional:
            self._attr_extra_state_attributes["state_provisional"] = True
        else:
            self._attr_extra_state_attributes.pop("state_provisional", None)

    def _optimistic_status(self, target: AlarmState) -> OperationStatus:
        """Build an OperationStatus reflecting the *intended* target state.

        Used when a command was accepted (res: OK) but the confirmation poll
        timed out: we optimistically show the target (the fail-safe direction)
        and let the coordinator reconcile. Falls back to the last known proto
        code, then disarmed, if the target has no modelled proto letter.
        """
        proto = (
            ALARM_STATE_TO_PROTO.get(target)
            or self._last_proto_code
            or PROTO_DISARMED
        )
        return OperationStatus(protom_response=proto)

    def _notify_operation_unconfirmed(self, translation_key: str) -> None:
        """Raise the accepted-but-unconfirmed persistent notification."""
        timeout = self.client.config.get(
            CONF_OPERATION_POLL_TIMEOUT, DEFAULT_OPERATION_POLL_TIMEOUT
        )
        _notify(
            self.hass,
            f"operation_unconfirmed_{self.installation.number}",
            translation_key,
            {
                "installation": self.installation.alias,
                "timeout": str(int(timeout)),
            },
        )

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
        await self._dismiss_pending_force_context_on_siblings(
            reason=DISMISSAL_REASON_USER_DISARM,
            new_mode="disarmed",
        )
        # Capture the calling user's context up-front — HA expires
        # `self._context` ~1 s after async_set_context, and the disarm
        # transition + state writes below take longer than that.
        user_context = self._context
        self._force_state(AlarmControlPanelState.DISARMING)
        self._operation_in_progress = True
        self._operation_epoch += 1
        try:
            target = self._resolve_target_state("disarmed")
            result = await self._execute_transition(target)
            self._set_waf_blocked(False)
            self.update_status_alarm(result)
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
            await inject_ha_event(
                self.hass,
                self._installation,
                category=ActivityCategory.DISARMED,
                alias="Disarmed",
                context=user_context,
            )
        except OperationTimeoutError as err:
            # Command accepted (xSDisarmPanel res: OK) but the confirmation
            # poll didn't resolve within poll_timeout. The panel is almost
            # certainly actioning it (issue #508, IT backend). Reflect the
            # target optimistically (fail-safe) and let the coordinator's
            # xSStatus read reconcile — do NOT roll back or report a failure.
            self._set_waf_blocked(False)
            self._set_state_provisional(True)
            self.update_status_alarm(self._optimistic_status(target))
            _LOGGER.warning(
                "Disarm not confirmed within timeout for %s; state provisional, "
                "awaiting reconciliation: %s",
                self.installation.number,
                err.log_detail(),
            )
            self._notify_operation_unconfirmed("disarm_unconfirmed")
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except VerisureOwaError as err:
            self._state = self._last_state
            _LOGGER.error(
                "Disarm failed for %s: %s", self.installation.number, err.log_detail()
            )
            self._handle_arm_disarm_error(err, "disarm_failed")
            self.async_write_ha_state()
            await inject_ha_event(
                self.hass,
                self._installation,
                category=ActivityCategory.COMMUNICATION_FAILED,
                alias=f"Disarm failed: {err}",
                context=user_context,
            )
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
        bypassed_exceptions: list[dict[str, Any]] | None = None,
    ) -> None:
        """Set the arm state using the command resolver."""
        # Capture the calling user's context up-front — HA expires
        # `self._context` ~1 s after async_set_context, and the arm
        # transition + state writes below take longer than that.
        user_context = self._context
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
            self.update_status_alarm(result)
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
            # Force-arm (after exceptions) keeps a different category so the
            # bypassed-zones state is visible in the timeline.
            armed_with_exceptions = bool(force_arming_remote_id)
            forced_excs: list[ActivityException] | None = None
            if armed_with_exceptions and bypassed_exceptions:
                forced_excs = [
                    ActivityException.model_validate(e) for e in bypassed_exceptions
                ]
            await inject_ha_event(
                self.hass,
                self._installation,
                category=(
                    ActivityCategory.ARMED_WITH_EXCEPTIONS
                    if armed_with_exceptions
                    else ActivityCategory.ARMED
                ),
                alias=("Armed with exceptions" if armed_with_exceptions else "Armed"),
                context=user_context,
                exceptions=forced_excs,
            )
        except OperationTimeoutError as err:
            # Arm accepted (xSArmPanel res: OK) but confirmation poll timed
            # out. Optimistically reflect the target and reconcile via the
            # coordinator — never roll back to the pre-arm state (#508).
            self._set_waf_blocked(False)
            self._set_state_provisional(True)
            self.update_status_alarm(self._optimistic_status(target))
            _LOGGER.warning(
                "Arm not confirmed within timeout for %s; state provisional, "
                "awaiting reconciliation: %s",
                self.installation.number,
                err.log_detail(),
            )
            self._notify_operation_unconfirmed("arm_unconfirmed")
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except ArmingExceptionError as exc:
            self._set_force_context(exc, mode)
            self._state = self._last_state
            self._fire_arming_exception_event(exc, mode)
            self.async_write_ha_state()
            # Surface the rejection in the activity timeline as well — the
            # polled record (~60 s later) will be a 5802; this gives the
            # user immediate feedback with the offending zones.
            await inject_ha_event(
                self.hass,
                self._installation,
                category=ActivityCategory.ARMING_FAILED,
                alias="Arming failed",
                context=user_context,
                exceptions=[
                    ActivityException.model_validate(e) for e in exc.exceptions
                ],
            )
        except VerisureOwaError as err:
            if self._last_arm_result.protom_response:
                self.update_status_alarm(self._last_arm_result)
            else:
                self._state = self._last_state
            _LOGGER.error(
                "Arm failed for %s: %s", self.installation.number, err.log_detail()
            )
            self._handle_arm_disarm_error(err, "arm_failed")
            self.async_write_ha_state()
            await inject_ha_event(
                self.hass,
                self._installation,
                category=ActivityCategory.ARMING_FAILED,
                alias=f"Arm failed: {err}",
                context=user_context,
            )
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
        self._schedule_force_arm_expiry()

    def _fire_arming_exception_event(
        self, exc: ArmingExceptionError, mode: str
    ) -> None:
        """Fire the arming-exception event under both ``verisure_owa_*`` and ``securitas_*``.

        ``fire_event`` emits both names with identical payloads. User
        automations listening to either name continue to work; docs
        recommend the ``verisure_owa_arming_exception`` form.
        """
        zones = [e.get("alias", "unknown") for e in exc.exceptions]
        payload = {
            "entity_id": self.entity_id,
            "mode": mode,
            "zones": zones,
            "details": {
                "installation": self.installation.number,
                "exceptions": exc.exceptions,
            },
            "_event_id": str(uuid.uuid4()),
        }
        fire_event(self.hass, "arming_exception", payload)

    def _fire_force_arm_expired_event(self) -> None:
        """Fire force_arm_expired event under both ``verisure_owa_*`` and ``securitas_*``.

        Must be called BEFORE the context is wiped — derives the payload from
        the still-live _force_context snapshot.
        """
        assert self._force_context is not None, (
            "_fire_force_arm_expired_event called without a force_context"
        )
        exceptions = self._force_context.get("exceptions", [])
        zones = [e.get("alias", "unknown") for e in exceptions]
        payload = {
            "entity_id": self.entity_id,
            "mode": self._force_context["mode"],
            "zones": zones,
            "details": {
                "installation": self.installation.number,
                "exceptions": exceptions,
            },
            "_event_id": str(uuid.uuid4()),
        }
        fire_event(self.hass, "force_arm_expired", payload)

    def _fire_arming_exception_dismissed_event(
        self, *, reason: DismissalReason, new_mode: str | None
    ) -> None:
        """Fire the verisure_owa_arming_exception_dismissed event.

        Caller is the panel that HELD the dismissed context (so payload
        entity_id is self.entity_id), even if the action that triggered
        the dismissal originated on a sibling panel.

        ``new_mode`` is None when the dismissal is triggered by entity
        teardown (reason="integration_reload") — at that point there is
        no new mode being targeted, the entity is simply being removed.
        """
        payload = {
            "entity_id": self.entity_id,
            "reason": reason,
            "new_mode": new_mode,
            "details": {"installation": self.installation.number},
            "_event_id": str(uuid.uuid4()),
        }
        fire_event(self.hass, "arming_exception_dismissed", payload)

    _FORCE_ARM_TTL = datetime.timedelta(seconds=180)

    def _schedule_force_arm_expiry(self) -> None:
        """Schedule the TTL-driven expiry callback.

        Replaces the previous coordinator-update-driven TTL check, which
        was unreliable: HA's DataUpdateCoordinator does not call its
        listeners on consecutive failures, so a sustained API outage
        starting before the TTL would miss the expiry event entirely.
        """
        self._cancel_force_arm_expiry()
        self._force_arm_expiry_unsub = async_call_later(
            self.hass,
            self._FORCE_ARM_TTL,
            self._async_handle_force_arm_expiry,
        )

    def _cancel_force_arm_expiry(self) -> None:
        """Cancel any pending expiry timer (no-op if not scheduled)."""
        if self._force_arm_expiry_unsub is not None:
            self._force_arm_expiry_unsub()
            self._force_arm_expiry_unsub = None

    async def _async_handle_force_arm_expiry(self, _now: datetime.datetime) -> None:
        """Timer callback: fire expired event + side effects if context still alive.

        The timer fires exactly _FORCE_ARM_TTL after _set_force_context,
        independent of coordinator state. If the context was already cleared
        by the canonical resolution paths (force_arm, force_arm_cancel,
        dismissal), this callback no-ops.
        """
        self._force_arm_expiry_unsub = None
        if self._force_context is None:
            return
        self._fire_force_arm_expired_event()
        if self._notifications_enabled:
            self._notify_force_arm_expired()
        self._wipe_force_arm_state()
        self.async_write_ha_state()

    def _clear_force_context(self) -> None:
        """Cancel any pending TTL timer and wipe force-arm context attributes.

        TTL-driven expiry is handled by ``_async_handle_force_arm_expiry``
        scheduled in ``_set_force_context``; this method just performs the
        unconditional wipe used by the canonical resolution paths
        (force_arm, force_arm_cancel, sibling dismissal).
        """
        self._cancel_force_arm_expiry()
        self._wipe_force_arm_state()

    def _wipe_force_arm_state(self) -> None:
        """Clear the in-memory force-arm context dict and its public attributes.

        Shared by the timer expiry path and the canonical-resolution clear
        path so both stay in lock-step when new force-arm-related entity
        attributes get added.
        """
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

    def _siblings_on_installation(self) -> list[BaseVerisureOwaAlarmPanel]:
        """Return all alarm panels (combined + sub-panels) for this installation.

        Walks ``hass.data[DOMAIN]`` config-entry buckets — each entry's
        ``combined_alarm_panels`` and ``axis_alarm_panels`` are populated by
        ``alarm_control_panel.__init__.async_setup_entry``.

        Always includes ``self``. Returns ``[self]`` if entry data is missing
        (defensive — early registration paths or test scaffolding may not
        have populated the buckets yet).
        """
        inst_num = self.installation.number
        siblings: list[BaseVerisureOwaAlarmPanel] = []
        domain_data = self.hass.data.get(DOMAIN, {})
        for entry_data in domain_data.values():
            if not isinstance(entry_data, dict):
                continue
            combined = entry_data.get("combined_alarm_panels", {}).get(inst_num)
            if combined is not None:
                siblings.append(combined)
            axis_panels = entry_data.get("axis_alarm_panels", {}).get(inst_num, {})
            siblings.extend(axis_panels.values())
        if self not in siblings:
            siblings.append(self)
        return siblings

    async def _dismiss_pending_force_context_on_siblings(
        self, *, reason: DismissalReason, new_mode: str
    ) -> None:
        """For every panel on this installation that has an active force-arm
        context, fire the dismissed event and clear the context.

        Called from the regular arm/disarm entry points (`_async_arm`,
        `async_alarm_disarm`) BEFORE the new operation dispatches, so the
        user sees stale notifications vanish immediately even if the new
        operation fails.

        Each panel that held a context is attributed in its own dismissed
        event with its own entity_id; typically only zero or one panel
        holds context at any time.
        """
        for panel in self._siblings_on_installation():
            if panel._force_context is None:  # noqa: SLF001  # pylint: disable=protected-access
                continue
            # Fire the public event first (panel attribution), then wipe
            # the panel's context. The integration's own dismissed-event
            # handler clears the shared notification.
            panel._fire_arming_exception_dismissed_event(  # noqa: SLF001  # pylint: disable=protected-access
                reason=reason,
                new_mode=new_mode,
            )
            panel._clear_force_context()  # noqa: SLF001  # pylint: disable=protected-access
            # Push the wiped `force_arm_available` / `arm_exceptions`
            # attributes to HA's state machine on every cleared panel.
            # `self` will be re-written by the caller's downstream
            # `set_arm_state` / disarm flow, but siblings have no other
            # path to refresh and would otherwise display stale
            # attributes until the next coordinator update.
            panel.async_write_ha_state()

    @property
    def _notifications_enabled(self) -> bool:
        """Return True if the built-in force-arm notification handler is active."""
        return self._client.config.get(CONF_FORCE_ARM_NOTIFICATIONS, True)

    def _register_arming_exception_handler(self) -> None:
        """Register event listeners for built-in arming exception notifications.

        Listens to:
        - ``verisure_owa_arming_exception`` (canonical) — sends initial
          persistent + mobile notifications with action buttons.
        - ``securitas_arming_exception`` — deprecated alias of the above,
          removed in v6.0.0. Deduplicated via _event_id so the handler
          fires at most once per arming exception even though both events
          carry the same payload.
        - ``verisure_owa_force_arm_expired`` — replaces the mobile
          notification with a button-less informational card on TTL
          expiry. The persistent side is updated directly by
          `_async_handle_force_arm_expiry` (the TTL timer callback),
          which fires the event AND calls `_notify_force_arm_expired()`
          in the same tick.
        - ``verisure_owa_arming_exception_dismissed`` — clears the shared
          installation-scoped persistent + mobile notifications when the
          stale force-arm context is dismissed (e.g. by a new arm/disarm
          on this or a sibling panel). Does NOT use the `_last_handled_event_id`
          dedup slot — dismissed events have unique `_event_id`s by
          construction and must not clobber the dedup slot used by
          arming-exception/expiry events.
        """

        @callback
        def _handle_arming_exception_event(event: Event) -> None:
            """Handle arming exception event for this entity."""
            if event.data.get("entity_id") != self.entity_id:
                return
            eid = event.data.get("_event_id")
            if eid is not None and eid == self._last_handled_event_id:
                return
            self._last_handled_event_id = eid
            self._notify_arm_exceptions_from_event(event)

        @callback
        def _handle_force_arm_expired_event(event: Event) -> None:
            """Handle force-arm-expired event for this entity."""
            if event.data.get("entity_id") != self.entity_id:
                return
            eid = event.data.get("_event_id")
            # Reuse the same dedup slot — the same event_id can only ever
            # describe one transition, never both an arming exception AND
            # an expiry, so collisions are not possible in practice.
            if eid is not None and eid == self._last_handled_event_id:
                return
            self._last_handled_event_id = eid
            self._notify_force_arm_expired_mobile_from_event(event)

        @callback
        def _handle_arming_exception_dismissed_event(event: Event) -> None:
            """Handle dismissed event for this entity by clearing notifications."""
            if event.data.get("entity_id") != self.entity_id:
                return
            # The notifications-enabled gate lives in async_added_to_hass at
            # registration time; if we got here, the toggle was True. But the
            # config can change at runtime via the options flow, so re-check
            # before doing the dismiss work.
            if not self._notifications_enabled:
                return
            self._dismiss_arming_exception_notification()

        # Subscribe only to the verisure_owa_* form — fire_event always
        # emits both names, so a single listener catches every emission
        # the integration itself produces. A user-fired securitas_*
        # event won't trigger this listener; user-facing code should fire
        # the verisure_owa_* form.
        self._arming_event_unsub_new = self.hass.bus.async_listen(
            ARMING_EXCEPTION_EVENT_TYPE,
            _handle_arming_exception_event,
        )
        self._force_arm_expired_event_unsub = self.hass.bus.async_listen(
            FORCE_ARM_EXPIRED_EVENT_TYPE,
            _handle_force_arm_expired_event,
        )
        self._arming_exception_dismissed_event_unsub = self.hass.bus.async_listen(
            ARMING_EXCEPTION_DISMISSED_EVENT_TYPE,
            _handle_arming_exception_dismissed_event,
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

    async def _async_notify_force_arm_expired_mobile(self, event: Event) -> None:
        """Replace the mobile arming-exception notification with a button-less
        informational card when the force-arm window expires.

        Same `tag` as the original notification (so iOS/Android updates the
        existing card in place rather than stacking a new one). No `actions`
        array — the buttons are removed.

        No-ops when notifications are disabled or no notify_group is configured.
        Per-entity scoped: ignores events whose entity_id is not ours.
        """
        if event.data.get("entity_id") != self.entity_id:
            return
        if not self._notifications_enabled:
            return
        notify_group = self.client.config.get(CONF_NOTIFY_GROUP)
        if not notify_group:
            return

        entry = get_notification_strings(self.hass, "force_arm_expired")
        title = entry.get("title", "")
        # Fall back to message if mobile_message is missing — defensive against
        # partial translation data; existing tests assert mobile_message is
        # present in every locale we ship, but a future locale might lag.
        mobile_message = entry.get("mobile_message") or entry.get("message", "")

        await self.hass.services.async_call(
            domain="notify",
            service=notify_group,
            service_data={
                "title": title,
                "message": mobile_message,
                "data": {
                    "tag": self._arming_exception_notification_id,
                },
            },
        )

    def _notify_force_arm_expired_mobile_from_event(self, event: Event) -> None:
        """Schedule the async expiry-mobile-notify on the HA loop."""
        self.hass.async_create_task(self._async_notify_force_arm_expired_mobile(event))

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

        Called by the verisure_owa.force_arm_cancel service. Clears the stored
        exception context and dismisses the arming-exception notification.
        """
        if self._force_context is None:
            _LOGGER.warning(
                "force_arm_cancel called for %s but no force context available",
                self.installation.number,
            )
            return
        _LOGGER.info("Force-arm cancelled by user")
        self._clear_force_context()
        if self._notifications_enabled:
            self._dismiss_arming_exception_notification()
        self.async_write_ha_state()

    async def async_force_arm(self, code: str | None = None) -> None:
        """Force-arm using stored exception context.

        Called by the verisure_owa.force_arm service. Re-arms in the same mode
        that previously failed, passing the stored referenceId and suid to
        override non-blocking exceptions.

        The presence of self._force_context is itself proof that a PIN-
        authenticated arm reached the server within the last scan_interval
        — set_arm_state can only populate the context after _async_arm
        passes _check_code_for_arm_if_required.  So we don't re-prompt for
        the PIN on this second-half completion (which would also break the
        mobile-notification tap flow, since notifications can't carry a PIN).

        If a service caller passes ``code`` explicitly (defence-in-depth for
        paranoid automations) we still validate it against the configured PIN.
        """
        if self._force_context is None:
            _LOGGER.warning(
                "force_arm called for %s but no force context available",
                self.installation.number,
            )
            return
        if code is not None:
            self._check_code(code)
        mode = self._force_context["mode"]
        ref_id = self._force_context["reference_id"]
        suid = self._force_context["suid"]
        # Capture exceptions before _clear_force_context wipes the context —
        # set_arm_state's success path uses these to populate the injected
        # `armed_with_exceptions` event with the bypassed-zone list.
        bypassed = list(self._force_context.get("exceptions", []))
        _LOGGER.info(
            "Force-arming: overriding previous exceptions %s",
            [e.get("alias") for e in bypassed],
        )
        self._clear_force_context()
        if self._notifications_enabled:
            self._dismiss_arming_exception_notification()
        self._force_state(AlarmControlPanelState.ARMING)
        await self.set_arm_state(
            mode,
            force_arming_remote_id=ref_id,
            suid=suid,
            bypassed_exceptions=bypassed,
        )

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
