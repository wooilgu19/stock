"""SQLite persistence for executed and simulated trades."""

import sqlite3
from pathlib import Path

from src.models import Side, TradeLog


class TradeRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS trade_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    strategy_id TEXT NOT NULL,
                    signal_strength REAL NOT NULL,
                    status TEXT NOT NULL,
                    broker_order_id TEXT
                )
            """)

    def save(self, trade: TradeLog) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO trade_logs
                (timestamp, symbol, side, quantity, price, strategy_id,
                 signal_strength, status, broker_order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade.timestamp.isoformat(), trade.symbol, trade.side.value,
                 trade.quantity, trade.price, trade.strategy_id,
                 trade.signal_strength, trade.status, trade.broker_order_id),
            )
            return int(cursor.lastrowid)

    def daily_realized_loss(self) -> float:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(quantity * price), 0) AS loss "
                "FROM trade_logs WHERE side = ? AND status = 'loss'",
                (Side.SELL.value,),
            ).fetchone()
            return float(row["loss"])
