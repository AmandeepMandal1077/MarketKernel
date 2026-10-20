from __future__ import annotations

from dataclasses import dataclass
from marketkernel.db import Database, utc_now_str


@dataclass(slots=True)
class TradeResult:
    success: bool
    message: str
    realized_pnl: float = 0.0


class TradingEngine:
    """Core trading execution engine shared by Manual and Automated modes."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        mode: str = "MANUAL",
        note: str = "",
    ) -> TradeResult:
        """Buy shares, deduct cash, update weighted avg buy price, and log trade."""
        sym = symbol.strip().upper()
        if quantity <= 0:
            return TradeResult(False, "Quantity must be greater than 0.")
        if price <= 0:
            return TradeResult(False, f"Invalid market price ({price}) for {sym}.")

        total_cost = round(quantity * price, 2)
        now = utc_now_str()

        with self.db._connect() as conn:
            acct = conn.execute("SELECT cash_balance FROM account WHERE id = 1").fetchone()
            cash = float(acct["cash_balance"])
            if cash < total_cost:
                return TradeResult(
                    False,
                    f"Insufficient cash! Need ₹{total_cost:,.2f}, have ₹{cash:,.2f}.",
                )

            pos = conn.execute(
                "SELECT quantity, avg_buy_price FROM positions WHERE symbol = ?",
                (sym,),
            ).fetchone()

            if pos is None or int(pos["quantity"]) == 0:
                new_qty = quantity
                new_avg = round(price, 2)
            else:
                old_qty = int(pos["quantity"])
                old_avg = float(pos["avg_buy_price"])
                new_qty = old_qty + quantity
                new_avg = round(((old_qty * old_avg) + (quantity * price)) / new_qty, 2)

            # 1. Deduct cash
            conn.execute(
                "UPDATE account SET cash_balance = ?, updated_at = ? WHERE id = 1",
                (round(cash - total_cost, 2), now),
            )

            # 2. Upsert position
            conn.execute(
                """
                INSERT INTO positions (symbol, quantity, avg_buy_price, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    quantity = excluded.quantity,
                    avg_buy_price = excluded.avg_buy_price,
                    updated_at = excluded.updated_at
                """,
                (sym, new_qty, new_avg, now),
            )

            # 3. Record trade in ledger
            conn.execute(
                """
                INSERT INTO trades (
                    timestamp, symbol, side, mode, quantity,
                    trade_price, buy_avg_at_sale, total_value, realized_pnl, note
                ) VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?, 0.0, ?)
                """,
                (now, sym, mode, quantity, round(price, 2), new_avg, total_cost, note),
            )

        return TradeResult(
            True,
            f"[{mode}] Bought {quantity} {sym} @ ₹{price:,.2f} (Avg Cost: ₹{new_avg:,.2f})",
        )

    def sell(
        self,
        symbol: str,
        quantity: int,
        price: float,
        mode: str = "MANUAL",
        note: str = "",
    ) -> TradeResult:
        """Sell shares, compute realized profit against avg buy price, credit cash, and log trade."""
        sym = symbol.strip().upper()
        if quantity <= 0:
            return TradeResult(False, "Quantity must be greater than 0.")
        if price <= 0:
            return TradeResult(False, f"Invalid market price ({price}) for {sym}.")

        now = utc_now_str()

        with self.db._connect() as conn:
            pos = conn.execute(
                "SELECT quantity, avg_buy_price FROM positions WHERE symbol = ?",
                (sym,),
            ).fetchone()

            if pos is None or int(pos["quantity"]) < quantity:
                held = int(pos["quantity"]) if pos else 0
                return TradeResult(
                    False,
                    f"Cannot sell {quantity} shares of {sym}. You only hold {held}.",
                )

            old_qty = int(pos["quantity"])
            avg_buy_price = float(pos["avg_buy_price"])
            remaining_qty = old_qty - quantity

            total_proceeds = round(quantity * price, 2)
            realized_pnl = round((price - avg_buy_price) * quantity, 2)

            acct = conn.execute("SELECT cash_balance FROM account WHERE id = 1").fetchone()
            cash = float(acct["cash_balance"])

            # 1. Credit cash proceeds
            conn.execute(
                "UPDATE account SET cash_balance = ?, updated_at = ? WHERE id = 1",
                (round(cash + total_proceeds, 2), now),
            )

            # 2. Update or clear position
            if remaining_qty == 0:
                conn.execute("DELETE FROM positions WHERE symbol = ?", (sym,))
            else:
                conn.execute(
                    "UPDATE positions SET quantity = ?, updated_at = ? WHERE symbol = ?",
                    (remaining_qty, now, sym),
                )

            # 3. Record sell trade with exact buy_avg_at_sale and realized_pnl
            conn.execute(
                """
                INSERT INTO trades (
                    timestamp, symbol, side, mode, quantity,
                    trade_price, buy_avg_at_sale, total_value, realized_pnl, note
                ) VALUES (?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    sym,
                    mode,
                    quantity,
                    round(price, 2),
                    avg_buy_price,
                    total_proceeds,
                    realized_pnl,
                    note,
                ),
            )

        pnl_sign = "+" if realized_pnl >= 0 else ""
        return TradeResult(
            True,
            f"[{mode}] Sold {quantity} {sym} @ ₹{price:,.2f} (Bought @ ₹{avg_buy_price:,.2f}) | Profit: {pnl_sign}₹{realized_pnl:,.2f}",
            realized_pnl=realized_pnl,
        )

    def evaluate_auto_rules(
        self, symbol: str, latest_price: float, closes: list[float]
    ) -> list[TradeResult]:
        """Check if an enabled auto-rule for `symbol` triggers an automated BUY or SELL."""
        results: list[TradeResult] = []
        if latest_price <= 0:
            return results

        rule = self.db.get_auto_rule(symbol)
        if not rule["enabled"]:
            return results

        qty = int(rule["trade_qty"])
        buy_below = float(rule["buy_below_price"])
        sell_above = float(rule["sell_above_price"])
        stop_loss = float(rule["stop_loss_price"])
        use_sma = bool(rule["use_sma_crossover"])

        pos = self.db.get_position(symbol)
        held_qty = int(pos["quantity"]) if pos else 0

        # 1. Price Threshold Buy Trigger (only if we don't already hold a position, to prevent infinite loop buying)
        if buy_below > 0 and latest_price <= buy_below and held_qty == 0:
            res = self.buy(
                symbol=symbol,
                quantity=qty,
                price=latest_price,
                mode="AUTO",
                note=f"Target Buy <= {buy_below}",
            )
            if res.success:
                results.append(res)
                held_qty += qty

        # 2. Take-Profit Sell Trigger (if holding shares and price hits target)
        if sell_above > 0 and latest_price >= sell_above and held_qty > 0:
            sell_qty = min(qty, held_qty)
            res = self.sell(
                symbol=symbol,
                quantity=sell_qty,
                price=latest_price,
                mode="AUTO",
                note=f"Take Profit >= {sell_above}",
            )
            if res.success:
                results.append(res)
                held_qty -= sell_qty

        # 3. Stop-Loss Sell Trigger (if holding shares and price drops below stop)
        if stop_loss > 0 and latest_price <= stop_loss and held_qty > 0:
            sell_qty = min(qty, held_qty)
            res = self.sell(
                symbol=symbol,
                quantity=sell_qty,
                price=latest_price,
                mode="AUTO",
                note=f"Stop Loss <= {stop_loss}",
            )
            if res.success:
                results.append(res)
                held_qty -= sell_qty

        # 4. Optional SMA(5) / SMA(15) Crossover Strategy
        if use_sma and len(closes) >= 16:
            prev_fast = sum(closes[-6:-1]) / 5.0
            prev_slow = sum(closes[-16:-1]) / 15.0
            curr_fast = sum(closes[-5:]) / 5.0
            curr_slow = sum(closes[-15:]) / 15.0

            # Bullish crossover: Fast crosses above Slow
            if prev_fast <= prev_slow and curr_fast > curr_slow and held_qty == 0:
                res = self.buy(
                    symbol=symbol,
                    quantity=qty,
                    price=latest_price,
                    mode="AUTO",
                    note="SMA(5) crossed above SMA(15)",
                )
                if res.success:
                    results.append(res)
            # Bearish crossover: Fast crosses below Slow
            elif prev_fast >= prev_slow and curr_fast < curr_slow and held_qty > 0:
                res = self.sell(
                    symbol=symbol,
                    quantity=held_qty,
                    price=latest_price,
                    mode="AUTO",
                    note="SMA(5) crossed below SMA(15)",
                )
                if res.success:
                    results.append(res)

        return results
