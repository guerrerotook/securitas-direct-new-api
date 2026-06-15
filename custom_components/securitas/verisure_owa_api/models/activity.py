"""Panel activity-timeline domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field, computed_field, model_validator

from ..pydantic_utils import NullSafeBase as _NullSafeBase


class ActivityException(_NullSafeBase):
    """Sensor exception attached to an armed-with-exceptions / arming-failed event.

    Reported when the panel arms despite a zone being unable to fully participate
    (door open, battery flat, etc.) or when the panel rejects the arm command
    because of those exceptions.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: str = ""
    device_type: str = Field(default="", validation_alias="deviceType")
    alias: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_key(self) -> str:
        """Translation key for the exception's status code.

        Mapping is conservative — only the values confirmed in real installations
        are translated; unmapped codes fall through to "unknown" rather than
        guessing.
        """
        if self.status == "0":
            return "open"
        if self.status == "2":
            return "battery_low"
        return "unknown"


class ActivityCategory(StrEnum):
    """High-level grouping of xSActV2 event type codes for UI / i18n.

    Type codes from the panel are granular (Armed-perimeter vs Armed-night vs
    Activation-indoor+outdoor all map to ARMED).  Categories give cards a
    stable key to localise / icon against without enumerating every code.
    """

    ARMED = "armed"
    ARMED_WITH_EXCEPTIONS = "armed_with_exceptions"
    ARMING_FAILED = "arming_failed"
    DISARMED = "disarmed"
    ALARM = "alarm"
    ALARM_RESOLVED = "alarm_resolved"
    TAMPERING = "tampering"
    SABOTAGE = "sabotage"
    IMAGE_REQUEST = "image_request"
    POWER_CUT = "power_cut"
    POWER_RESTORED = "power_restored"
    STATUS_CHECK = "status_check"
    # Communication problem with the panel — distinct from ARMING_FAILED
    # (an arm rejected because of exceptions). Verisure's own UI uses labels
    # like "Error processing alarm deactivation" for these; the panel emits
    # type 501 on a failed arm/disarm round-trip and 502 on a failed status
    # refresh.
    COMMUNICATION_FAILED = "communication_failed"
    # Panel's link to the central/website returned to normal after being
    # unreachable. Mirror of COMMUNICATION_FAILED — the panel emits this
    # when comms recover so the user can correlate outages.
    COMMUNICATION_RESTORED = "communication_restored"
    # Connected smart-lock (DR device) door signals — the lock opening and
    # then auto-locking. Distinct events so cards can icon them separately.
    DOOR_OPENED = "door_opened"
    DOOR_CLOSED = "door_closed"
    # A Verisure-app "routine" fired — a user-scheduled automation that can
    # arm/disarm the alarm on a schedule.
    ROUTINE_EXECUTED = "routine_executed"
    UNKNOWN = "unknown"


# Numeric type → category map. Codes seen in real fixture data.
#
# Note on the 800-series: in Verisure parlance "connessione/connection" means
# the alarm being *armed* (not network connectivity).  802/821/823/824 are
# panel-emitted arm-state signals; 822 is the corresponding disarm signal.
_ACTIVITY_TYPE_TO_CATEGORY: dict[int, ActivityCategory] = {
    # Armed — user-initiated arm commands and the panel-emitted arm signals
    2: ActivityCategory.ARMED,
    31: ActivityCategory.ARMED,  # Spanish panel: armed interior ("Conexión")
    37: ActivityCategory.ARMED,
    40: ActivityCategory.ARMED,  # Spanish panel: armed exterior ("Conexión modo exterior")
    46: ActivityCategory.ARMED,
    701: ActivityCategory.ARMED,
    721: ActivityCategory.ARMED,
    801: ActivityCategory.ARMED,  # "Attivazione modalità totale" — Italian interior total arm
    802: ActivityCategory.ARMED,  # "Attivazione modalità parziale" / "Connection Main partial"
    821: ActivityCategory.ARMED,  # "Attivazione Perimetrale" — Italian perimeter arm
    823: ActivityCategory.ARMED,  # "Attivazione Perimetrale + Totale" — perimeter + total
    824: ActivityCategory.ARMED,  # "Connection Exterior + Main partial"
    # Force-armed with sensor exceptions bypassed (NOT an alarm — the panel
    # armed despite open zones or dead batteries; bypassed zones in `exceptions[]`)
    850: ActivityCategory.ARMED_WITH_EXCEPTIONS,
    # Arm attempts the panel rejected because of exceptions.  The 5xxx range
    # mirrors the corresponding 8xx connection-success codes (5802 → 802 Main
    # partial; 5824 → 824 Exterior + Main partial).  Add more codes here as
    # they're observed.
    5802: ActivityCategory.ARMING_FAILED,
    5823: ActivityCategory.ARMING_FAILED,  # 823 mirror — Exterior + Main total
    5824: ActivityCategory.ARMING_FAILED,
    # Spanish-firmware arming-failure codes — emitted as "Error conectando ..."
    # in the panel timeline. Without these mappings the rows show as
    # "Unknown event" AND escape the polled-echo dedup filter (which requires
    # category ∈ HA_INJECTABLE_CATEGORIES), so every HA-initiated arm
    # rejection appears twice in the activity log. Add more codes here as
    # they're observed on other panels.
    531: ActivityCategory.ARMING_FAILED,  # "Error conectando la alarma en modo parcial día"
    537: ActivityCategory.ARMING_FAILED,  # "Error conectando interior + exterior"
    540: ActivityCategory.ARMING_FAILED,  # "Error conectando la alarma perimetral"
    546: ActivityCategory.ARMING_FAILED,  # "Error conectando la alarma en modo parcial noche"
    # Disarmed — user-initiated disarm commands and the panel-emitted disarm signal
    1: ActivityCategory.DISARMED,
    32: ActivityCategory.DISARMED,  # Spanish panel: disarmed interior (pair with 31 armed)
    107: ActivityCategory.DISARMED,
    700: ActivityCategory.DISARMED,
    720: ActivityCategory.DISARMED,
    # "Disattivazione" — generic Italian disarm (fires after 801/802)
    800: ActivityCategory.DISARMED,
    820: ActivityCategory.DISARMED,  # "Disattivazione Perimetrale" — perimeter-only disarm
    822: ActivityCategory.DISARMED,  # "Disattivazione Perimetrale + Principale" — perimeter + main
    # Alarms
    13: ActivityCategory.ALARM,
    14: ActivityCategory.ALARM,  # "Allarme Foto" — photo-detector alarm (img=1 carries the image)
    24: ActivityCategory.TAMPERING,
    241: ActivityCategory.SABOTAGE,
    331: ActivityCategory.ALARM_RESOLVED,
    # Other
    16: ActivityCategory.IMAGE_REQUEST,
    25: ActivityCategory.POWER_CUT,
    26: ActivityCategory.POWER_RESTORED,
    27: ActivityCategory.STATUS_CHECK,
    # Panel-side communication failure (arm/disarm couldn't reach the panel
    # in 501; status-check refresh failed in 502). Surfaced alongside the
    # localised "Sorry, action couldn't be performed" alias by the panel.
    501: ActivityCategory.COMMUNICATION_FAILED,
    502: ActivityCategory.COMMUNICATION_FAILED,
    # "Estado de las comunicaciones" — emitted when the panel's link to the
    # central/website returns to normal after a period of being unreachable.
    3121: ActivityCategory.COMMUNICATION_RESTORED,
    # Connected smart-lock (DR device) door signals. Seen on a French panel as
    # "Porte ouverte" (324, lock opened) / "Porte fermée" (325, lock auto-locked
    # a few minutes later). GitHub #512.
    324: ActivityCategory.DOOR_OPENED,
    325: ActivityCategory.DOOR_CLOSED,
    # A Verisure-app "routine" fired (source=ROUTINES) — a user-scheduled
    # automation that can arm/disarm the alarm. Seen as "Routine exécutée".
    # GitHub #513.
    70: ActivityCategory.ROUTINE_EXECUTED,
}


class ActivityEvent(_NullSafeBase):
    """A single entry from the alarm panel's xSActV2 timeline."""

    model_config = ConfigDict(populate_by_name=True)

    alias: str = ""
    type: int = 0
    device: str | None = None
    source: str | None = None
    id_signal: str = Field(default="", validation_alias="idSignal")
    scheduler_type: str | None = Field(default=None, validation_alias="schedulerType")
    verisure_user: str | None = Field(default=None, validation_alias="myVerisureUser")
    time: str = ""
    img: int = 0
    incidence_id: str | None = Field(default=None, validation_alias="incidenceId")
    signal_type: int = Field(default=0, validation_alias="signalType")
    interface: str | None = None
    device_name: str | None = Field(default=None, validation_alias="deviceName")
    keyname: str | None = None
    tag_id: str | None = Field(default=None, validation_alias="tagId")
    user_auth: str | None = Field(default=None, validation_alias="userAuth")
    exceptions: list[ActivityException] | None = None
    media_platform: dict[str, Any] | None = Field(
        default=None, validation_alias="mediaPlatform"
    )
    # True when the event was synthesized by this integration (e.g. an
    # arm/disarm injected at the moment HA issued the command).  Polled
    # entries from the panel default to False.
    injected: bool = False
    # When set, this polled (panel) entry is a probable duplicate of the
    # injected HA event whose ``id_signal`` this holds — i.e. the panel's own
    # echo of an action HA issued, matched by category + timestamp proximity.
    # The card nests it inside the HA event's detail and the bus listener does
    # not re-fire it, so an HA-issued action triggers automations only once.
    duplicate_of: str | None = None
    # Semantic grouping — explicit on HA-injected events, derived from `type`
    # for polled events via the model validator below.  Keep `category` rather
    # than `type` as the canonical filter for automations: the `type` field
    # holds the panel's raw code, which varies across installations for the
    # same logical event (e.g. disarm = 1 / 32 / 700 / 720 depending on panel).
    category: ActivityCategory = ActivityCategory.UNKNOWN

    @model_validator(mode="before")
    @classmethod
    def _derive_category_from_type(cls, data: Any) -> Any:
        """Default `category` from the numeric `type` for polled inputs.

        Skipped when the caller (e.g. ``make_synthetic_event``) sets
        ``category`` explicitly.
        """
        if not isinstance(data, dict) or "category" in data:
            return data
        type_val = data.get("type", data.get("signalType", 0))
        try:
            cat = _ACTIVITY_TYPE_TO_CATEGORY.get(int(type_val))
        except (TypeError, ValueError):
            cat = None
        if cat is not None:
            data = dict(data)
            data["category"] = cat.value
        return data
