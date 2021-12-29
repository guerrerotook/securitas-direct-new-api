"""Securitas Direct API implementation."""
from datetime import datetime
import json
import logging
from typing import List, Tuple

import requests
from requests.adapters import HTTPAdapter
from requests.models import Response
from urllib3 import Retry

from .dataTypes import ArmStatus, ArmType, CheckAlarmStatus, DisarmStatus, Installation
from .domains import ApiDomains

_LOGGER = logging.getLogger(__name__)


class ApiManager:
    """Securitas Direct API."""

    def __init__(self, username, password, country, language):
        """Create the object."""
        self.username = username
        self.password = password
        self.country = country
        self.language = language
        self.api_url = ApiDomains().get_url(language=language)
        self.session = None
        self.authentication_token = None
        self.jar = requests.cookies.RequestsCookieJar()

    def _executeRequest(self, content) -> Response:
        headers = None
        if self.authentication_token is not None:
            authorization_value = {
                "user": self.username,
                "id": self._generateId(),
                "country": self.country,
                "lang": self.language,
                "callby": "OWP_10",
                "hash": self.authentication_token,
            }
            headers = {"auth": json.dumps(authorization_value)}

        _LOGGER.debug(content)
        response: Response = self._createRequestSession().post(
            self.api_url, headers=headers, json=content, cookies=self.jar
        )
        _LOGGER.debug(response.text)
        errorLogin: bool = self._checkErrros(response.text)
        if errorLogin:
            return self._executeRequest(content)

        return response

    def _createRequestSession(self) -> requests.Session:
        if not self.session:
            self.session = requests.session()
            self.session.mount(
                "https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1))
            )

        return self.session

    def _generateId(self) -> str:
        current: datetime = datetime.now()
        return (
            "OWP_______________"
            + self.username
            + "_______________"
            + str(current.year)
            + str(current.month)
            + str(current.day)
            + str(current.hour)
            + str(current.minute)
            + str(current.microsecond)
        )

    def _checkErrros(self, value: str) -> bool:
        if value is not None:
            response = json.loads(value)
            if "errors" in response:
                for errorItem in response["errors"]:
                    if "message" in errorItem:
                        if errorItem["message"] == "Invalid token: Expired":
                            self.authentication_token = None
                            _LOGGER.info("Login is expired. Login again.")
                            return self.login()[0]
                        else:
                            _LOGGER.error(errorItem["message"])
        return False

    def logout(self):
        """Logout."""
        content = {
            "operationName": "Logout",
            "variables": {},
            "query": "mutation Logout {\n  xSLogout\n}\n",
        }
        self._executeRequest(content)

    def login(self) -> Tuple[bool, str]:
        """Login."""
        content = {
            "operationName": "LoginToken",
            "variables": {
                "id": self._generateId(),
                "country": self.country,
                "callby": "OWP_10",
                "lang": self.language,
                "user": self.username,
                "password": self.password,
            },
            "query": "mutation LoginToken($user: String!, $password: String!, $id: String!, $country: String!, $lang: String!, $callby: String!) {\n  xSLoginToken(user: $user, password: $password, id: $id, country: $country, lang: $lang, callby: $callby) {\n    res\n    msg\n    hash\n    lang\n    legals\n    mainUser\n    changePassword\n  }\n}\n",
        }
        response = self._executeRequest(content)
        result_json = json.loads(response.text)
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return (False, error_message)
        else:
            self.authentication_token = result_json["data"]["xSLoginToken"]["hash"]
            return (True, "None")

    def listInstallations(self) -> List[Installation]:
        """List securitas direct installations."""
        content = {
            "operationName": "InstallationList",
            "query": "query InstallationList {\n  xSInstallations {\n    installations {\n      numinst\n      alias\n      panel\n      type\n      name\n      surname\n      address\n      city\n      postcode\n      province\n      email\n      phone\n    }\n  }\n}\n",
        }
        response = self._executeRequest(content)
        result_json = json.loads(response.text)
        try:
            result: List[Installation] = []
            raw_Installations = result_json["data"]["xSInstallations"]["installations"]
            for item in raw_Installations:
                InstallationItem: Installation = Installation(
                    int(item["numinst"]),
                    item["alias"],
                    item["panel"],
                    item["type"],
                    item["name"],
                    item["surname"],
                    item["address"],
                    item["city"],
                    item["postcode"],
                    item["province"],
                    item["email"],
                    item["phone"],
                )
                result.append(InstallationItem)
        except (KeyError, TypeError):
            result = []
        return result

    def checkAlarm(self, Installation: Installation) -> str:
        """Check status of the alarm."""
        content = {
            "operationName": "CheckAlarm",
            "variables": {
                "numinst": str(Installation.number),
                "panel": Installation.panel,
            },
            "query": "query CheckAlarm($numinst: String!, $panel: String!) {\n  xSCheckAlarm(numinst: $numinst, panel: $panel) {\n    res\n    msg\n    referenceId\n  }\n}\n",
        }
        response = self._executeRequest(content)
        result_json = json.loads(response.text)
        try:
            return result_json["data"]["xSCheckAlarm"]["referenceId"]
        except (KeyError, TypeError):
            return None

    def checkAlarmStatus(
        self, Installation: Installation, referenceId: str
    ) -> CheckAlarmStatus:
        """Check status of the operation check alarm."""
        content = {
            "operationName": "CheckAlarmStatus",
            "variables": {
                "numinst": str(Installation.number),
                "panel": Installation.panel,
                "referenceId": referenceId,
                "idService": "11",
                "counter": 2,
            },
            "query": "query CheckAlarmStatus($numinst: String!, $idService: String!, $panel: String!, $referenceId: String!) {\n  xSCheckAlarmStatus(numinst: $numinst, idService: $idService, panel: $panel, referenceId: $referenceId) {\n    res\n    msg\n    status\n    numinst\n    protomResponse\n    protomResponseDate\n  }\n}\n",
        }
        response = self._executeRequest(content)
        result_json = json.loads(response.text)
        try:
            raw_data = result_json["data"]["xSCheckAlarmStatus"]
            return CheckAlarmStatus(
                raw_data["res"],
                raw_data["msg"],
                raw_data["status"],
                raw_data["numinst"],
                raw_data["protomResponse"],
                raw_data["protomResponseDate"],
            )
        except (KeyError, TypeError):
            return None

    def armAlarm(
        self, Installation: Installation, mode: str, currentStatus: str
    ) -> Tuple[bool, str]:
        """Arms the alarm in the specified mode."""
        content = {
            "operationName": "xSArmPanel",
            "variables": {
                "request": mode,
                "numinst": str(Installation.number),
                "panel": Installation.panel,
                "currentStatus": currentStatus,
            },
            "query": "mutation xSArmPanel($numinst: String!, $request: ArmCodeRequest!, $panel: String!, $pin: String, $currentStatus: String) {\n  xSArmPanel(numinst: $numinst, request: $request, panel: $panel, pin: $pin, currentStatus: $currentStatus) {\n    res\n    msg\n    referenceId\n  }\n}\n",
        }
        response = self._executeRequest(content)
        result_json = json.loads(response.text)
        try:
            if result_json["data"]["xSArmPanel"]["res"] == "OK":
                return (True, result_json["data"]["xSArmPanel"]["referenceId"])
            else:
                return (False, result_json["data"]["xSArmPanel"]["msg"])
        except (KeyError, TypeError):
            return (False, "Unknown error.")

    def checkArmStatus(
        self,
        Installation: Installation,
        referenceId: str,
        mode: str,
        counter: int,
        currentStatus: str,
    ) -> ArmStatus:
        """Check progress of the alarm."""
        content = {
            "operationName": "ArmStatus",
            "variables": {
                "request": mode,
                "numinst": str(Installation.number),
                "panel": Installation.panel,
                "currentStatus": currentStatus,
                "referenceId": referenceId,
                "counter": counter,
            },
            "query": "query ArmStatus($numinst: String!, $request: ArmCodeRequest, $panel: String!, $referenceId: String!, $counter: Int!) {\n  xSArmStatus(numinst: $numinst, panel: $panel, referenceId: $referenceId, counter: $counter, request: $request) {\n    res\n    msg\n    status\n    protomResponse\n    protomResponseDate\n    numinst\n    requestId\n    error {\n      code\n      type\n      allowForcing\n      exceptionsNumber\n      referenceId\n    }\n  }\n}\n",
        }
        response = self._executeRequest(content)
        result_json = json.loads(response.text)
        try:
            raw_data = result_json["data"]["xSArmStatus"]
            return ArmStatus(
                raw_data["res"],
                raw_data["msg"],
                raw_data["status"],
                raw_data["numinst"],
                raw_data["protomResponse"],
                raw_data["protomResponseDate"],
                raw_data["requestId"],
                raw_data["error"],
            )
        except (KeyError, TypeError):
            return None

    def disarmAlarm(
        self, Installation: Installation, currentStatus: str
    ) -> Tuple[bool, str]:
        """Disarm the alarm."""
        content = {
            "operationName": "xSDisarmPanel",
            "variables": {
                "request": "DARM1",
                "numinst": str(Installation.number),
                "panel": Installation.panel,
                "currentStatus": currentStatus,
            },
            "query": "mutation xSDisarmPanel($numinst: String!, $request: DisarmCodeRequest!, $panel: String!, $pin: String) {\n  xSDisarmPanel(numinst: $numinst, request: $request, panel: $panel, pin: $pin) {\n    res\n    msg\n    referenceId\n  }\n}\n",
        }
        response = self._executeRequest(content)
        result_json = json.loads(response.text)
        try:
            if result_json["data"]["xSDisarmPanel"]["res"] == "OK":
                return (True, result_json["data"]["xSDisarmPanel"]["referenceId"])
            else:
                return (False, result_json["data"]["xSDisarmPanel"]["msg"])
        except (KeyError, TypeError):
            return (False, "Disarm error.")

    def checkDisarmStatus(
        self,
        Installation: Installation,
        referenceId: str,
        armType: ArmType,
        counter: int,
        currentStatus: str,
    ) -> DisarmStatus:
        """Check progress of the alarm."""
        content = {
            "operationName": "DisarmStatus",
            "variables": {
                "request": "DARM" + str(armType.value),
                "numinst": str(Installation.number),
                "panel": Installation.panel,
                "currentStatus": currentStatus,
                "referenceId": referenceId,
                "counter": counter,
            },
            "query": "query DisarmStatus($numinst: String!, $panel: String!, $referenceId: String!, $counter: Int!, $request: DisarmCodeRequest) {\n  xSDisarmStatus(numinst: $numinst, panel: $panel, referenceId: $referenceId, counter: $counter, request: $request) {\n    res\n    msg\n    status\n    protomResponse\n    protomResponseDate\n    numinst\n    requestId\n    error {\n      code\n      type\n      allowForcing\n      exceptionsNumber\n      referenceId\n    }\n  }\n}\n",
        }
        response = self._executeRequest(content)
        result_json = json.loads(response.text)
        try:
            raw_data = result_json["data"]["xSDisarmStatus"]
            return DisarmStatus(
                raw_data["error"],
                raw_data["msg"],
                raw_data["numinst"],
                raw_data["protomResponse"],
                raw_data["protomResponseDate"],
                raw_data["requestId"],
                raw_data["res"],
                raw_data["status"],
            )
        except (KeyError, TypeError):
            return None
