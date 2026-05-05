"""Tests for capability JWT decoding and detection helpers."""

from datetime import datetime, timedelta
import json
from pathlib import Path

from custom_components.securitas.securitas_direct_new_api.client import SecuritasClient

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


class TestDetectPeri:
    def test_jwt_cap_signal(self):
        """Granvia (Spanish + peri) — JWT advertises PERI."""
        from custom_components.securitas.securitas_direct_new_api.capabilities import (
            detect_peri,
        )
        fixture = _load("spain_full_peri.json")
        cap_set = frozenset(fixture["decoded_jwt_body"]["installations"][0]["cap"])
        # No services / partitions data: JWT alone should suffice
        assert detect_peri(installation=None, services=[], capabilities=cap_set) is True

    def test_alarm_partition_signal(self):
        """Italy (SDVECU) — only the alarm-partition signal fires."""
        from custom_components.securitas.securitas_direct_new_api.capabilities import (
            detect_peri,
        )

        class FakeInstallation:
            alarm_partitions = [
                {"id": "01", "enterStates": ["01", "02"]},
                {"id": "02", "enterStates": ["01"]},
                {"id": "03", "enterStates": []},
            ]

        # No JWT cap, no services, but partition data present
        assert detect_peri(installation=FakeInstallation(), services=[], capabilities=frozenset()) is True

    def test_negative_when_no_signals(self):
        """Tetuan (Spanish, no peri) — all signals absent."""
        from custom_components.securitas.securitas_direct_new_api.capabilities import (
            detect_peri,
        )

        class FakeInstallation:
            alarm_partitions = []

        assert detect_peri(installation=FakeInstallation(), services=[], capabilities=frozenset(["ARM", "DARM", "ARMDAY"])) is False

    def test_active_peri_service_signal(self):
        """A service entry with request='PERI' and active=True → has peri."""
        from custom_components.securitas.securitas_direct_new_api.capabilities import (
            detect_peri,
        )
        from custom_components.securitas.securitas_direct_new_api.models import Service

        class FakeInstallation:
            alarm_partitions = []

        active_peri = Service(
            id=33, id_service=33, active=True, visible=True, bde=False, is_premium=False,
            cod_oper=False, total_device=0, request="PERI", multiple_req=False,
            num_devices_mr=0, attributes=[],
        )
        assert detect_peri(installation=FakeInstallation(), services=[active_peri], capabilities=frozenset()) is True

    def test_inactive_peri_service_does_not_signal(self):
        from custom_components.securitas.securitas_direct_new_api.capabilities import (
            detect_peri,
        )
        from custom_components.securitas.securitas_direct_new_api.models import Service

        class FakeInstallation:
            alarm_partitions = []

        inactive_peri = Service(
            id=33, id_service=33, active=False, visible=True, bde=False, is_premium=False,
            cod_oper=False, total_device=0, request="PERI", multiple_req=False,
            num_devices_mr=0, attributes=[],
        )
        assert detect_peri(installation=FakeInstallation(), services=[inactive_peri], capabilities=frozenset()) is False

    def test_sch_attr_signal(self):
        """Existing detection via SCH service attribute named PERI."""
        from custom_components.securitas.securitas_direct_new_api.capabilities import (
            detect_peri,
        )
        from custom_components.securitas.securitas_direct_new_api.models import Attribute, Service

        class FakeInstallation:
            alarm_partitions = []

        sch = Service(
            id=60, id_service=60, active=True, visible=True, bde=False, is_premium=False,
            cod_oper=False, total_device=0, request="SCH", multiple_req=False,
            num_devices_mr=0, attributes=[Attribute(name="PERI", value="PERIMETRAL", active=False)],
        )
        assert detect_peri(installation=FakeInstallation(), services=[sch], capabilities=frozenset()) is True


class TestDetectAnnex:
    def test_both_present(self):
        from custom_components.securitas.securitas_direct_new_api.capabilities import detect_annex
        assert detect_annex(frozenset(["ARMANNEX", "DARMANNEX", "ARM"])) is True

    def test_only_arm_annex(self):
        from custom_components.securitas.securitas_direct_new_api.capabilities import detect_annex
        assert detect_annex(frozenset(["ARMANNEX", "ARM"])) is False

    def test_neither(self):
        from custom_components.securitas.securitas_direct_new_api.capabilities import detect_annex
        assert detect_annex(frozenset(["ARM", "ARMDAY"])) is False
