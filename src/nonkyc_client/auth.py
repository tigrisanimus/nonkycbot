"""Authentication helpers for NonKYC exchange APIs."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import string
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlencode


@dataclass(frozen=True)
class ApiCredentials:
    api_key: str
    api_secret: str


@dataclass(frozen=True)
class SignedHeaders:
    headers: dict[str, str]
    signature: str
    nonce: int
    data_to_sign: str
    json_str: str | None


class AuthSigner:
    """Signer for authenticated NonKYC REST and WebSocket requests."""

    def __init__(self, time_provider: Callable[[], float] | None = None) -> None:
        self._time_provider = time_provider or time.time

    def sign(self, message: str, credentials: ApiCredentials) -> str:
        return hmac.new(
            credentials.api_secret.encode("utf8"),
            message.encode("utf8"),
            hashlib.sha256,
        ).hexdigest()

    def build_rest_headers(
        self,
        credentials: ApiCredentials,
        method: str,
        url: str,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> SignedHeaders:
        method_upper = method.upper()
        json_str = None
        if method_upper == "GET":
            if params:
                query = urlencode(sorted(params.items()), doseq=True)
                data_to_sign = f"{url}?{query}"
            else:
                data_to_sign = url
        else:
            if body is None:
                data_to_sign = url
            else:
                json_str = json.dumps(body, separators=(",", ":"), sort_keys=True)
                data_to_sign = f"{url}{json_str}"
        nonce = int(self._time_provider() * 1e3)
        message = f"{credentials.api_key}{data_to_sign}{nonce}"
        signature = self.sign(message, credentials)
        headers = {
            "X-API-KEY": credentials.api_key,
            "X-API-NONCE": str(nonce),
            "X-API-SIGN": signature,
        }
        return SignedHeaders(
            headers=headers,
            signature=signature,
            nonce=nonce,
            data_to_sign=data_to_sign,
            json_str=json_str,
        )

    def build_ws_login_payload(
        self, credentials: ApiCredentials, nonce: str | None = None
    ) -> dict[str, Any]:
        token = nonce or self._generate_nonce()
        signature = self.sign(token, credentials)
        return {
            "method": "login",
            "params": {
                "algo": "HS256",
                "pKey": credentials.api_key,
                "nonce": token,
                "signature": signature,
            },
        }

    def _generate_nonce(self) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(14))
