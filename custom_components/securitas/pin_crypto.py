"""One-way hashing for the local alarm/lock PIN (``CONF_CODE``).

The PIN is never sent to the Verisure/Securitas API — it only gates local
arm/disarm/lock actions inside Home Assistant (see ``_check_code`` in
``alarm_control_panel/_base.py`` and ``lock.py``). Storing it hashed means a
copy of ``entry.data``/``entry.options`` (config backups, support requests,
``.storage/core.config_entries``) no longer discloses it in plain text; only
verification is possible, never recovery.

Uses PBKDF2-HMAC-SHA256 from the stdlib rather than a dedicated password-
hashing library. HA does ship bcrypt as a hard dependency, so that route is
available — we deliberately don't take it, to avoid resting the PIN format
on a transitive dep of core, for what is cryptographically a low-entropy
4-8 digit code either way.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 600_000
_SALT_BYTES = 16

# Ceiling on the iteration count read back out of a persisted hash. The count
# is embedded so that raising _ITERATIONS keeps old entries verifiable, so this
# has to leave generous headroom — but it can't be unbounded: verification runs
# on the event loop, and a corrupted or hand-edited entry carrying a huge count
# would otherwise hang every arm/disarm (or, past OpenSSL's own limit, raise
# OverflowError, which is not a ValueError and would escape the guard below).
_MAX_ITERATIONS = 10_000_000


def hash_pin(pin: str) -> str:
    """Hash *pin*, returning a self-describing string safe to persist.

    Format: ``pbkdf2_sha256$<iterations>$<salt-hex>$<hash-hex>``. Embedding
    the algorithm and iteration count lets a future bump to the iteration
    count verify old entries correctly without a migration step.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${salt.hex()}${derived.hex()}"


def encode_pin(pin: str | None) -> tuple[str | None, bool]:
    """Return the ``(CONF_CODE_HASH, CONF_CODE_IS_NUMERIC)`` pair to persist.

    The two keys are always written together: digit-ness has to be captured
    from the raw PIN here, because it can't be recovered from the hash
    afterwards. An empty or absent PIN yields ``(None, False)`` — cleared,
    not omitted, so the keys keep their meaning when ``entry.options``
    shadows ``entry.data``.
    """
    return (hash_pin(pin), pin.isdigit()) if pin else (None, False)


def verify_pin(pin: str | None, encoded: str | None) -> bool:
    """Return True if *pin* matches the hash produced by ``hash_pin``.

    A falsy *encoded* means no PIN is configured and returns False. That is
    only the absence of a match — deciding what "no PIN configured" *permits*
    is entity policy, and stays at the call sites (see ``_check_code`` in
    ``alarm_control_panel/_base.py``, which accepts any code in that case).

    Any unusable *encoded* value is rejected rather than raised on: a config
    entry that has been truncated or hand-edited should read as "wrong PIN"
    on the disarm path, not as an unhandled exception. Both the shape check
    and the field parsing are inside the guard — a string can split into
    four parts and still carry a non-hex salt or a non-numeric iteration
    count — or not be a string at all, if the entry was edited by hand.
    """
    if pin is None or not encoded:
        return False
    try:
        algorithm, iterations_str, salt_hex, hash_hex = encoded.split("$")
        if algorithm != _ALGORITHM:
            return False
        iterations = int(iterations_str)
        # Bound before deriving, never after — the point is to not do the work.
        if not 0 < iterations <= _MAX_ITERATIONS:
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256", pin.encode(), bytes.fromhex(salt_hex), iterations
        )
        expected = bytes.fromhex(hash_hex)
    except (AttributeError, TypeError, ValueError):
        return False
    return hmac.compare_digest(derived, expected)
