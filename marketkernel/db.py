from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DB_PATH = Path("marketkernel.db")

DEFAULT_WATCHLIST = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "SBIN.NS",
]


def utc_now_str() -> str:
    """Return current timestamp formatted for readable TUI display."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """SQLite persistence layer for accounts, positions, trades, and auto-rules."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection; commit on success, rollback on error, always close."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    starting_capital REAL NOT NULL DEFAULT 100000.0,
                    cash_balance REAL NOT NULL DEFAULT 100000.0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol TEXT PRIMARY KEY,
                    added_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL CHECK (quantity >= 0),
                    avg_buy_price REAL NOT NULL CHECK (avg_buy_price >= 0),
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
                    mode TEXT NOT NULL CHECK (mode IN ('MANUAL', 'AUTO')),
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    trade_price REAL NOT NULL CHECK (trade_price > 0),
                    buy_avg_at_sale REAL NOT NULL DEFAULT 0.0,
                    total_value REAL NOT NULL,
                    realized_pnl REAL NOT NULL DEFAULT 0.0,
                    note TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS auto_rules (
                    symbol TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    buy_below_price REAL NOT NULL DEFAULT 0.0,
                    sell_above_price REAL NOT NULL DEFAULT 0.0,
                    stop_loss_price REAL NOT NULL DEFAULT 0.0,
                    use_sma_crossover INTEGER NOT NULL DEFAULT 0,
                    trade_qty INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # Seed default account if empty
            row = conn.execute("SELECT id FROM account WHERE id = 1").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO account (id, starting_capital, cash_balance, updated_at) VALUES (1, 100000.0, 100000.0, ?)",
                    (utc_now_str(),),
                )

            # Seed default watchlist if empty
            wl_count = conn.execute("SELECT COUNT(*) AS cnt FROM watchlist").fetchone()["cnt"]
            if wl_count == 0:
                now = utc_now_str()
                for sym in DEFAULT_WATCHLIST:
                    conn.execute(
                        "INSERT OR IGNORE INTO watchlist (symbol, added_at) VALUES (?, ?)",
                        (sym, now),
                    )

    # --- Account & Watchlist ---

    def get_account(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
            return dict(row)

    def reset_account(self, starting_capital: float = 100000.0) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM positions")
            conn.execute("DELETE FROM trades")
            conn.execute(
                "UPDATE account SET starting_capital = ?, cash_balance = ?, updated_at = ? WHERE id = 1",
                (starting_capital, starting_capital, utc_now_str()),
            )

    def get_watchlist(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT symbol FROM watchlist ORDER BY symbol ASC").fetchall()
            return [r["symbol"] for r in rows]

    def add_to_watchlist(self, symbol: str) -> None:
        clean_sym = symbol.strip().upper()
        if not clean_sym:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (symbol, added_at) VALUES (?, ?)",
                (clean_sym, utc_now_str()),
            )

    def remove_from_watchlist(self, symbol: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.strip().upper(),))

    # --- Positions & Trades ---

    def get_positions(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE quantity > 0 ORDER BY symbol ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE symbol = ? AND quantity > 0",
                (symbol.upper(),),
            ).fetchone()
            return dict(row) if row else None

    def get_trades(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_total_realized_pnl(self) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0.0) AS total_pnl FROM trades WHERE side = 'SELL'"
            ).fetchone()
            return float(row["total_pnl"])

    # --- Auto Rules ---

    def get_auto_rule(self, symbol: str) -> dict[str, Any]:
        sym = symbol.upper()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM auto_rules WHERE symbol = ?", (sym,)
            ).fetchone()
            if row:
                return dict(row)
            return {
                "symbol": sym,
                "enabled": 0,
                "buy_below_price": 0.0,
                "sell_above_price": 0.0,
                "stop_loss_price": 0.0,
                "use_sma_crossover": 0,
                "trade_qty": 1,
                "updated_at": utc_now_str(),
            }

    def get_all_enabled_rules(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM auto_rules WHERE enabled = 1"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_enabled_symbols(self) -> set[str]:
        """Single-query lookup of which symbols have an enabled auto-rule."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol FROM auto_rules WHERE enabled = 1"
            ).fetchall()
            return {r["symbol"] for r in rows}

    def upsert_auto_rule(
        self,
        symbol: str,
        enabled: bool,
        buy_below_price: float,
        sell_above_price: float,
        stop_loss_price: float,
        use_sma_crossover: bool,
        trade_qty: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auto_rules (
                    symbol, enabled, buy_below_price, sell_above_price,
                    stop_loss_price, use_sma_crossover, trade_qty, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    enabled = excluded.enabled,
                    buy_below_price = excluded.buy_below_price,
                    sell_above_price = excluded.sell_above_price,
                    stop_loss_price = excluded.stop_loss_price,
                    use_sma_crossover = excluded.use_sma_crossover,
                    trade_qty = excluded.trade_qty,
                    updated_at = excluded.updated_at
                """,
                (
                    symbol.upper(),
                    1 if enabled else 0,
                    max(0.0, buy_below_price),
                    max(0.0, sell_above_price),
                    max(0.0, stop_loss_price),
                    1 if use_sma_crossover else 0,
                    max(1, trade_qty),
                    utc_now_str(),
                ),
            )
