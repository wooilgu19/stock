"""Minimal Korea Investment & Securities REST client.

This module only handles authentication and market-data requests. Order
submission remains behind OrderManager so paper-trading safety is preserved.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from collections.abc import Iterable
from typing import Any

import requests

from src.models import OrderRequest, OrderStatusUpdate, Side


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
        try:
            response = self.session.request(method, self.base_url + path,
                                            timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise KISAPIError(f"KIS request failed: {exc}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise KISAPIError(f"KIS returned non-JSON response ({response.status_code})") from exc
        if not isinstance(body, dict):
            raise KISAPIError("KIS response body was not an object")
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


class KISOrderExecutor:
    """Submit domestic cash orders through a :class:`KISRestClient`.

    This adapter intentionally supports limit orders only: ``OrderRequest``
    already contains a validated price, and silently changing it to a market
    order would weaken the risk boundary.  The executor returns only after KIS
    provides an order number, which lets ``OrderManager`` persist an accepted
    order safely.
    """

    def __init__(self, client: KISRestClient, account_number: str,
                 account_product_code: str = "01", paper_trading: bool = True) -> None:
        if not account_number.strip():
            raise ValueError("account_number is required")
        if not account_product_code.strip():
            raise ValueError("account_product_code is required")
        self.client = client
        self.account_number = account_number
        self.account_product_code = account_product_code
        self.paper_trading = paper_trading

    def submit(self, order: OrderRequest) -> str:
        if order.quantity <= 0 or order.price <= 0:
            raise ValueError("quantity and price must be positive")
        if order.side not in (Side.BUY, Side.SELL):
            raise ValueError("unsupported order side")

        transaction_id = self._transaction_id(order.side)
        body = self.client._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-cash",
            headers={
                "authorization": f"Bearer {self.client.access_token()}",
                "appkey": self.client.app_key,
                "appsecret": self.client.app_secret,
                "tr_id": transaction_id,
                "content-type": "application/json; charset=utf-8",
            },
            json={
                "CANO": self.account_number,
                "ACNT_PRDT_CD": self.account_product_code,
                "PDNO": order.symbol,
                "ORD_DVSN": "00",
                "ORD_QTY": str(order.quantity),
                "ORD_UNPR": str(int(order.price)),
            },
        )
        try:
            order_number = str(body["output"]["ODNO"])
        except (KeyError, TypeError, ValueError) as exc:
            raise KISAPIError("KIS order response did not contain ODNO") from exc
        if not order_number.strip():
            raise KISAPIError("KIS order response contained an empty ODNO")
        return order_number

    def _transaction_id(self, side: Side) -> str:
        if self.paper_trading:
            return "VTTC0802U" if side == Side.BUY else "VTTC0801U"
        return "TTTC0802U" if side == Side.BUY else "TTTC0801U"


class KISOrderStatusProvider:
    """Fetch recent domestic-stock order lifecycle updates from KIS."""

    _MAX_PAGES = 100

    def __init__(self, client: KISRestClient, account_number: str,
                 account_product_code: str = "01", paper_trading: bool = True,
                 lookback_days: int = 1) -> None:
        if not account_number.strip():
            raise ValueError("account_number is required")
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        self.client = client
        self.account_number = account_number
        self.account_product_code = account_product_code
        self.paper_trading = paper_trading
        self.lookback_days = lookback_days

    def __call__(self) -> Iterable[OrderStatusUpdate]:
        today = date.today()
        return self.fetch(today - timedelta(days=self.lookback_days - 1), today)

    def fetch(self, start_date: date, end_date: date) -> list[OrderStatusUpdate]:
        if end_date < start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        headers = {
            "authorization": f"Bearer {self.client.access_token()}",
            "appkey": self.client.app_key,
            "appsecret": self.client.app_secret,
            "tr_id": "VTTC8001R" if self.paper_trading else "TTTC8001R",
        }
        params = {
            "CANO": self.account_number,
            "ACNT_PRDT_CD": self.account_product_code,
            "INQR_STRT_DT": start_date.strftime("%Y%m%d"),
            "INQR_END_DT": end_date.strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "INQR_DVSN_3": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        updates: list[OrderStatusUpdate] = []
        seen_tokens: set[tuple[str, str]] = set()
        for _ in range(self._MAX_PAGES):
            body = self.client._request(
                "GET",
                "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
                headers=headers,
                params=params,
            )
            rows = body.get("output1", [])
            if not isinstance(rows, list):
                raise KISAPIError("KIS order status response output1 was not a list")
            updates.extend(
                update for row in rows if isinstance(row, dict)
                if (update := self._parse_update(row)) is not None
            )
            next_tokens = self._next_page_tokens(body)
            if not any(next_tokens):
                return updates
            if next_tokens in seen_tokens:
                raise KISAPIError("KIS order status pagination repeated a page token")
            seen_tokens.add(next_tokens)
            params["CTX_AREA_FK100"], params["CTX_AREA_NK100"] = next_tokens
        raise KISAPIError("KIS order status pagination exceeded page limit")

    @staticmethod
    def _next_page_tokens(body: dict[str, Any]) -> tuple[str, str]:
        output2 = body.get("output2")
        source = output2 if isinstance(output2, dict) else body
        return (
            str(source.get("ctx_area_fk100", "") or "").strip(),
            str(source.get("ctx_area_nk100", "") or "").strip(),
        )

    @staticmethod
    def _parse_update(row: dict[str, Any]) -> OrderStatusUpdate | None:
        order_id = str(row.get("odno", "")).strip()
        if not order_id:
            return None
        try:
            rejected = int(str(row.get("rjct_qty", "0") or "0")) > 0
            filled = int(str(row.get("tot_ccld_qty", "0") or "0")) > 0
            remaining = int(str(row.get("rmn_qty", "0") or "0"))
        except (TypeError, ValueError):
            return None
        cancelled = str(row.get("cncl_yn", "N")).upper() == "Y"
        status = "rejected" if rejected else (
            "cancelled" if cancelled else "filled" if filled and remaining == 0 else "submitted"
        )
        return OrderStatusUpdate(order_id, status)
