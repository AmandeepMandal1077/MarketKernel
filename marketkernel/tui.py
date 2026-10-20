from __future__ import annotations

import asyncio
from typing import Any

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
)

from marketkernel.charts import CHART_MODES, PriceChart
from marketkernel.data_feed import MarketDataFeed
from marketkernel.db import Database
from marketkernel.engine import TradingEngine


# =====================================================================
# MODAL 1: MANUAL BUY / SELL DIALOG
# =====================================================================
class OrderModal(ModalScreen[dict[str, Any] | None]):
    """Popup modal for placing a Manual Buy or Sell order."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        side: str,
        symbol: str,
        latest_price: float,
        cash_balance: float,
        held_qty: int,
        avg_buy_price: float,
    ) -> None:
        super().__init__()
        self.side = side.upper()
        self.symbol = symbol
        self.latest_price = latest_price
        self.cash_balance = cash_balance
        self.held_qty = held_qty
        self.avg_buy_price = avg_buy_price

    def compose(self) -> ComposeResult:
        max_buy = int(self.cash_balance // self.latest_price) if self.latest_price > 0 else 0
        info_line = (
            f"Available Cash: ₹{self.cash_balance:,.2f} (Max Buy: {max_buy} shares)"
            if self.side == "BUY"
            else f"Currently Holding: {self.held_qty} shares | Bought Avg: ₹{self.avg_buy_price:,.2f}"
        )

        with Vertical(id="modal-box"):
            yield Label(f"MANUAL {self.side} — {self.symbol}", id="modal-title")
            yield Label(f"Latest Market Price (yfinance): ₹{self.latest_price:,.2f}")
            yield Label(info_line)
            yield Label("Quantity (Shares):")
            yield Input(value="1", placeholder="Enter quantity (e.g. 5)", id="qty-input")
            yield Label("Execution Price (Leave as market price or override):")
            yield Input(value=f"{self.latest_price:.2f}", id="price-input")
            yield Label("Trade Note (Optional):")
            yield Input(value="", placeholder="e.g. Breakout entry / Booking profit", id="note-input")
            with Horizontal(id="modal-buttons"):
                yield Button(f"Confirm {self.side}", variant="success" if self.side == "BUY" else "error", id="confirm-btn")
                yield Button("Cancel (Esc)", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#qty-input", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#cancel-btn")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#confirm-btn")
    @on(Input.Submitted)
    def handle_confirm(self) -> None:
        try:
            qty = int(self.query_one("#qty-input", Input).value.strip())
            price = float(self.query_one("#price-input", Input).value.strip())
            note = self.query_one("#note-input", Input).value.strip()
        except ValueError:
            self.notify("Please enter a valid integer quantity and numeric price.", severity="error")
            return

        self.dismiss(
            {
                "side": self.side,
                "symbol": self.symbol,
                "quantity": qty,
                "price": price,
                "note": note,
            }
        )


# =====================================================================
# MODAL 2: AUTOMATED BUY / SELL RULE DIALOG
# =====================================================================
class AutoRuleModal(ModalScreen[dict[str, Any] | None]):
    """Popup modal for configuring automated buy/sell rules for a stock."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, symbol: str, latest_price: float, current_rule: dict[str, Any]) -> None:
        super().__init__()
        self.symbol = symbol
        self.latest_price = latest_price
        self.rule = current_rule

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Label(f"AUTO-TRADER CONFIG — {self.symbol} (LTP: ₹{self.latest_price:,.2f})", id="modal-title")
            yield Checkbox("Enable Automated Buying & Selling for this Stock", value=bool(self.rule["enabled"]), id="chk-enabled")
            yield Checkbox("Enable SMA(5) / SMA(15) Crossover Auto-Signals", value=bool(self.rule["use_sma_crossover"]), id="chk-sma")
            yield Label("Order Quantity per Auto-Trade:")
            yield Input(value=str(self.rule["trade_qty"]), id="auto-qty")
            yield Label("Auto-BUY when price drops at or below (₹, 0 = disabled):")
            yield Input(value=str(self.rule["buy_below_price"]), id="auto-buy")
            yield Label("Auto-SELL (Take Profit) when price rises at or above (₹, 0 = disabled):")
            yield Input(value=str(self.rule["sell_above_price"]), id="auto-sell")
            yield Label("Auto-SELL (Stop Loss) when price falls at or below (₹, 0 = disabled):")
            yield Input(value=str(self.rule["stop_loss_price"]), id="auto-sl")
            with Horizontal(id="modal-buttons"):
                yield Button("Save Auto-Rule", variant="primary", id="save-btn")
                yield Button("Cancel (Esc)", variant="default", id="cancel-btn")

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#cancel-btn")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save-btn")
    def handle_save(self) -> None:
        try:
            qty = int(self.query_one("#auto-qty", Input).value.strip() or "1")
            buy_below = float(self.query_one("#auto-buy", Input).value.strip() or "0")
            sell_above = float(self.query_one("#auto-sell", Input).value.strip() or "0")
            stop_loss = float(self.query_one("#auto-sl", Input).value.strip() or "0")
        except ValueError:
            self.notify("Numeric values required for prices and quantity.", severity="error")
            return

        self.dismiss(
            {
                "symbol": self.symbol,
                "enabled": self.query_one("#chk-enabled", Checkbox).value,
                "use_sma_crossover": self.query_one("#chk-sma", Checkbox).value,
                "trade_qty": qty,
                "buy_below_price": buy_below,
                "sell_above_price": sell_above,
                "stop_loss_price": stop_loss,
            }
        )


# =====================================================================
# MODAL 3: ADD / REMOVE WATCHLIST SYMBOL
# =====================================================================
class WatchlistModal(ModalScreen[tuple[str, str] | None]):
    """Popup modal to add or remove a yfinance ticker symbol."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Label("MANAGE WATCHLIST SYMBOL", id="modal-title")
            yield Label("Enter Yahoo Finance Symbol (e.g. TATAMOTORS.NS, ITC.NS, AAPL, NVDA):")
            yield Input(placeholder="TATAMOTORS.NS", id="sym-input")
            with Horizontal(id="modal-buttons"):
                yield Button("Add Symbol", variant="success", id="add-btn")
                yield Button("Remove Symbol", variant="error", id="rem-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#sym-input", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#cancel-btn")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#add-btn")
    @on(Input.Submitted)
    def handle_add(self) -> None:
        sym = self.query_one("#sym-input", Input).value.strip().upper()
        if sym:
            self.dismiss(("ADD", sym))

    @on(Button.Pressed, "#rem-btn")
    def handle_remove(self) -> None:
        sym = self.query_one("#sym-input", Input).value.strip().upper()
        if sym:
            self.dismiss(("REMOVE", sym))


# =====================================================================
# TABLE COLUMN DEFINITIONS (key, label)
# =====================================================================
WATCHLIST_COLS = [
    ("symbol", "Symbol"),
    ("ltp", "Latest (₹)"),
    ("chg", "Chg %"),
    ("high", "Day High"),
    ("low", "Day Low"),
    ("auto", "Auto"),
]
POSITION_COLS = [
    ("symbol", "Symbol"),
    ("qty", "Qty"),
    ("avg", "Bought Avg"),
    ("ltp", "LTP"),
    ("upnl", "Unrealized P&L"),
    ("upct", "P&L %"),
]
TRADE_COLS = [
    ("id", "ID"),
    ("time", "Time (UTC)"),
    ("symbol", "Symbol"),
    ("side", "Side"),
    ("mode", "Mode"),
    ("qty", "Qty"),
    ("bought", "Bought @"),
    ("traded", "Traded @"),
    ("pnl", "Realized P&L"),
]


# =====================================================================
# MAIN APPLICATION: MARKETKERNEL TUI
# =====================================================================
class MarketKernelApp(App[None]):
    """Main navigable TUI for MarketKernel."""

    TITLE = "MarketKernel — Live yfinance Manual & Auto Trading Simulator"
    CSS = """
    Screen {
        background: #0b0f19;
        color: #e2e8f0;
    }
    OrderModal, AutoRuleModal, WatchlistModal {
        align: center middle;
        background: #000000 60%;
    }
    #summary-bar {
        height: 3;
        background: #111827;
        border: solid #1e293b;
        padding: 0 2;
        content-align: left middle;
        text-style: bold;
    }
    #main-grid {
        grid-size: 2 1;
        grid-columns: 44% 56%;
        height: 1fr;
    }
    #left-pane, #right-pane {
        height: 100%;
        padding: 0 1;
    }
    .panel-title {
        background: #1e293b;
        color: #38bdf8;
        padding: 0 1;
        text-style: bold;
        width: 100%;
    }
    #watchlist-table {
        height: 1fr;
        border: solid #334155;
    }
    #positions-table {
        height: 1fr;
        border: solid #334155;
    }
    #chart-box {
        height: 22;
        border: solid #334155;
    }
    #auto-banner {
        height: 2;
        background: #172554;
        color: #93c5fd;
        padding: 0 1;
        content-align: left middle;
    }
    #trades-table {
        height: 1fr;
        border: solid #334155;
    }
    #modal-box {
        width: 68;
        height: auto;
        max-height: 95%;
        overflow-y: auto;
        background: #0f172a;
        border: thick #38bdf8;
        padding: 1 2;
    }
    #modal-title {
        text-style: bold;
        color: #38bdf8;
        margin-bottom: 1;
    }
    #modal-buttons {
        margin-top: 1;
        height: auto;
    }
    Button {
        margin-right: 2;
    }
    """

    BINDINGS = [
        Binding("b", "manual_buy", "Buy Stock"),
        Binding("s", "manual_sell", "Sell Stock"),
        Binding("a", "config_auto", "Auto-Rule"),
        Binding("w", "manage_watchlist", "+/- Symbol"),
        Binding("c", "cycle_chart", "Chart Mode"),
        Binding("r", "refresh_now", "Refresh Data"),
        Binding("1", "timeframe('1')", "1m Chart"),
        Binding("2", "timeframe('2')", "5m Chart"),
        Binding("3", "timeframe('3')", "1D Chart"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.db = Database()
        self.engine = TradingEngine(self.db)
        self.feed = MarketDataFeed()
        self.active_symbol: str = "RELIANCE.NS"
        self.preset_key: str = "1"
        self.chart_mode_idx: int = 0
        self._polling: bool = False
        self._poll_again: bool = False
        self._chart_gen: int = 0

    # -----------------------------------------------------------------
    # Layout
    # -----------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Initializing MarketKernel...", id="summary-bar")
        with Grid(id="main-grid"):
            with Vertical(id="left-pane"):
                yield Label("WATCHLIST (Up/Down to select stock)", classes="panel-title")
                yield DataTable(id="watchlist-table", cursor_type="row", zebra_stripes=True)
                yield Label("OPEN POSITIONS (Holdings & Unrealized Profit)", classes="panel-title")
                yield DataTable(id="positions-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="right-pane"):
                yield PriceChart(id="chart-box")
                yield Static(id="auto-banner")
                yield Label("TRADE LEDGER (Recorded Buys, Sells & Realized Profit)", classes="panel-title")
                yield DataTable(id="trades-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        wl = self.db.get_watchlist()
        if wl:
            self.active_symbol = wl[0]

        for table_id, cols in (
            ("#watchlist-table", WATCHLIST_COLS),
            ("#positions-table", POSITION_COLS),
            ("#trades-table", TRADE_COLS),
        ):
            table = self.query_one(table_id, DataTable)
            for key, label in cols:
                table.add_column(label, key=key)

        self.query_one("#watchlist-table", DataTable).focus()
        self.refresh_tables()
        self.update_chart_view()
        self.poll_market_data()
        # Poll yfinance automatically every 10 seconds (skipped if a poll is still running)
        self.set_interval(10.0, self._interval_poll)

    # =====================================================================
    # BACKGROUND YFINANCE POLLING & AUTO-TRADER EXECUTION
    # =====================================================================
    def _interval_poll(self) -> None:
        if not self._polling:
            self.poll_market_data()

    def poll_market_data(self) -> None:
        """Request a poll. Never overlaps: if one is running, it re-runs once when done."""
        if self._polling:
            self._poll_again = True
            return
        self._polling = True
        self._poll_worker()

    @work(group="poll", exit_on_error=False)
    async def _poll_worker(self) -> None:
        try:
            while True:
                self._poll_again = False
                try:
                    await self._poll_once()
                except Exception as exc:
                    self.notify(f"Polling error: {exc}", severity="error")
                if not self._poll_again:
                    break
        finally:
            self._polling = False

    def _symbols_to_poll(self) -> list[str]:
        symbols = self.db.get_watchlist()
        extras = [p["symbol"] for p in self.db.get_positions()]
        extras += [r["symbol"] for r in self.db.get_all_enabled_rules()]
        for sym in extras:
            if sym not in symbols:
                symbols.append(sym)
        return symbols

    async def _poll_once(self) -> None:
        symbols = self._symbols_to_poll()
        await asyncio.to_thread(
            self.feed.fetch_all, symbols, self.active_symbol, self.preset_key
        )

        # Evaluate automated buy/sell rules against fresh (non-stale) quote data only
        for rule in self.db.get_all_enabled_rules():
            sym = rule["symbol"]
            snap = self.feed.quote(sym)
            if snap is None or snap.latest_price <= 0 or snap.error:
                continue
            for res in self.engine.evaluate_auto_rules(sym, snap.latest_price, snap.closes):
                self.notify(res.message, title="AUTO-TRADE EXECUTED", severity="information")

        self.refresh_tables()
        self.update_chart_view()

    @work(exclusive=True, group="chart", exit_on_error=False)
    async def fetch_active_chart(self) -> None:
        """Fetch bars for the active symbol/timeframe on demand (cancellable)."""
        sym, key = self.active_symbol, self.preset_key
        await asyncio.to_thread(self.feed.fetch_symbol, sym, key)
        if sym == self.active_symbol and key == self.preset_key:
            self.update_chart_view()

    # =====================================================================
    # UI RENDERING & SYNCHRONIZATION
    # =====================================================================
    def _sync_table(
        self,
        table: DataTable,
        rows: list[tuple[str, list[Any]]],
        select_key: str | None = None,
        update_cells: bool = True,
    ) -> None:
        """Update a DataTable in place; rebuild only if its row keys changed."""
        new_keys = [key for key, _ in rows]
        old_keys = [str(row_key.value) for row_key in table.rows]

        if new_keys == old_keys:
            if update_cells:
                col_keys = list(table.columns.keys())
                for row_key, cells in rows:
                    for col_key, value in zip(col_keys, cells):
                        table.update_cell(row_key, col_key, value, update_width=True)
            return

        previous_cursor = table.cursor_row
        table.clear()
        for row_key, cells in rows:
            table.add_row(*cells, key=row_key)

        if select_key is not None and select_key in new_keys:
            table.move_cursor(row=new_keys.index(select_key), animate=False)
        elif 0 <= previous_cursor < len(new_keys):
            table.move_cursor(row=previous_cursor, animate=False)

    def refresh_tables(self) -> None:
        """Refresh watchlist, positions, trade ledger and the summary bar (no chart)."""
        acct = self.db.get_account()
        cash = float(acct["cash_balance"])
        positions = self.db.get_positions()
        realized_pnl = self.db.get_total_realized_pnl()
        enabled_symbols = self.db.get_enabled_symbols()

        # 1. Watchlist
        wl_rows: list[tuple[str, list[Any]]] = []
        for sym in self.db.get_watchlist():
            snap = self.feed.quote(sym)
            auto_tag = Text("ON", style="bold green") if sym in enabled_symbols else Text("OFF", style="dim")
            if snap and snap.latest_price > 0:
                chg_color = "green" if snap.change_pct >= 0 else "red"
                sign = "+" if snap.change_pct >= 0 else ""
                wl_rows.append(
                    (
                        sym,
                        [
                            sym,
                            f"₹{snap.latest_price:,.2f}",
                            Text(f"{sign}{snap.change_pct:.2f}%", style=chg_color),
                            f"₹{snap.high:,.2f}",
                            f"₹{snap.low:,.2f}",
                            auto_tag,
                        ],
                    )
                )
            else:
                placeholder = "No data" if (snap and snap.error) else "Fetching..."
                wl_rows.append((sym, [sym, placeholder, "-", "-", "-", auto_tag]))
        self._sync_table(
            self.query_one("#watchlist-table", DataTable),
            wl_rows,
            select_key=self.active_symbol,
        )

        # 2. Open positions & portfolio totals
        pos_rows: list[tuple[str, list[Any]]] = []
        invested_cost = 0.0
        current_market_value = 0.0

        for pos in positions:
            sym = pos["symbol"]
            qty = int(pos["quantity"])
            avg_buy = float(pos["avg_buy_price"])

            snap = self.feed.quote(sym)
            ltp = snap.latest_price if (snap and snap.latest_price > 0) else avg_buy

            cost = qty * avg_buy
            mkt_val = qty * ltp
            unrealized = mkt_val - cost
            unrealized_pct = ((ltp - avg_buy) / avg_buy * 100.0) if avg_buy > 0 else 0.0

            invested_cost += cost
            current_market_value += mkt_val

            pnl_style = "bold green" if unrealized >= 0 else "bold red"
            sign = "+" if unrealized >= 0 else ""
            pos_rows.append(
                (
                    sym,
                    [
                        sym,
                        str(qty),
                        f"₹{avg_buy:,.2f}",
                        f"₹{ltp:,.2f}",
                        Text(f"{sign}₹{unrealized:,.2f}", style=pnl_style),
                        Text(f"{sign}{unrealized_pct:.2f}%", style=pnl_style),
                    ],
                )
            )
        self._sync_table(self.query_one("#positions-table", DataTable), pos_rows)

        # 3. Summary bar
        total_unrealized = current_market_value - invested_cost
        net_worth = cash + current_market_value
        u_sign = "+" if total_unrealized >= 0 else ""
        r_sign = "+" if realized_pnl >= 0 else ""
        self.query_one("#summary-bar", Static).update(
            f"NET WORTH: ₹{net_worth:,.2f}  |  CASH: ₹{cash:,.2f}  |  "
            f"INVESTED: ₹{invested_cost:,.2f}  |  UNREALIZED P&L: {u_sign}₹{total_unrealized:,.2f}  |  "
            f"REALIZED PROFIT: {r_sign}₹{realized_pnl:,.2f}"
        )

        # 4. Trade ledger (rows are immutable once written: only rebuild when a new trade appears)
        tr_rows: list[tuple[str, list[Any]]] = []
        for tr in self.db.get_trades(limit=60):
            side = tr["side"]
            side_text = Text(side, style="bold cyan" if side == "BUY" else "bold yellow")
            pnl = float(tr["realized_pnl"])
            if side == "SELL":
                p_sign = "+" if pnl >= 0 else ""
                pnl_text = Text(f"{p_sign}₹{pnl:,.2f}", style="bold green" if pnl >= 0 else "bold red")
                bought_at_str = f"₹{float(tr['buy_avg_at_sale']):,.2f}"
            else:
                pnl_text = Text("-", style="dim")
                bought_at_str = f"₹{float(tr['trade_price']):,.2f}"

            tr_rows.append(
                (
                    str(tr["id"]),
                    [
                        str(tr["id"]),
                        tr["timestamp"][5:],  # MM-DD HH:MM:SS
                        tr["symbol"],
                        side_text,
                        tr["mode"],
                        str(tr["quantity"]),
                        bought_at_str,
                        f"₹{float(tr['trade_price']):,.2f}",
                        pnl_text,
                    ],
                )
            )
        self._sync_table(
            self.query_one("#trades-table", DataTable), tr_rows, update_cells=False
        )

    def update_chart_view(self) -> None:
        """Redraw the chart + auto-rule banner for the active symbol."""
        sym = self.active_symbol
        snap = self.feed.chart(sym, self.preset_key)
        pos = self.db.get_position(sym)
        avg_buy = float(pos["avg_buy_price"]) if pos else 0.0
        rule = self.db.get_auto_rule(sym)
        mode_key, mode_label = CHART_MODES[self.chart_mode_idx]

        self.query_one("#chart-box", PriceChart).show(
            snap=snap,
            preset_key=self.preset_key,
            mode=mode_key,
            avg_buy_price=avg_buy,
            auto_rule=rule,
        )

        banner = self.query_one("#auto-banner", Static)
        if rule["enabled"]:
            banner.update(
                f"AUTO-TRADER [{sym}]: ENABLED | Qty: {rule['trade_qty']} | "
                f"Buy <= ₹{rule['buy_below_price']:,.2f} | "
                f"Take Profit >= ₹{rule['sell_above_price']:,.2f} | "
                f"Stop Loss <= ₹{rule['stop_loss_price']:,.2f} | "
                f"SMA Cross: {'ON' if rule['use_sma_crossover'] else 'OFF'} | "
                f"Chart: {mode_label} ('c' to switch)"
            )
        else:
            banner.update(
                f"AUTO-TRADER [{sym}]: DISABLED (Press 'a' to configure) | "
                f"Chart: {mode_label} ('c' to switch)"
            )

    # =====================================================================
    # NAVIGATION & KEYBOARD ACTIONS
    # =====================================================================
    def schedule_chart_update(self) -> None:
        """Debounce rapid cursor movement so holding Up/Down stays smooth."""
        self._chart_gen += 1
        gen = self._chart_gen
        self.set_timer(0.06, lambda: self._on_cursor_settled(gen))

    def _on_cursor_settled(self, gen: int) -> None:
        if gen != self._chart_gen:
            return
        self.update_chart_view()
        if self.feed.chart(self.active_symbol, self.preset_key) is None:
            self.fetch_active_chart()

    @on(DataTable.RowHighlighted, "#watchlist-table")
    def on_watchlist_cursor_move(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        new_sym = str(event.row_key.value)
        if new_sym != self.active_symbol:
            self.active_symbol = new_sym
            self.schedule_chart_update()

    @on(DataTable.RowSelected, "#positions-table")
    def on_position_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        sym = str(event.row_key.value)
        self.active_symbol = sym
        wl = self.db.get_watchlist()
        if sym in wl:
            self.query_one("#watchlist-table", DataTable).move_cursor(
                row=wl.index(sym), animate=False
            )
        self.schedule_chart_update()

    def action_timeframe(self, key: str) -> None:
        self.preset_key = key
        self.notify(f"Switched chart timeframe to preset #{key}. Fetching bars...", timeout=2)
        self.update_chart_view()
        self.fetch_active_chart()

    def action_cycle_chart(self) -> None:
        self.chart_mode_idx = (self.chart_mode_idx + 1) % len(CHART_MODES)
        _, label = CHART_MODES[self.chart_mode_idx]
        self.notify(f"Chart mode: {label}", timeout=2)
        self.update_chart_view()

    def action_refresh_now(self) -> None:
        self.notify("Polling latest data from yfinance...", timeout=2)
        self.poll_market_data()
        self.fetch_active_chart()

    def _order_context(self) -> tuple[float, dict[str, Any], int, float]:
        snap = self.feed.quote(self.active_symbol)
        ltp = snap.latest_price if snap else 0.0
        acct = self.db.get_account()
        pos = self.db.get_position(self.active_symbol)
        held = int(pos["quantity"]) if pos else 0
        avg_buy = float(pos["avg_buy_price"]) if pos else 0.0
        return ltp, acct, held, avg_buy

    def _after_order(self, res: Any) -> None:
        self.notify(res.message, severity="information" if res.success else "error")
        self.refresh_tables()
        self.update_chart_view()

    def action_manual_buy(self) -> None:
        ltp, acct, held, avg_buy = self._order_context()
        if ltp <= 0:
            self.notify("No live price yet for this symbol. Wait for data, then retry.", severity="warning")
            return

        def _on_order_close(data: dict[str, Any] | None) -> None:
            if not data:
                return
            res = self.engine.buy(
                symbol=data["symbol"],
                quantity=data["quantity"],
                price=data["price"],
                mode="MANUAL",
                note=data["note"],
            )
            self._after_order(res)

        self.push_screen(
            OrderModal("BUY", self.active_symbol, ltp, float(acct["cash_balance"]), held, avg_buy),
            _on_order_close,
        )

    def action_manual_sell(self) -> None:
        ltp, acct, held, avg_buy = self._order_context()
        if ltp <= 0:
            self.notify("No live price yet for this symbol. Wait for data, then retry.", severity="warning")
            return

        def _on_order_close(data: dict[str, Any] | None) -> None:
            if not data:
                return
            res = self.engine.sell(
                symbol=data["symbol"],
                quantity=data["quantity"],
                price=data["price"],
                mode="MANUAL",
                note=data["note"],
            )
            self._after_order(res)

        self.push_screen(
            OrderModal("SELL", self.active_symbol, ltp, float(acct["cash_balance"]), held, avg_buy),
            _on_order_close,
        )

    def action_config_auto(self) -> None:
        snap = self.feed.quote(self.active_symbol)
        ltp = snap.latest_price if snap else 0.0
        rule = self.db.get_auto_rule(self.active_symbol)

        def _on_rule_close(data: dict[str, Any] | None) -> None:
            if not data:
                return
            self.db.upsert_auto_rule(
                symbol=data["symbol"],
                enabled=data["enabled"],
                buy_below_price=data["buy_below_price"],
                sell_above_price=data["sell_above_price"],
                stop_loss_price=data["stop_loss_price"],
                use_sma_crossover=data["use_sma_crossover"],
                trade_qty=data["trade_qty"],
            )
            state = "ENABLED" if data["enabled"] else "DISABLED"
            self.notify(f"Auto-Trader for {data['symbol']} is now {state}.")
            self.refresh_tables()
            self.update_chart_view()
            self.poll_market_data()

        self.push_screen(AutoRuleModal(self.active_symbol, ltp, rule), _on_rule_close)

    def action_manage_watchlist(self) -> None:
        def _on_wl_close(res: tuple[str, str] | None) -> None:
            if not res:
                return
            action, sym = res
            if action == "ADD":
                self.db.add_to_watchlist(sym)
                self.active_symbol = sym
                self.notify(f"Added {sym} to watchlist. Fetching data...")
            elif action == "REMOVE":
                self.db.remove_from_watchlist(sym)
                wl = self.db.get_watchlist()
                if self.active_symbol == sym and wl:
                    self.active_symbol = wl[0]
                self.notify(f"Removed {sym} from watchlist.")
            self.refresh_tables()
            self.update_chart_view()
            self.poll_market_data()
            self.fetch_active_chart()

        self.push_screen(WatchlistModal(), _on_wl_close)
