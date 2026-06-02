"""Auth domain: login, refresh, logout, validate-device (2FA), send-otp."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ..exceptions import (
    AccountBlockedError,
    AuthenticationError,
    TwoFactorRequiredError,
    VerisureOwaError,
)
from ..graphql_queries import (
    LOGIN_TOKEN_MUTATION,
    REFRESH_LOGIN_MUTATION,
    SEND_OTP_MUTATION,
    VALIDATE_DEVICE_MUTATION,
)
from ..models import OtpPhone
from ._base import API_CALLBY, _ClientBase

_LOGGER = logging.getLogger(__name__)


class _AuthMixin(_ClientBase):
    """Login, refresh, logout, and 2FA validation."""

    async def login(self) -> None:
        """Login to the Verisure OWA API and set auth tokens.

        Once a refresh token has been minted the password is scrubbed from
        storage (v5.1.0). Sending an empty password to the API only earns a
        credential error and burns an attempt toward Verisure's 3-strikes
        account lock, so refuse it here and signal reauth instead — this guards
        every fallback path that reaches login() after a rejected refresh (#499).
        """
        if not self.password:
            raise AuthenticationError(
                "Cannot login: no password available (refresh token rejected). "
                "Re-authentication required."
            )
        content = {
            "operationName": "mkLoginToken",
            "variables": {
                "user": self.username,
                "password": self.password,
                "id": self._generate_id(),
                "country": self.country,
                "callby": API_CALLBY,
                "lang": self.language,
                "idDevice": self.device_id,
                "idDeviceIndigitall": self.id_device_indigitall,
                "deviceType": "",
                "deviceVersion": self.device_version,
                "deviceResolution": "",
                "deviceName": self.device_name,
                "deviceBrand": self.device_brand,
                "deviceOsVersion": self.device_os_version,
                "uuid": self.uuid,
            },
            "query": LOGIN_TOKEN_MUTATION,
        }

        response: dict[str, Any] = {}
        try:
            response = await self._execute_raw(content, "mkLoginToken")
        except VerisureOwaError as err:
            result_json: dict[str, Any] | None = err.response_body
            if result_json is not None:
                # Check for account-blocked error (60052)
                if self._is_account_blocked(result_json):
                    _new = AccountBlockedError(err.message, http_status=err.http_status)
                    _new.response_body = result_json
                    raise _new from err
                if result_json.get("data"):
                    data = result_json["data"]
                    if data.get("xSLoginToken"):
                        if data["xSLoginToken"].get("needDeviceAuthorization"):
                            _new = TwoFactorRequiredError(
                                err.message, http_status=err.http_status
                            )
                            _new.response_body = result_json
                            raise _new from err
                    _new = AuthenticationError(err.message, http_status=err.http_status)
                    _new.response_body = result_json
                    raise _new from err
                _new = AuthenticationError(err.message, http_status=err.http_status)
                _new.response_body = result_json
                raise _new from err
            raise

        if "errors" in response:
            _LOGGER.error("Login error %s", response["errors"][0]["message"])
            _new_err = AuthenticationError(response["errors"][0]["message"])
            _new_err.response_body = response
            raise _new_err

        # Check if 2FA is required even on successful response
        login_data = self._extract_response_data(response, "xSLoginToken")
        if login_data.get("needDeviceAuthorization", False):
            _new_err = TwoFactorRequiredError("2FA authentication required")
            _new_err.response_body = response
            raise _new_err

        if login_data.get("refreshToken"):
            self._update_refresh_token(login_data["refreshToken"])

        if login_data["hash"] is not None:
            self.authentication_token = login_data["hash"]
            self._register_secret("auth_token", self.authentication_token)
            self.login_timestamp = int(datetime.now().timestamp() * 1000)

            if self._decode_auth_token(self.authentication_token) is None:
                raise VerisureOwaError("Failed to decode authentication token")
        else:
            self.login_timestamp = int(datetime.now().timestamp() * 1000)

        self.note_auth_success()

    async def refresh_token(self) -> bool:
        """Refresh the authentication token. Returns True on success."""
        content = {
            "operationName": "RefreshLogin",
            "variables": {
                "refreshToken": self.refresh_token_value,
                "id": self._generate_id(),
                "uuid": self.uuid,
                "country": self.country,
                "lang": self.language,
                "callby": API_CALLBY,
                "idDevice": self.device_id,
                "idDeviceIndigitall": self.id_device_indigitall,
                "deviceType": "",
                "deviceVersion": self.device_version,
                "deviceResolution": "",
                "deviceName": self.device_name,
                "deviceBrand": self.device_brand,
                "deviceOsVersion": self.device_os_version,
            },
            "query": REFRESH_LOGIN_MUTATION,
        }
        response = await self._execute_raw(content, "RefreshLogin")

        refresh_data = self._extract_response_data(response, "xSRefreshLogin")

        if refresh_data.get("res") != "OK":
            return False

        if refresh_data.get("hash"):
            self.authentication_token = refresh_data["hash"]
            self._register_secret("auth_token", self.authentication_token)
            if self._decode_auth_token(self.authentication_token) is None:
                return False
            self.login_timestamp = int(datetime.now().timestamp() * 1000)
        else:
            return False

        if refresh_data.get("refreshToken"):
            self._update_refresh_token(refresh_data["refreshToken"])

        self.note_auth_success()
        return True

    async def logout(self) -> None:
        """Logout and clear authentication state."""
        content = {
            "operationName": "Logout",
            "variables": {},
            "query": "mutation Logout {\n  xSLogout\n}\n",
        }
        try:
            await self._execute_raw(content, "Logout")
        finally:
            self.authentication_token = None
            self.refresh_token_value = ""
            self._authentication_token_exp = datetime.min
            self.login_timestamp = 0

    async def validate_device(
        self, otp_succeed: bool, auth_otp_hash: str, sms_code: str
    ) -> tuple[str | None, list[OtpPhone] | None]:
        """Validate the device with 2FA."""
        content = {
            "operationName": "mkValidateDevice",
            "variables": {
                "idDevice": self.device_id,
                "idDeviceIndigitall": self.id_device_indigitall,
                "uuid": self.uuid,
                "deviceName": self.device_name,
                "deviceBrand": self.device_brand,
                "deviceOsVersion": self.device_os_version,
                "deviceVersion": self.device_version,
            },
            "query": VALIDATE_DEVICE_MUTATION,
        }

        if otp_succeed:
            self.authentication_otp_challenge_value = (auth_otp_hash, sms_code)
            self._register_secret("otp_hash", auth_otp_hash)
            self._register_secret("otp_token", sms_code)

        try:
            response = await self._execute_raw(content, "mkValidateDevice")
        except VerisureOwaError as err:
            # Always invalidate the (hash, code) pair on failure so a wrong
            # OTP cannot be replayed in the next request's headers; the user
            # must request a fresh OTP via send_otp.
            self.authentication_otp_challenge_value = None
            if err.response_body is not None:
                try:
                    error_data = err.response_body["errors"][0]["data"]
                    if "auth-otp-hash" in error_data or "auth-phones" in error_data:
                        return self._extract_otp_data(error_data)
                except (KeyError, IndexError, TypeError):
                    pass
            raise
        self.authentication_otp_challenge_value = None

        if "errors" in response and response["errors"][0]["message"] == "Unauthorized":
            return self._extract_otp_data(response["errors"][0]["data"])

        validate_data = self._extract_response_data(response, "xSValidateDevice")
        self.authentication_token = validate_data["hash"]
        self._register_secret("auth_token", self.authentication_token)
        self._decode_auth_token(self.authentication_token)
        if validate_data.get("refreshToken"):
            self._update_refresh_token(validate_data["refreshToken"])
        return (None, None)

    async def send_otp(self, device_id: int, auth_otp_hash: str) -> str:
        """Send the OTP device challenge."""
        content = {
            "operationName": "mkSendOTP",
            "variables": {
                "recordId": device_id,
                "otpHash": auth_otp_hash,
            },
            "query": SEND_OTP_MUTATION,
        }
        response = await self._execute_raw(content, "mkSendOTP")

        otp_data = self._extract_response_data(response, "xSSendOtp")
        return otp_data["res"]
