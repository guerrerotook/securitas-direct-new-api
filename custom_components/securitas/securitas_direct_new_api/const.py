"""Define constants for Securitas Direct API."""

from enum import IntEnum, auto
from typing import Final

API_ARM: Final[str] = "ARM1"
API_ARM_DAY: Final[str] = "ARMDAY1"
API_ARM_NIGHT: Final[str] = "ARMNIGHT1"
API_ARM_PERI: Final[str] = "PERI1"
API_ARM_INTANDPERI: Final[str] = "ARM1PERI1"
API_ARM_PARTIALINTANDPERI: Final[str] = "ARMDAY1PERI1"

API_DISARM: Final[str] = "DARM1"
API_DISARM_INTANDPERI: Final[str] = "DARM1DARMPERI"


class SecDirAlarmState(IntEnum):
    """Define possible stats of an SD alarm as seen on the app or website."""

    INTERIOR_PARTIAL = auto()
    INTERIOR_TOTAL = auto()
    INTERIOR_DISARMED = auto()
    INTERIOR_PARTIAL_AND_PERI = auto()
    NIGHT_ARMED = auto()
    EXTERIOR_ARMED = auto()
    EXTERIOR_DISARMED = auto()
    TOTAL_ARMED = auto()
    TOTAL_DISARMED = auto()


MAP_STATE_TO_PROTO_STATUS = {
    SecDirAlarmState.INTERIOR_PARTIAL: "P",
    SecDirAlarmState.INTERIOR_TOTAL: "T",
    SecDirAlarmState.INTERIOR_DISARMED: "D",
    SecDirAlarmState.INTERIOR_PARTIAL_AND_PERI: "",  # FIXME
    SecDirAlarmState.NIGHT_ARMED: "Q",
    SecDirAlarmState.EXTERIOR_ARMED: "E",
    SecDirAlarmState.EXTERIOR_DISARMED: "D",
    SecDirAlarmState.TOTAL_ARMED: "T",
    SecDirAlarmState.TOTAL_DISARMED: "D",
}

# Map alarm states to commands. These "standard" commands assume there are no
# exterior (perimetral) sensors, so having a state to arm the exterior doesn't
# make a lot of sense, but the original HA code had this, so I just left it here
STD_COMMANDS_MAP = {
    SecDirAlarmState.EXTERIOR_ARMED: API_ARM_PERI,  # see comment above
    SecDirAlarmState.INTERIOR_PARTIAL: API_ARM_DAY,
    SecDirAlarmState.INTERIOR_TOTAL: API_ARM,
    SecDirAlarmState.NIGHT_ARMED: API_ARM_NIGHT,
    SecDirAlarmState.TOTAL_ARMED: API_ARM,
    SecDirAlarmState.TOTAL_DISARMED: API_DISARM,
}

# Map alarm states to commands assuming there are exterior (perimetral) sensors.
PERI_COMMANDS_MAP = {
    SecDirAlarmState.EXTERIOR_ARMED: API_ARM_PERI,
    SecDirAlarmState.EXTERIOR_DISARMED: API_DISARM,
    SecDirAlarmState.INTERIOR_PARTIAL: API_ARM_DAY,
    SecDirAlarmState.INTERIOR_TOTAL: API_ARM,
    SecDirAlarmState.INTERIOR_PARTIAL_AND_PERI: API_ARM_PARTIALINTANDPERI,
    SecDirAlarmState.INTERIOR_DISARMED: API_DISARM,
    # AlarmStates.NIGHT_ARMED: API_ARM_NIGHT,
    SecDirAlarmState.TOTAL_ARMED: API_ARM_INTANDPERI,
    SecDirAlarmState.TOTAL_DISARMED: API_DISARM_INTANDPERI,
}


class CommandType(IntEnum):
    """Enumerate possible mappings from states to commands."""

    STD = auto()
    PERI = auto()


# The ApiManager will pick one mapping from this
COMMAND_MAP = {
    CommandType.STD: STD_COMMANDS_MAP,
    CommandType.PERI: PERI_COMMANDS_MAP,
}
