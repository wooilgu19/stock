"""Typed messages passed through the trading pipeline."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Tick:
    symbol: str
    price: float
    volume: int
    timestamp: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.price <= 0 or self.volume < 0:
            raise ValueError("price must be positive and volume cannot be negative")


@dataclass(frozen=True)
class Signal:
    symbol: str
    action: SignalAction
    strength: float
    price: float
    strategy_id: str
    timestamp: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not 0 <= self.strength <= 1:
            raise ValueError("strength must be between 0 and 1")
        if self.action != SignalAction.HOLD and self.price <= 0:
            raise ValueError("trade signal price must be positive")


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: Side
    quantity: int
    price: float
    strategy_id: str
    signal_strength: float
    timestamp: datetime = field(default_factory=utc_now)

    @property
    def value(self) -> int:
        return int(self.quantity * self.price)

    def __post_init__(self) -> None:
        if self.quantity <= 0 or self.price <= 0:
            raise ValueError("quantity and price must be positive")


@dataclass(frozen=True)
class TradeLog:
    symbol: str
    side: Side
    quantity: int
    price: float
    strategy_id: str
    signal_strength: float
    status: str = "filled"
    timestamp: datetime = field(default_factory=utc_now)
    broker_order_id: str | None = None
    id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": self.price,
            "strategy_id": self.strategy_id,
            "signal_strength": self.signal_strength,
            "status": self.status,
            "broker_order_id": self.broker_order_id,
        }
