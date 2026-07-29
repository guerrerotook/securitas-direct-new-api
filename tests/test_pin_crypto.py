"""Tests for pin_crypto — PIN hashing and verification."""

import pytest

from custom_components.securitas.pin_crypto import hash_pin, verify_pin


def test_verify_accepts_matching_pin():
    encoded = hash_pin("1234")
    assert verify_pin("1234", encoded) is True


def test_verify_rejects_wrong_pin():
    encoded = hash_pin("1234")
    assert verify_pin("9999", encoded) is False


def test_verify_rejects_none_pin():
    encoded = hash_pin("1234")
    assert verify_pin(None, encoded) is False


def test_hash_is_salted_differently_each_time():
    """Two hashes of the same PIN must differ (random salt) but both verify."""
    first = hash_pin("1234")
    second = hash_pin("1234")
    assert first != second
    assert verify_pin("1234", first) is True
    assert verify_pin("1234", second) is True


def test_hash_is_not_recoverable_plaintext():
    """The encoded hash must never contain the raw PIN as a substring.

    The probe PIN is deliberately non-hex. A digit-only PIN like "1234" can
    turn up by chance inside the salt/digest hex — measured at ~1 run in 750,
    which is a flaky test rather than a real finding.
    """
    assert "syzygy" not in hash_pin("syzygy")


def test_verify_handles_malformed_encoded_gracefully():
    """A corrupt/foreign string should be rejected, not raise."""
    assert verify_pin("1234", "not-a-valid-hash") is False
    assert verify_pin("1234", "") is False


@pytest.mark.parametrize(
    "encoded",
    [
        "pbkdf2_sha256$600000$zz$aa",  # salt isn't hex
        "pbkdf2_sha256$600000$ab$zz",  # digest isn't hex
        "pbkdf2_sha256$600000$abc$abcd",  # odd-length hex
        "pbkdf2_sha256$notanint$ab$cd",  # iteration count isn't a number
    ],
    ids=["bad-salt", "bad-digest", "odd-length-hex", "bad-iterations"],
)
def test_verify_rejects_corrupt_fields_without_raising(encoded):
    """Damage *inside* a well-formed shape must be rejected, not raise.

    These split into four parts and carry the right algorithm tag, so they
    get past the shape check and reach the hex/int parsing. A hand-edited or
    truncated core.config_entries must not turn every disarm into an
    unhandled ValueError instead of a clean "wrong PIN".
    """
    assert verify_pin("1234", encoded) is False


def test_verify_rejects_unknown_algorithm_tag():
    encoded = hash_pin("1234")
    _algorithm, iterations, salt_hex, hash_hex = encoded.split("$")
    forged = f"bcrypt${iterations}${salt_hex}${hash_hex}"
    assert verify_pin("1234", forged) is False


def test_supports_non_numeric_pins():
    encoded = hash_pin("abcd")
    assert verify_pin("abcd", encoded) is True
    assert verify_pin("ABCD", encoded) is False
