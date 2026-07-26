"""One-way hashing for the local alarm/lock PIN (``CONF_CODE``).

The PIN is never sent to the Verisure/Securitas API — it only gates local
arm/disarm/lock actions inside Home Assistant (see ``_check_code`` in
``alarm_control_panel/_base.py`` and ``lock.py``). Storing it hashed means a
copy of ``entry.data``/``entry.options`` (config backups, support requests,
``.storage/core.config_entries``) no longer discloses it in plain text; only
verification is possible, never recovery.

Uses PBKDF2-HMAC-SHA256 from the stdlib rather than a dedicated password-
hashing library (bcrypt/argon2) so no extra pip dependency is added to the
HACS manifest for what is, cryptographically, a low-entropy 4-8 digit code.
"""

from __future__ import annotations

import hashlib
import hmac
import os

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 600_000
_SALT_BYTES = 16


def hash_pin(pin: str) -> str:
    """Hash *pin*, returning a self-describing string safe to persist.

    Format: ``pbkdf2_sha256$<iterations>$<salt-hex>$<hash-hex>``. Embedding
    the algorithm and iteration count lets a future bump to the iteration
    count verify old entries correctly without a migration step.
    """
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_pin(pin: str | None, encoded: str) -> bool:
    """Return True if *pin* matches the hash produced by ``hash_pin``.

    Callers are expected to already know a PIN is configured (i.e. only call
    this when ``encoded`` is non-empty) — this function does not special-case
    "no PIN configured"; see ``_check_code`` call sites.
    """
    if pin is None:
        return False
    try:
        algorithm, iterations_str, salt_hex, hash_hex = encoded.split("$")
    except ValueError:
        return False
    if algorithm != _ALGORITHM:
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256", pin.encode(), bytes.fromhex(salt_hex), int(iterations_str)
    )
    return hmac.compare_digest(derived, bytes.fromhex(hash_hex))
