"""Tests for capability JWT decoding and detection helpers."""

from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest

from custom_components.securitas.securitas_direct_new_api.client import SecuritasClient
from tests.mock_graphql import make_jwt

FIXTURES = Path(__file__).parent / "fixtures" / "capability_jwts"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestGetSupportedCommands:
    def test_returns_cap_set_from_decoded_jwt(self):
        """JWT body's installations[].cap is exposed as a frozenset on the client."""
        fixture = _load("vatrinus_uk_annex.json")
        body = fixture["decoded_jwt_body"]
        # We don't need a real JWT — we directly populate the storage with
        # the new 3-tuple shape that _ensure_capabilities will produce.
        client = SecuritasClient.__new__(SecuritasClient)  # bypass __init__
        client._capabilities = {
            "INST_VATRINUS": (
                "fake_jwt_string",
                datetime.now() + timedelta(hours=1),
                frozenset(body["installations"][0]["cap"]),
            ),
        }

        caps = client.get_supported_commands("INST_VATRINUS")
        assert isinstance(caps, frozenset)
        assert "ARMANNEX" in caps
        assert "DARMANNEX" in caps
        assert "ARMDAY" in caps
        assert "ARMNIGHT" in caps

    def test_returns_empty_for_unknown_install(self):
        client = SecuritasClient.__new__(SecuritasClient)
        client._capabilities = {}
        assert client.get_supported_commands("DOES_NOT_EXIST") == frozenset()

    def test_returns_empty_for_legacy_2tuple_storage(self):
        """If a legacy 2-tuple is somehow in storage, return empty rather than crash."""
        client = SecuritasClient.__new__(SecuritasClient)
        client._capabilities = {
            "LEGACY": ("fake_jwt", datetime.now()),  # 2-tuple, no cap set
        }
        assert client.get_supported_commands("LEGACY") == frozenset()
