from datetime import date
import json
import logging
from datetime import datetime
from time import time
import requests

from http.client import HTTPConnection, NotConnected  # py3

log = logging.getLogger('urllib3')
log.setLevel(logging.DEBUG)

# logging from urllib3 to console
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
log.addHandler(ch)

# print statements from `http.client.HTTPConnection` to console/stdout
HTTPConnection.debuglevel = 1

from requests.adapters import HTTPAdapter
from requests.models import Response
from requests.sessions import session
from urllib3 import Retry

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
                "user" : self.username, 
                "id" : self.generateId(),
                "country" : self.country,
                "lang" : self.language,
                "callby" : "OWP_10",
                "hash" : self.authentication_token
            }
            headers = { 'auth' : json.dumps(authorization_value) }
            
        return self.createRequestSession().post(API_URL, headers=headers, json=content, cookies=self.jar)

    def createRequestSession(self) -> requests.Session:
        if not self.session:
            self.session = requests.session()
            self.session.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1)))

        return self.session

    def generateId(self) -> str:
        return "OWP_______________"+ self.username + "_______________" + str(date.year) + str(date.month) + str(date.day) + str(datetime.hour) + str(datetime.minute) + str(datetime.microsecond)

    def login(self) -> bool:
        content = { 
            "operationName": "LoginToken" , 
            "query" : "mutation LoginToken($user: String!, $password: String!, $id: String!, $country: String!, $lang: String!, $callby: String!) {\n  xSLoginToken(user: $user, password: $password, id: $id, country: $country, lang: $lang, callby: $callby) {\n    res\n    msg\n    hash\n    lang\n    legals\n    mainUser\n    changePassword\n  }\n}\n",
            "variables" : { 
                "id" : self.generateId(), 
                "country" : self.country,
                "callby" : "OWP_10",
                "lang" : self.language,
                "user" : self.username,
                "password" : self.password,                
                }            
            }
        response = self.executeRequest(content)
        result_json = json.loads(response.text)
        if result_json["errors"] is not None:
            error_message = result_json["errors"][0]["message"]
            print(error_message)
            return False
        else:
            self.authentication_token = result_json["data"]["xSLoginToken"]["hash"]
            return True

    def listInstalations(self):
        content = {
            "operationName" : "InstallationList",
            "query" : "query InstallationList {\n  xSInstallations {\n    installations {\n      numinst\n      alias\n      panel\n      type\n      name\n      surname\n      address\n      city\n      postcode\n      province\n      email\n      phone\n    }\n  }\n}\n"
        }
        response = self.executeRequest(content)
        result_json = json.loads(response.text)
        if result_json["errors"] is not None:
            error_message = result_json["errors"][0]["message"]
            print(error_message)
            return False
        else:
            self.authentication_token = result_json["data"]["xSLoginToken"]["hash"]
            return True
    