import json
import logging
import requests

from requests.adapters import HTTPAdapter
from requests.models import Response
from requests.sessions import session
from urllib3 import Retry

API_URL = "https://customers.securitasdirect.es/owa-static/"

class ApiManager:
    def __init__(self, username, password, country, language):
        self.username = username
        self.password = password
        self.country = country
        self.language = language
        requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS += 'HIGH:!DH:!aNULL'

    def executeRequest(self, operation, content) -> Response:
        self.operation = operation
        self.content = content
        return self.createRequestSession().get(API_URL + operation, params=content)

    def createRequestSession(self) -> requests.Session:
        if not self.session:
            self.session = requests.session()
            self.session.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1)))

        return self.session

    def login(self) -> bool:
        rawContent = "{\"operationName\":\"LoginToken\",\"variables\":{\"id\":\"OWP_______________123_______________202111271046477\",\"country\":\"ES\",\"callby\":\"OWP_10\",\"lang\":\"es\",\"user\":\"123\",\"password\":\"456\"},\"query\":\"mutation LoginToken($user: String!, $password: String!, $id: String!, $country: String!, $lang: String!, $callby: String!) {\\n  xSLoginToken(user: $user, password: $password, id: $id, country: $country, lang: $lang, callby: $callby) {\\n    res\\n    msg\\n    hash\\n    lang\\n    legals\\n    mainUser\\n    changePassword\\n  }\\n}\\n\"}"
        content = { 
            "operationName": "LoginToken" , 
            "variables" : { 
                "id" : "OWP_______________123_______________202111271046477", 
                "country" : self.country,
                "callby" : "OWP",
                "lang" : self.language,
                "user" : self.username,
                "password" : self.password,
                "query" : "mutation LoginToken($user: String!, $password: String!, $id: String!, $country: String!, $lang: String!, $callby: String!)"
                } 
            }
        response = self.executeRequest("login", content=content)        

        

    