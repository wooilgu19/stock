"""SQLite persistence for executed and simulated trades."""

import sqlite3
from datetime import date, datetime, timedelta, timezone
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

    def ping(self) -> None:
        """Raise if the persistence store cannot execute a trivial query."""
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def daily_realized_loss(self, day: date | None = None) -> float:
        """Return recorded loss for one UTC calendar day.

        Trade timestamps are persisted as ISO-8601 values.  Comparing an
        explicit half-open UTC range keeps historical losses from affecting a
        later trading day while remaining deterministic in tests.
        """
        target_day = day or datetime.now(timezone.utc).date()
        start = datetime.combine(target_day, datetime.min.time(), timezone.utc)
        end = start + timedelta(days=1)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(quantity * price), 0) AS loss "
                "FROM trade_logs WHERE side = ? AND status = 'loss' "
                "AND timestamp >= ? AND timestamp < ?",
                (Side.SELL.value, start.isoformat(), end.isoformat()),
            ).fetchone()
            return float(row["loss"])

    def has_order_id(self, order_id: str) -> bool:
        """Return whether an order with this id was already persisted."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM trade_logs WHERE broker_order_id = ? LIMIT 1",
                (order_id,),
            ).fetchone()
            return row is not None

    def pending_order_ids(self) -> set[str]:
        """Return broker ids that still need a lifecycle update."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT broker_order_id FROM trade_logs "
                "WHERE status = 'submitted' AND broker_order_id IS NOT NULL"
            ).fetchall()
            return {str(row["broker_order_id"]) for row in rows}

    def update_order_status(self, order_id: str, status: str) -> bool:
        """Update a known submitted order and report whether it was changed."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE trade_logs SET status = ? "
                "WHERE broker_order_id = ? AND status = 'submitted'",
                (status, order_id),
            )
            return cursor.rowcount > 0

    def executed_trade_totals(self) -> list[tuple[str, str, int, float]]:
        """Return aggregate quantities and values for persisted executions."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT symbol, side, SUM(quantity) AS quantity,
                          SUM(quantity * price) AS value
                   FROM trade_logs
                   WHERE status IN ('filled', 'simulated')
                   GROUP BY symbol, side"""
            ).fetchall()
            return [
                (str(row["symbol"]), str(row["side"]), int(row["quantity"]), float(row["value"]))
                for row in rows
            ]
