from urllib3 import Retry
from requests.sessions import session
from requests.models import Response
from requests.adapters import HTTPAdapter
from datetime import date
import json
import logging
import dataTypes
from datetime import datetime
from time import time
import requests
from typing import Any, List
from dataTypes import instalation, CheckAlarmStatus

from http.client import HTTPConnection, NotConnected  # py3

log = logging.getLogger('urllib3')
log.setLevel(logging.DEBUG)

# logging from urllib3 to console
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
log.addHandler(ch)

# print statements from `http.client.HTTPConnection` to console/stdout
HTTPConnection.debuglevel = 1


API_URL = "https://customers.securitasdirect.es/owa-api/graphql"


class ApiManager:
    def __init__(self, username, password, country, language):
        self.username = username
        self.password = password
        self.country = country
        self.language = language
        self.session = None
        self.authentication_token = None
        self.jar = requests.cookies.RequestsCookieJar()

    def executeRequest(self, content) -> Response:
        headers = None
        if self.authentication_token is not None:
            authorization_value = {
                "user": self.username,
                "id": self.generateId(),
                "country": self.country,
                "lang": self.language,
                "callby": "OWP_10",
                "hash": self.authentication_token
            }
            headers = {'auth': json.dumps(authorization_value)}

        return self.createRequestSession().post(API_URL, headers=headers, json=content, cookies=self.jar)

    def createRequestSession(self) -> requests.Session:
        if not self.session:
            self.session = requests.session()
            self.session.mount(
                "https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1)))

        return self.session

    def generateId(self) -> str:
        current: datetime = datetime.now()
        return "OWP_______________" + self.username + "_______________" + str(current.year) + str(current.month) + str(current.day) + str(current.hour) + str(current.minute) + str(current.microsecond)

    def login(self) -> bool:
        content = {
            "operationName": "LoginToken",
            "variables": {
                "id": self.generateId(),
                "country": self.country,
                "callby": "OWP_10",
                "lang": self.language,
                "user": self.username,
                "password": self.password,
            },
            "query": "mutation LoginToken($user: String!, $password: String!, $id: String!, $country: String!, $lang: String!, $callby: String!) {\n  xSLoginToken(user: $user, password: $password, id: $id, country: $country, lang: $lang, callby: $callby) {\n    res\n    msg\n    hash\n    lang\n    legals\n    mainUser\n    changePassword\n  }\n}\n",
        }
        json_internal = json.dumps(content)
        response = self.executeRequest(content)
        result_json = json.loads(response.text)
        if hasattr(result_json, "errors"):
            error_message = result_json["errors"][0]["message"]
            print(error_message)
            return False
        else:
            self.authentication_token = result_json["data"]["xSLoginToken"]["hash"]
            return True

    def listInstalations(self) -> List[instalation]:
        content = {
            "operationName": "InstallationList",
            "query": "query InstallationList {\n  xSInstallations {\n    installations {\n      numinst\n      alias\n      panel\n      type\n      name\n      surname\n      address\n      city\n      postcode\n      province\n      email\n      phone\n    }\n  }\n}\n"
        }
        response = self.executeRequest(content)
        result_json = json.loads(response.text)
        if hasattr(result_json, "errors"):
            error_message = result_json["errors"][0]["message"]
            print(error_message)
            return False
        else:
            result: List[instalation] = list()
            raw_instalations = result_json["data"]["xSInstallations"]["installations"]
            for item in raw_instalations:
                instalationItem: instalation = instalation(
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
                    item["phone"]
                )
                result.append(instalationItem)
            return result

    def checkAlarm(self, instalation: instalation) -> str:
        content = {
            "operationName": "CheckAlarm",
            "variables": {"numinst": instalation.number, "panel": instalation.panel},
            "query": "query CheckAlarm($numinst: String!, $panel: String!) {\\n  xSCheckAlarm(numinst: $numinst, panel: $panel) {\\n    res\\n    msg\\n    referenceId\\n  }\\n}\\n"
        }
        response = self.executeRequest(content)
        result_json = json.loads(response.text)
        if hasattr(result_json, "errors"):
            error_message = result_json["errors"][0]["message"]
            print(error_message)
            return None
        else:
            return result_json["data"]["xSCheckAlarm"]["referenceId"]

    def checkAlarmStatus(self, instalation: instalation, referenceId: str) -> CheckAlarmStatus:
        content = {
            "operationName": "CheckAlarmStatus",
            "variables": {
                "numinst": instalation.number,
                "panel": instalation.panel,
                "referenceId": referenceId,
                "idService": "11",
                "counter": 2
            },
             "query": "query CheckAlarmStatus($numinst: String!, $idService: String!, $panel: String!, $referenceId: String!) {\\n  xSCheckAlarmStatus(numinst: $numinst, idService: $idService, panel: $panel, referenceId: $referenceId) {\\n    res\\n    msg\\n    status\\n    numinst\\n    protomResponse\\n    protomResponseDate\\n  }\\n}\\n"
        }
        response = self.executeRequest(content)
        result_json = json.loads(response.text)
        if hasattr(result_json, "errors"):
            error_message = result_json["errors"][0]["message"]
            print(error_message)
            return None
        else:
            raw_data = result_json["data"]["xSCheckAlarmStatus"]
            return CheckAlarmStatus(
                raw_data["res"],
                raw_data["msg"],
                int(raw_data["status"]),
                raw_data["numinst"],
                raw_data["protomResponse"],
                raw_data["protomResponseDate"])
