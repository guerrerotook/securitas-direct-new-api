"""Verisure OWA API client.

The single client class handles authentication lifecycle, typed GraphQL
execution, and polling.  It is composed from per-domain mixins kept in
private sibling modules:

- ``_base`` — shared state (init, headers, GraphQL execute, polling).
- ``_auth`` — login / refresh / logout / 2FA.
- ``_alarm`` — arm / disarm / check-alarm / status.
- ``_activity`` — panel timeline.
- ``_lock`` — smart-lock status / config / mode change.
- ``_camera`` — camera discovery / capture / thumbnail / full image.
- ``_sentinel`` — comfort sensors and air-quality.
- ``_installation`` — installation list + service catalog.

Module-level helpers (``generate_uuid``, ``generate_device_id``) and the
public lock-device constants stay re-exported here so existing imports
from ``verisure_owa_api.client`` keep working unchanged.
"""

from __future__ import annotations

import secrets
from uuid import uuid4

from ._activity import _ActivityMixin
from ._alarm import _AlarmMixin
from ._auth import _AuthMixin
from ._camera import _CameraMixin
from ._installation import _InstallationMixin
from ._lock import SMARTLOCK_DEVICE_ID, _LockMixin
from ._sentinel import _SentinelMixin

__all__ = [
    "SMARTLOCK_DEVICE_ID",
    "VerisureOwaClient",
    "generate_device_id",
    "generate_uuid",
]


def generate_uuid() -> str:
    """Create a device id."""
    return str(uuid4()).replace("-", "")[0:16]


def generate_device_id() -> str:
    """Create a device identifier for the API."""
    return secrets.token_urlsafe(16) + ":APA91b" + secrets.token_urlsafe(130)[0:134]


class VerisureOwaClient(  # pylint: disable=too-many-ancestors
    _AuthMixin,
    _AlarmMixin,
    _ActivityMixin,
    _LockMixin,
    _CameraMixin,
    _SentinelMixin,
    _InstallationMixin,
):
    """Verisure OWA API client.

    Handles authentication lifecycle, typed GraphQL execution, and polling.
    Uses HttpTransport for the raw HTTP layer.  All behaviour is defined on
    the per-domain mixins; this class composes them.
    """
