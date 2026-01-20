"""Authentication helpers for nonkyc.io exchange APIs."""

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
    signed_message: str
    json_str: str | None


class AuthSigner:
    """Signer for authenticated NonKYC REST and WebSocket requests."""

    def __init__(
        self,
        time_provider: Callable[[], float] | None = None,
        *,
        nonce_multiplier: float = 1e3,
        sort_params: bool = False,
        sort_body: bool = False,
    ) -> None:
        self._time_provider = time_provider or time.time
        self._uses_default_time_provider = time_provider is None
        self._nonce_multiplier = nonce_multiplier
        self._sort_params = sort_params
        self._sort_body = sort_body

    def sign(self, message: str, credentials: ApiCredentials) -> str:
        return hmac.new(
            credentials.api_secret.encode("utf8"),
            message.encode("utf8"),
            hashlib.sha256,
        ).hexdigest()

    def serialize_body(self, body: Mapping[str, Any]) -> str:
        return json.dumps(
            body,
            separators=(",", ":"),
            sort_keys=self._sort_body,
            ensure_ascii=False,
        )

    def serialize_query(self, params: Mapping[str, Any]) -> str:
        query_items = sorted(params.items()) if self._sort_params else params.items()
        return urlencode(list(query_items), doseq=True)

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
                query = self.serialize_query(params)
                data_to_sign = f"{url}?{query}"
            else:
                data_to_sign = url
        else:
            json_str = self.serialize_body(body or {})
            data_to_sign = f"{url}{json_str}"
        nonce = self.generate_nonce()
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
            signed_message=message,
            json_str=json_str,
        )

    def build_headers_for_message(
        self,
        credentials: ApiCredentials,
        data_to_sign: str,
        nonce: int,
        json_str: str | None = None,
    ) -> SignedHeaders:
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
            signed_message=message,
            json_str=json_str,
        )

    def generate_nonce(self, multiplier: float | None = None) -> int:
        resolved_multiplier = (
            self._nonce_multiplier if multiplier is None else multiplier
        )
        return int(self._time_provider() * resolved_multiplier)

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

    def uses_default_time_provider(self) -> bool:
        return self._uses_default_time_provider

    def set_time_provider(self, time_provider: Callable[[], float]) -> None:
        self._time_provider = time_provider
        self._uses_default_time_provider = False
