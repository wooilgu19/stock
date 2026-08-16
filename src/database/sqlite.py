"""SQLite persistence for executed and simulated trades."""

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.models import ORDER_LIFECYCLE_STATUSES, Side, TradeLog


class TradeRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        # sqlite3.Connection used as `with connection:` only commits/rolls
        # back; it never closes the socket. Left unclosed, WAL/shm handles
        # pile up and on Windows block deletion of the containing directory.
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._transaction() as connection:
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
                    broker_order_id TEXT,
                    filled_quantity INTEGER NOT NULL DEFAULT 0,
                    average_fill_price REAL
                )
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(trade_logs)")}
            if "client_order_id" not in columns:
                connection.execute("ALTER TABLE trade_logs ADD COLUMN client_order_id TEXT")
            if "filled_quantity" not in columns:
                connection.execute("ALTER TABLE trade_logs ADD COLUMN filled_quantity INTEGER NOT NULL DEFAULT 0")
            if "average_fill_price" not in columns:
                connection.execute("ALTER TABLE trade_logs ADD COLUMN average_fill_price REAL")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_trade_broker_id ON trade_logs(broker_order_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_trade_client_id ON trade_logs(client_order_id)")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_client_id "
                "ON trade_logs(client_order_id) WHERE client_order_id IS NOT NULL"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_trade_status_timestamp ON trade_logs(status, timestamp)")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS stream_cursors (
                    stream TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL
                )
            """)

    def save(self, trade: TradeLog) -> int:
        # A retried submission reuses the same client_order_id as a prior
        # rejected attempt (has_order_id() intentionally excludes 'rejected'
        # so retries are allowed). Without ON CONFLICT that plain insert
        # would violate the partial unique index and crash the caller with
        # sqlite3.IntegrityError, permanently stalling the pipeline on that
        # message. Resurrect the rejected row instead of inserting a
        # duplicate identity.
        with self._transaction() as connection:
            cursor = connection.execute(
                """INSERT INTO trade_logs
                (timestamp, symbol, side, quantity, price, strategy_id,
                 signal_strength, status, broker_order_id, client_order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_order_id) WHERE client_order_id IS NOT NULL
                DO UPDATE SET
                    timestamp = excluded.timestamp,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    quantity = excluded.quantity,
                    price = excluded.price,
                    strategy_id = excluded.strategy_id,
                    signal_strength = excluded.signal_strength,
                    status = excluded.status,
                    broker_order_id = excluded.broker_order_id,
                    filled_quantity = 0,
                    average_fill_price = NULL
                WHERE trade_logs.status = 'rejected'""",
                (trade.timestamp.isoformat(), trade.symbol, trade.side.value,
                 trade.quantity, trade.price, trade.strategy_id,
                 trade.signal_strength, trade.status, trade.broker_order_id,
                 trade.client_order_id),
            )
            return int(cursor.lastrowid)

    def ping(self) -> None:
        """Raise if the persistence store cannot execute a trivial query."""
        with self._transaction() as connection:
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
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT symbol, side, quantity, price, timestamp, filled_quantity, "
                "average_fill_price FROM trade_logs "
                "WHERE status IN ('filled', 'simulated', 'cancelled', 'submitted', 'rejected') "
                "AND (status IN ('filled', 'simulated') OR filled_quantity > 0) "
                "AND timestamp < ? ORDER BY timestamp, id",
                (end.isoformat(),)
            ).fetchall()
            legacy_loss = connection.execute(
                "SELECT COALESCE(SUM(quantity * price), 0) AS loss FROM trade_logs "
                "WHERE status = 'loss' AND timestamp >= ? AND timestamp < ?",
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        lots: dict[str, list[list[float | int]]] = {}
        loss = 0.0
        for row in rows:
            quantity = int(row["filled_quantity"] or row["quantity"])
            price = float(row["average_fill_price"] or row["price"])
            symbol_lots = lots.setdefault(str(row["symbol"]), [])
            if row["side"] == Side.BUY.value:
                symbol_lots.append([quantity, price])
                continue
            remaining = quantity
            proceeds = 0.0
            cost = 0.0
            while remaining and symbol_lots:
                lot_quantity, lot_price = symbol_lots[0]
                matched = min(remaining, int(lot_quantity))
                proceeds += matched * price
                cost += matched * float(lot_price)
                remaining -= matched
                lot_quantity = int(lot_quantity) - matched
                if lot_quantity:
                    symbol_lots[0][0] = lot_quantity
                else:
                    symbol_lots.pop(0)
            if row["timestamp"] >= start.isoformat() and row["timestamp"] < end.isoformat():
                loss += max(0.0, cost - proceeds)
        # Compatibility for databases created before execution-based P&L was
        # introduced. It is deliberately ignored as soon as execution rows
        # exist, so it cannot mask the FIFO calculation.
        return loss if rows else float(legacy_loss["loss"])

    def has_order_id(self, order_id: str) -> bool:
        """Return whether an order with this id was already persisted."""
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT 1 FROM trade_logs WHERE (broker_order_id = ? OR client_order_id = ?) "
                "AND status IN ('pending', 'submitted', 'filled', 'simulated') LIMIT 1",
                (order_id, order_id),
            ).fetchone()
            return row is not None

    def pending_order_ids(self) -> set[str]:
        """Return broker ids that still need a lifecycle update."""
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT broker_order_id FROM trade_logs "
                "WHERE status IN ('pending', 'submitted') AND broker_order_id IS NOT NULL"
            ).fetchall()
            return {str(row["broker_order_id"]) for row in rows}

    def update_order_status(self, order_id: str, status: str,
                            filled_quantity: int = 0,
                            average_fill_price: float | None = None) -> bool:
        """Update a known submitted order and report whether it was changed."""
        if status not in ORDER_LIFECYCLE_STATUSES:
            return False
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE trade_logs SET status = ?, filled_quantity = ?, "
                "average_fill_price = COALESCE(?, average_fill_price) "
                "WHERE broker_order_id = ? AND status IN ('pending', 'submitted')",
                (status, filled_quantity, average_fill_price, order_id),
            )
            return cursor.rowcount > 0

    def attach_broker_order(self, client_order_id: str, broker_order_id: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE trade_logs SET broker_order_id = ?, status = 'submitted' "
                "WHERE client_order_id = ? AND status = 'pending'",
                (broker_order_id, client_order_id),
            )
            return cursor.rowcount > 0

    def stream_cursor(self, stream: str) -> str:
        with self._transaction() as connection:
            row = connection.execute("SELECT message_id FROM stream_cursors WHERE stream = ?", (stream,)).fetchone()
            return str(row["message_id"]) if row else "0-0"

    def save_stream_cursor(self, stream: str, message_id: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO stream_cursors(stream, message_id) VALUES (?, ?) "
                "ON CONFLICT(stream) DO UPDATE SET message_id = excluded.message_id",
                (stream, message_id),
            )

    def executed_trade_totals(self) -> list[tuple[str, str, int, float]]:
        """Return aggregate quantities and values for persisted executions."""
        with self._transaction() as connection:
            rows = connection.execute(
                """SELECT symbol, side,
                          SUM(CASE WHEN filled_quantity > 0 THEN filled_quantity ELSE quantity END) AS quantity,
                          SUM((CASE WHEN filled_quantity > 0 THEN filled_quantity ELSE quantity END) *
                              COALESCE(average_fill_price, price)) AS value
                   FROM trade_logs
                   WHERE status IN ('filled', 'simulated', 'cancelled', 'submitted', 'rejected')
                     AND (status IN ('filled', 'simulated') OR filled_quantity > 0)
                   GROUP BY symbol, side"""
            ).fetchall()
            return [
                (str(row["symbol"]), str(row["side"]), int(row["quantity"]), float(row["value"]))
                for row in rows
            ]
