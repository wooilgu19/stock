"""Minimal Korea Investment & Securities REST client.

This module only handles authentication and market-data requests. Order
submission remains behind OrderManager so paper-trading safety is preserved.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests


@dataclass(frozen=True)
class AccessToken:
    value: str
    expires_at: datetime

    def is_valid(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return current < self.expires_at - timedelta(minutes=1)


class KISAPIError(RuntimeError):
    """Raised when KIS returns an unsuccessful response."""


class KISRestClient:
    def __init__(self, base_url: str, app_key: str, app_secret: str,
                 timeout: float = 10.0, session: requests.Session | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.app_key = app_key
        self.app_secret = app_secret
        self.timeout = timeout
        self.session = session or requests.Session()
        self._token: AccessToken | None = None

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method, self.base_url + path,
                                        timeout=self.timeout, **kwargs)
        try:
            body = response.json()
        except ValueError as exc:
            raise KISAPIError(f"KIS returned non-JSON response ({response.status_code})") from exc
        if not response.ok or body.get("rt_cd") not in (None, "0"):
            message = body.get("msg1", "unknown KIS API error")
            raise KISAPIError(f"KIS request failed: {message}")
        return body

    def access_token(self) -> str:
        if self._token and self._token.is_valid():
            return self._token.value
        body = self._request(
            "POST",
            "/oauth2/tokenP",
            headers={"content-type": "application/json"},
            json={"grant_type": "client_credentials", "appkey": self.app_key,
                  "appsecret": self.app_secret},
        )
        expires_in = int(body.get("expires_in", 86_400))
        self._token = AccessToken(
            value=body["access_token"],
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        )
        return self._token.value

    def current_price(self, symbol: str, account_type: str = "01") -> float:
        body = self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            headers={"authorization": f"Bearer {self.access_token()}",
                     "appkey": self.app_key, "appsecret": self.app_secret,
                     "tr_id": "FHKST01010100"},
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
        )
        try:
            return float(body["output"]["stck_prpr"])
        except (KeyError, TypeError, ValueError) as exc:
            raise KISAPIError("KIS price response did not contain stck_prpr") from exc
