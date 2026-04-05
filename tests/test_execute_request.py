"""Tests for generate_uuid and generate_device_id utility functions."""

from custom_components.securitas.securitas_direct_new_api.client import (
    generate_device_id,
    generate_uuid,
)


# ── generate_uuid tests ──────────────────────────────────────────────────────


class TestGenerateUuid:
    """Tests for the generate_uuid module-level function."""

    def test_returns_16_character_string(self):
        """UUID is exactly 16 characters long."""
        result = generate_uuid()
        assert len(result) == 16

    def test_contains_no_hyphens(self):
        """UUID contains no hyphens."""
        result = generate_uuid()
        assert "-" not in result

    def test_two_calls_return_different_values(self):
        """Two calls return different UUIDs."""
        a = generate_uuid()
        b = generate_uuid()
        assert a != b


# ── generate_device_id tests ────────────────────────────────────────────────


class TestGenerateDeviceId:
    """Tests for the generate_device_id module-level function."""

    def test_contains_apa91b_marker(self):
        """Device ID contains the ':APA91b' marker."""
        result = generate_device_id("ES")
        assert ":APA91b" in result

    def test_returns_expected_length(self):
        """Device ID is 163 chars: 22 (token_urlsafe(16)) + 7 (':APA91b') + 134."""
        result = generate_device_id("ES")
        assert len(result) == 22 + 7 + 134

    def test_two_calls_return_different_values(self):
        """Two calls return different device IDs."""
        a = generate_device_id("ES")
        b = generate_device_id("ES")
        assert a != b
