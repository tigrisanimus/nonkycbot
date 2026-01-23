import hashlib
import hmac
import json
import random
import string
from collections import OrderedDict
from typing import Any, Dict
from urllib.parse import urlencode

from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest, WSRequest


class NonkycAuth(AuthBase):
    def __init__(self, api_key: str, secret_key: str, time_provider: TimeSynchronizer):
        self.api_key = api_key
        self.secret_key = secret_key
        self.time_provider = time_provider

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """
        Adds the server time and the signature to the request, required for authenticated interactions. It also adds
        the required parameter in the request header.
        :param request: the request to be configured for authenticated interaction
        """

        headers = {}
        if request.headers is not None:
            headers.update(request.headers)

        if request.method == RESTMethod.GET:
            url = f"{request.url}?{urlencode(request.params)}" if request.params else request.url
            headers.update(self.header_for_authentication(data=(url)))

        elif request.method == RESTMethod.POST:
            json_str = (json.dumps(json.loads(request.data))).replace(" ", "")
            to_sign = f"{request.url}{json_str}"
            headers.update(self.header_for_authentication(to_sign))

        request.headers = headers
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        """
        This method is intended to configure a websocket request to be authenticated. Nonkyc does not use this
        functionality
        """
        return request  # pass-through

    def generate_ws_authentication_message(self, request: WSRequest = None, ) -> Dict[str, any]:
        random_str = str(random.choices(string.ascii_letters + string.digits, k=14))
        payload = {
            "method": "login",
            "params": {
                "algo": "HS256",
                "pKey": self.api_key,
                "nonce": random_str,
                "signature": self._generate_signature(random_str)
            }
        }
        return payload

    def header_for_authentication(self, data: str) -> Dict[str, str]:
        timestamp =  int(self.time_provider.time() * 1e4)
        message_to_sign = f"{self.api_key}{data}{timestamp}"
        signature = self._generate_signature(message_to_sign)
        return {"X-API-KEY": self.api_key,
                "X-API-NONCE": str(timestamp),
                "X-API-SIGN": signature}

    def _generate_signature(self, data: str) -> str:
        digest = hmac.new(self.secret_key.encode("utf8"), data.encode("utf8"), hashlib.sha256).hexdigest()
        return digest
