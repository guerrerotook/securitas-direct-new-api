"""Tests for SecuritasClient lock methods — get_lock_modes, get_lock_config, change_lock_mode."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from custom_components.securitas.securitas_direct_new_api.client import (
    SMARTLOCK_DEVICE_ID,
    SMARTLOCK_DEVICE_TYPE,
    SecuritasClient,
)
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    OperationTimeoutError,
)
from custom_components.securitas.securitas_direct_new_api.http_transport import (
    HttpTransport,
)
from custom_components.securitas.securitas_direct_new_api.models import (
    Installation,
    SmartLock,
    SmartLockMode,
    SmartLockModeStatus,
)

pytestmark = pytest.mark.asyncio

# ── JWT helpers ──────────────────────────────────────────────────────────────

SECRET = "test-secret"


def make_jwt(exp_minutes: int = 15, **extra_claims) -> str:
    """Create a real HS256 JWT with a known expiry."""
    exp = datetime.now(tz=timezone.utc) + timedelta(minutes=exp_minutes)
    payload = {"exp": exp, "sub": "test-user", **extra_claims}
    return jwt.encode(payload, SECRET, algorithm="HS256")


FAKE_JWT = make_jwt(exp_minutes=15)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_installation(**overrides) -> Installation:
    """Factory for Installation with sensible defaults."""
    defaults = {
        "number": "123456",
        "alias": "Home",
        "panel": "SDVFAST",
        "type": "PLUS",
        "name": "John",
        "last_name": "Doe",
        "address": "123 St",
        "city": "Madrid",
        "postal_code": "28001",
        "province": "Madrid",
        "email": "test@example.com",
        "phone": "555-1234",
    }
    defaults.update(overrides)
    return Installation(**defaults)


def _pre_auth(client: SecuritasClient) -> None:
    """Set up a valid auth token so _ensure_auth is a no-op."""
    client.authentication_token = FAKE_JWT
    client._authentication_token_exp = datetime.now() + timedelta(hours=1)
    # Stub get_services to avoid NotImplementedError on _ensure_capabilities
    client.get_services = AsyncMock(return_value=[])


# ── Response builders ────────────────────────────────────────────────────────


def lock_mode_response(
    *,
    res: str = "OK",
    smartlock_info: list[dict] | None = None,
) -> dict:
    """Build a mock xSGetLockCurrentMode response."""
    return {
        "data": {
            "xSGetLockCurrentMode": {
                "res": res,
                "smartlockInfo": smartlock_info,
            }
        }
    }


def smartlock_config_response(
    *,
    res: str = "OK",
    device_id: str = "1",
    reference_id: str = "",
    zone_id: str = "Z1",
    serial_number: str = "SN001",
    family: str = "smartlock",
    label: str = "Front Door",
    features: dict | None = None,
) -> dict:
    """Build a mock xSGetSmartlockConfig response."""
    return {
        "data": {
            "xSGetSmartlockConfig": {
                "res": res,
                "deviceId": device_id,
                "referenceId": reference_id,
                "zoneId": zone_id,
                "serialNumber": serial_number,
                "family": family,
                "label": label,
                "features": features
                or {
                    "holdBackLatchTime": 5,
                    "calibrationType": 1,
                    "autolock": {"active": True, "timeout": 30},
                },
            }
        }
    }


def danalock_submit_response(reference_id: str = "ref-dana-001") -> dict:
    """Build a mock xSGetDanalockConfig response."""
    return {
        "data": {
            "xSGetDanalockConfig": {
                "res": "OK",
                "msg": "",
                "referenceId": reference_id,
            }
        }
    }


def danalock_status_response(
    *,
    res: str = "OK",
    msg: str = "",
    device_number: str = "1",
    features: dict | None = None,
) -> dict:
    """Build a mock xSGetDanalockConfigStatus response."""
    return {
        "data": {
            "xSGetDanalockConfigStatus": {
                "res": res,
                "msg": msg,
                "deviceNumber": device_number,
                "features": features
                or {
                    "holdBackLatchTime": 5,
                    "calibrationType": 1,
                    "autolock": {"active": True, "timeout": 30},
                },
            }
        }
    }


def change_lock_submit_response(reference_id: str = "ref-lock-001") -> dict:
    """Build a mock xSChangeSmartlockMode response."""
    return {
        "data": {
            "xSChangeSmartlockMode": {
                "res": "OK",
                "msg": "",
                "referenceId": reference_id,
            }
        }
    }


def change_lock_status_response(
    *,
    res: str = "OK",
    msg: str = "",
    protom_response: str = "L",
    status: str = "LOCKED",
) -> dict:
    """Build a mock xSChangeSmartlockModeStatus response."""
    return {
        "data": {
            "xSChangeSmartlockModeStatus": {
                "res": res,
                "msg": msg,
                "protomResponse": protom_response,
                "status": status,
            }
        }
    }


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def transport():
    """Create a mock HttpTransport."""
    mock = MagicMock(spec=HttpTransport)
    mock.execute = AsyncMock()
    return mock


@pytest.fixture
def client(transport):
    """Create a SecuritasClient with test credentials, mocked transport, fast polling."""
    c = SecuritasClient(
        transport=transport,
        country="ES",
        language="es",
        username="test@example.com",
        password="test-password",
        device_id="test-device-id",
        uuid="test-uuid",
        id_device_indigitall="test-indigitall",
        poll_delay=0.0,
        poll_timeout=2.0,
    )
    _pre_auth(c)
    return c


# ── get_lock_modes tests ────────────────────────────────────────────────────


class TestGetLockModes:
    async def test_returns_list_of_smart_lock_mode(self, client, transport):
        """Successful call returns a list of SmartLockMode instances."""
        transport.execute.return_value = lock_mode_response(
            res="OK",
            smartlock_info=[
                {
                    "lockStatus": "LOCKED",
                    "deviceId": "1",
                    "statusTimestamp": "2024-01-01 12:00:00",
                },
                {
                    "lockStatus": "UNLOCKED",
                    "deviceId": "2",
                    "statusTimestamp": "2024-01-01 12:05:00",
                },
            ],
        )

        inst = _make_installation()
        result = await client.get_lock_modes(inst)

        assert len(result) == 2
        assert all(isinstance(m, SmartLockMode) for m in result)
        assert result[0].lock_status == "LOCKED"
        assert result[0].device_id == "1"
        assert result[1].lock_status == "UNLOCKED"
        assert result[1].device_id == "2"

    async def test_empty_smartlock_info(self, client, transport):
        """Returns empty list when smartlockInfo is None."""
        transport.execute.return_value = lock_mode_response(
            res="OK",
            smartlock_info=None,
        )

        inst = _make_installation()
        result = await client.get_lock_modes(inst)

        assert result == []

    async def test_variables_include_numinst(self, client, transport):
        """Verifies numinst is sent in the request variables."""
        transport.execute.return_value = lock_mode_response(res="OK", smartlock_info=[])

        inst = _make_installation(number="999888")
        await client.get_lock_modes(inst)

        call_args = transport.execute.call_args[0][0]
        assert call_args["variables"]["numinst"] == "999888"


# ── get_lock_config tests ───────────────────────────────────────────────────


class TestGetLockConfig:
    async def test_smartlock_fast_path_success(self, client, transport):
        """Smartlock config query returns OK -- returns SmartLock directly."""
        transport.execute.return_value = smartlock_config_response(
            res="OK",
            zone_id="Z1",
            serial_number="SN001",
            family="smartlock",
            label="Front Door",
        )

        inst = _make_installation()
        result = await client.get_lock_config(inst)

        assert isinstance(result, SmartLock)
        assert result.res == "OK"
        assert result.zone_id == "Z1"
        assert result.serial_number == "SN001"
        assert result.family == "smartlock"
        assert result.label == "Front Door"
        # Only one transport call (no polling needed)
        assert transport.execute.call_count == 1

    async def test_danalock_fallback(self, client, transport):
        """Smartlock fails, danalock polls to success."""
        transport.execute.side_effect = [
            # 1. Smartlock config returns error (non-OK res)
            smartlock_config_response(res="ERROR"),
            # 2. Danalock submit returns referenceId
            danalock_submit_response("ref-dana-001"),
            # 3. Danalock status poll: WAIT
            danalock_status_response(res="WAIT"),
            # 4. Danalock status poll: OK
            danalock_status_response(
                res="OK",
                device_number="1",
                features={
                    "holdBackLatchTime": 5,
                    "calibrationType": 1,
                    "autolock": {"active": True, "timeout": 30},
                },
            ),
        ]

        inst = _make_installation()
        result = await client.get_lock_config(inst)

        assert isinstance(result, SmartLock)
        assert result.device_id == "1"
        assert result.features is not None
        assert result.features.hold_back_latch_time == 5

    async def test_both_fail_returns_empty_smartlock(self, client, transport):
        """Both smartlock and danalock fail, returns empty SmartLock()."""
        transport.execute.side_effect = [
            # 1. Smartlock returns error
            smartlock_config_response(res="ERROR"),
            # 2. Danalock submit returns referenceId
            danalock_submit_response("ref-dana-002"),
            # 3. Danalock status returns error
            danalock_status_response(res="ERROR", msg="Device not found"),
        ]

        inst = _make_installation()
        result = await client.get_lock_config(inst)

        assert isinstance(result, SmartLock)
        # Empty SmartLock has None res and empty strings
        assert result.res is None
        assert result.device_id == ""

    async def test_smartlock_exception_falls_back_to_danalock(self, client, transport):
        """If smartlock query raises an exception, falls back to danalock."""
        from custom_components.securitas.securitas_direct_new_api.exceptions import (
            SecuritasDirectError,
        )

        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SecuritasDirectError("Smartlock not supported")
            if call_count == 2:
                return danalock_submit_response("ref-dana-003")
            if call_count == 3:
                return danalock_status_response(res="OK", device_number="2")
            return danalock_status_response(res="OK")

        transport.execute.side_effect = _side_effect

        inst = _make_installation()
        result = await client.get_lock_config(inst)

        assert isinstance(result, SmartLock)
        assert result.device_id == "2"

    async def test_custom_device_id(self, client, transport):
        """Passes custom device_id to query variables."""
        transport.execute.return_value = smartlock_config_response(res="OK")

        inst = _make_installation()
        await client.get_lock_config(inst, device_id="5")

        call_args = transport.execute.call_args[0][0]
        assert call_args["variables"]["deviceId"] == "5"


# ── change_lock_mode tests ──────────────────────────────────────────────────


class TestChangeLockMode:
    async def test_success_with_polling(self, client, transport):
        """Submit + poll through WAIT states, returns SmartLockModeStatus."""
        transport.execute.side_effect = [
            # 1. Submit: xSChangeSmartlockMode
            change_lock_submit_response("ref-lock-001"),
            # 2. Poll: WAIT
            change_lock_status_response(res="WAIT"),
            # 3. Poll: OK
            change_lock_status_response(
                res="OK",
                protom_response="L",
                status="LOCKED",
            ),
        ]

        inst = _make_installation()
        result = await client.change_lock_mode(inst, lock=True)

        assert isinstance(result, SmartLockModeStatus)
        assert result.protom_response == "L"
        assert result.status == "LOCKED"
        # protom_response should be updated on the client
        assert client.protom_response == "L"

    async def test_timeout(self, client, transport):
        """Raises OperationTimeoutError when poll never completes."""
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return change_lock_submit_response("ref-lock-002")
            return change_lock_status_response(res="WAIT")

        transport.execute.side_effect = _side_effect

        inst = _make_installation()
        client.poll_timeout = 0.1

        with pytest.raises(OperationTimeoutError):
            await client.change_lock_mode(inst, lock=True)

    async def test_unlock_sends_lock_false(self, client, transport):
        """lock=False is passed correctly in the submit variables."""
        transport.execute.side_effect = [
            change_lock_submit_response("ref-lock-003"),
            change_lock_status_response(
                res="OK", protom_response="U", status="UNLOCKED"
            ),
        ]

        inst = _make_installation()
        await client.change_lock_mode(inst, lock=False)

        # Check the submit call includes lock=False
        submit_call = transport.execute.call_args_list[0]
        content = submit_call[0][0]
        assert content["variables"]["lock"] is False
        assert content["variables"]["deviceType"] == SMARTLOCK_DEVICE_TYPE
        assert content["variables"]["deviceId"] == SMARTLOCK_DEVICE_ID

    async def test_custom_device_id(self, client, transport):
        """Custom device_id is passed in submit and poll variables."""
        transport.execute.side_effect = [
            change_lock_submit_response("ref-lock-004"),
            change_lock_status_response(res="OK", protom_response="L", status="LOCKED"),
        ]

        inst = _make_installation()
        await client.change_lock_mode(inst, lock=True, device_id="3")

        # Check submit call
        submit_call = transport.execute.call_args_list[0]
        submit_content = submit_call[0][0]
        assert submit_content["variables"]["deviceId"] == "3"

        # Check poll call
        poll_call = transport.execute.call_args_list[1]
        poll_content = poll_call[0][0]
        assert poll_content["variables"]["deviceId"] == "3"
