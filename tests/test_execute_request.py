"""Tests for the generate_uuid utility function."""

from custom_components.securitas.verisure_owa_api.client import generate_uuid

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
