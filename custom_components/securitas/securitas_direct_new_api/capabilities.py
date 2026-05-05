"""Capability-based detection helpers.

Pure functions that take already-fetched installation, services and
capabilities data and decide what features the integration should expose.
"""

from __future__ import annotations

from typing import Iterable

from .models import Attribute, Installation, Service


def detect_peri(
    installation: Installation | None | object,
    services: Iterable[Service],
    capabilities: frozenset[str],
) -> bool:
    """Return True if perimeter is supported, layered across all known signals.

    Signals (any returns True):
      1. JWT capability set contains "PERI" (SDVFAST Spanish/UK panels).
      2. A service entry with request="PERI" and active=True (alternative
         SDVFAST signal).
      3. Any service has an attribute named "PERI" (matches SCH service
         attributes — original detection branch).
      4. installation.alarm_partitions has an id="02" entry with non-empty
         enterStates (SDVECU Italian panels — these do NOT advertise PERI
         in the JWT or as a service).
    """
    # Signal 1: JWT capability
    if "PERI" in capabilities:
        return True

    # Signal 2: active PERI service
    for svc in services:
        if getattr(svc, "request", None) == "PERI" and getattr(svc, "active", False):
            return True

    # Signal 3: SCH (or any) service has PERI attribute
    for svc in services:
        attrs = getattr(svc, "attributes", None) or []
        for attr in attrs:
            if isinstance(attr, Attribute) and attr.name == "PERI":
                return True

    # Signal 4: alarm partition 02 with non-empty enterStates
    partitions = getattr(installation, "alarm_partitions", None) or []
    for partition in partitions:
        if partition.get("id") == "02" and partition.get("enterStates"):
            return True

    return False


def detect_annex(capabilities: frozenset[str]) -> bool:
    """Return True if the annex axis is available on this installation.

    Annex detection is JWT-only — empirically, installations with annex
    always advertise both ARMANNEX and DARMANNEX in the capability set.
    There is no service-attribute or partition fallback for annex (none
    has been observed).
    """
    return "ARMANNEX" in capabilities and "DARMANNEX" in capabilities


def supported_interior_modes(capabilities: frozenset[str]) -> set[str]:
    """Return the set of capability strings indicating supported interior modes.

    Result is a subset of {"ARM", "ARMDAY", "ARMNIGHT"}. Used by the
    Interior sub-panel to derive supported_features.
    """
    return {c for c in ("ARM", "ARMDAY", "ARMNIGHT") if c in capabilities}
