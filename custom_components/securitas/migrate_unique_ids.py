"""Registry-rewrite that unifies pre-v5 entity unique_ids onto the
v5.0.2 canonical ``v4_securitas_direct.<num>_<type>`` form.

The pre-v5 codebase used three inconsistent unique_id shapes:

- ``v4_securitas_direct.<num>`` (alarm panel) and
  ``v4_securitas_direct.<num>_lock_<id>`` (lock) — dotted, branded prefix.
- ``v4_<num>_<type>[_<id>]`` (everything else — wifi sensor, capture
  button, camera, sentinel sensors) — bare prefix, snake-case.
- ``v4_refresh_button_<num>`` (refresh button only) — type-then-number.

v5.0.2 generates new entities exclusively in the first form. This
module's ``migrate_unique_ids`` runs once per config entry on
``async_setup_entry`` and rewrites any entity-registry row still
holding one of the other two shapes onto the canonical shape. The
rewrite preserves the row's ``entity_id``, so HACS upgraders don't
see duplicated entities with ``_2`` suffixes after the v5.0.2 upgrade.

Idempotent — entries already on the canonical form are left alone.
"""

from __future__ import annotations

import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_CANONICAL_PREFIX = "v4_securitas_direct."

# Refresh button: type-then-number ordering, only entity with this shape.
_REFRESH_BUTTON_RE = re.compile(r"^v4_refresh_button_(?P<num>\d+)$")

# Everything else: v4_<num>_<rest> where <num> is the installation number
# (always digits) and <rest> is the type-and-maybe-id suffix.
_BARE_V4_RE = re.compile(r"^v4_(?P<num>\d+)_(?P<rest>.+)$")


def canonical_unique_id(old: str) -> str | None:
    """Return the canonical ``v4_securitas_direct.<...>`` form of ``old``.

    Returns ``None`` for inputs that are already canonical or that don't
    match any known pre-v5 shape. The ``None`` return is the "no rewrite
    needed" signal used by ``async_migrate_entries``.
    """
    if old.startswith(_CANONICAL_PREFIX):
        return old  # already canonical; helps pure-function readability

    refresh = _REFRESH_BUTTON_RE.match(old)
    if refresh:
        return f"{_CANONICAL_PREFIX}{refresh.group('num')}_refresh_button"

    bare = _BARE_V4_RE.match(old)
    if bare:
        return f"{_CANONICAL_PREFIX}{bare.group('num')}_{bare.group('rest')}"

    return None  # not a shape we recognise; leave the entry alone


async def migrate_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rewrite this entry's pre-v5 entity unique_ids to the canonical form.

    Called once per ``async_setup_entry`` invocation. Idempotent — re-running
    on an already-migrated entry is a no-op.
    """

    @callback
    def _maybe_rewrite(registry_entry: er.RegistryEntry) -> dict[str, str] | None:
        # async_migrate_entries already filters by config_entry_id, but
        # defensively skip rows whose integration isn't us.
        if registry_entry.platform != DOMAIN:
            return None
        new_uid = canonical_unique_id(registry_entry.unique_id)
        if new_uid is None or new_uid == registry_entry.unique_id:
            return None
        _LOGGER.info(
            "Rewriting unique_id %r → %r (entity_id %s)",
            registry_entry.unique_id,
            new_uid,
            registry_entry.entity_id,
        )
        return {"new_unique_id": new_uid}

    await er.async_migrate_entries(hass, entry.entry_id, _maybe_rewrite)
