# MarketKernel — Complete Walkthrough

MarketKernel is a **terminal-based stock trading simulator** built with Textual. It streams
quotes and OHLC bars from Yahoo Finance through `yfinance`, lets you place simulated manual
trades, and can execute automated buy/sell rules every time it polls the market.

It is a **simulator only**:

- No real broker connection is made.
- No real money moves.
- No commissions, taxes, slippage, or bid/ask spread are applied.
- Prices come from Yahoo Finance and may be delayed, incomplete, or unavailable.
- All state is stored locally in `marketkernel.db`.

---

## 1. Starting the application

Always launch from the project root, because `marketkernel.db` is created relative to the
current working directory.

```powershell
cd E:\Dev\MarketKernel
.\.venv\Scripts\Activate.ps1
python main.py
```

You can also run it without activating the environment:

```powershell
E:\Dev\MarketKernel\.venv\Scripts\python.exe E:\Dev\MarketKernel\main.py
```

On first launch the database is seeded with:

- Starting cash: **₹100,000.00**
- Watchlist: `RELIANCE.NS`, `TCS.NS`, `INFY.NS`, `HDFCBANK.NS`, `SBIN.NS`
- No positions, no trades, no auto-rules

---

## 2. Screen layout

```text
┌─ Header (title + clock) ─────────────────────────────────────────────┐
├─ Summary bar: net worth, cash, invested, unrealized, realized ───────┤
│                                                                      │
│  WATCHLIST                           PRICE CHART                    │
│  (all tracked symbols)               (line / candles / OHLC bars)   │
│                                                                      │
│  OPEN POSITIONS                      AUTO-TRADER BANNER              │
│  (your current holdings)             (rule status for active stock)  │
│                                                                      │
│                                      TRADE LEDGER                   │
│                                      (permanent buy/sell history)    │
│                                                                      │
└─ Footer (available keyboard shortcuts) ──────────────────────────────┘
```

The **active symbol** is the symbol currently highlighted in the Watchlist. All actions —
manual buy/sell, auto-rule configuration, and the large chart — apply to that symbol.

---

## 3. Keyboard shortcuts

These shortcuts are handled by the main screen. While a modal dialog is open, typing goes
into that dialog and `Esc` cancels it.

| Key | Footer label | Exact meaning |
|---|---|---|
| `b` | Buy Stock | Opens the **manual BUY** dialog for the active symbol. |
| `s` | Sell Stock | Opens the **manual SELL** dialog for the active symbol. |
| `a` | Auto-Rule | Opens the **Auto-Trader configuration** dialog for the active symbol. |
| `w` | +/- Symbol | Opens the **watchlist manager** to add or remove a Yahoo Finance symbol. |
| `c` | Chart Mode | Cycles the chart through `Line + SMA(5/15)` → `Candlesticks` → `OHLC Bars` → back to line. |
| `r` | Refresh Data | Immediately requests a quote refresh and re-fetches the active chart timeframe. |
| `1` | 1m Chart | Switches the chart to **1-day / 1-minute bars** (intraday). |
| `2` | 5m Chart | Switches the chart to **5-day / 5-minute bars**. |
| `3` | 1D Chart | Switches the chart to **3-month / 1-day bars**. |
| `q` | Quit | Closes the application. Trades are already saved. |
| `↑` / `↓` | — | Moves the Watchlist cursor. The chart follows after a 60 ms pause. |
| `Enter` | — | On a row in **Open Positions**, makes that symbol active. |
| `Tab` | — | Moves focus between fields/buttons inside a dialog. |
| `Esc` | Cancel | Closes the current dialog without applying changes. |
| `Enter` | — | Submits the focused input. In the Buy/Sell dialog this confirms the order; in the Watchlist dialog it adds the symbol. The Auto-Rule dialog must be saved with its button. |

The currently selected chart mode is remembered while you change symbols or timeframes.

---

## 4. Summary bar

The top bar always shows the portfolio in rupees:

| Label | Formula / meaning |
|---|---|
| **NET WORTH** | `cash_balance + current market value of all open positions` |
| **CASH** | Uninvested simulated cash. Starts at ₹100,000 and changes only when you buy or sell. |
| **INVESTED** | `Σ (position quantity × position average buy price)` — your cost basis. |
| **UNREALIZED P&L** | `current market value − invested`. Profit/loss on shares you still hold. |
| **REALIZED PROFIT** | Sum of `realized_pnl` across every SELL trade ever recorded. |

If a position has no usable live quote, its **LTP falls back to its average buy price**, so
that position temporarily contributes zero unrealized P&L rather than a fake value.

---

## 5. Watchlist panel

Each row represents one Yahoo Finance ticker.

| Column | Exact meaning |
|---|---|
| **Symbol** | The Yahoo Finance ticker, e.g. `RELIANCE.NS`, `TCS.NS`, `AAPL`. |
| **Latest (₹)** | Last close of the current quote snapshot: 1-minute bars when available, otherwise the 5-minute / 5-day fallback. |
| **Chg %** | `(latest close − first open of the fetched window) / first open × 100`. This is **not** guaranteed to be the official previous-day change; it is the change across the bars returned for the quote window. Green when ≥ 0, red when < 0. |
| **Day High** | Highest high in the quote window. With the intraday quote it is normally the current day; after the 5-day fallback it can span five days. |
| **Day Low** | Lowest low in the same quote window. |
| **Auto** | `ON` if an auto-rule exists for that symbol with **Enable** checked, even if all thresholds are still zero. `OFF` otherwise. |

Placeholder states:

- **Fetching...** — no snapshot has been received yet.
- **No data** — Yahoo Finance returned an error or no bars, and nothing usable is cached.

A quote snapshot with an error but previously fetched bars keeps showing the last prices.
The chart labels this as **STALE**; auto-trading skips it.

Moving the cursor changes the active symbol. The chart update is debounced by 60 ms so
holding `↓` or `↑` stays smooth.

---

## 6. Open Positions panel

Only positions with quantity greater than zero appear here.

| Column | Exact meaning |
|---|---|
| **Symbol** | Ticker of the held stock. |
| **Qty** | Whole number of shares currently held. |
| **Bought Avg** | Weighted average cost of the shares still held. It changes **only on buys**, never on sells. |
| **LTP** | Latest price (same quote snapshot as the Watchlist). Falls back to Bought Avg if no quote is available. |
| **Unrealized P&L** | `(LTP − Bought Avg) × Qty`. Green when ≥ 0, red when < 0. |
| **P&L %** | `(LTP − Bought Avg) / Bought Avg × 100`. |

Press `Enter` on a position to make it the active symbol and follow it on the chart. If it
is also in the Watchlist, the cursor moves to its row.

### Weighted average example

| Action | Cash | Position | Average |
|---|---:|---|---:|
| Start | ₹100,000 | — | — |
| Buy 10 @ ₹3,500 | ₹65,000 | 10 | ₹3,500.00 |
| Buy 10 @ ₹3,300 | ₹32,000 | 20 | `(10×3500 + 10×3300) / 20 = ₹3,400.00` |
| Price rises to ₹3,600 | ₹32,000 | 20 | Unrealized: `(3600−3400)×20 = +₹4,000` |
| Sell 15 @ ₹3,600 | ₹86,000 | 5 | Realized: `(3600−3400)×15 = +₹3,000`; average stays ₹3,400.00 |

A partial sell **does not** change the average buy price. Selling the entire quantity
removes the position row.

---

## 7. Price chart

### 7.1 Chart timeframes

| Key | Timeframe | Yahoo parameters | Label on chart |
|---|---|---|---|
| `1` | 1-minute intraday | period `1d`, interval `1m` | Intraday (1-Min Bars) |
| `2` | 5-minute bars over 5 days | period `5d`, interval `5m` | 5-Day (5-Min Bars) |
| `3` | Daily bars over 3 months | period `3mo`, interval `1d` | 3-Month (Daily Bars) |

If the 1-minute request is empty (pre-market, holiday, or Yahoo limitation), preset `1`
automatically retries with `5d` / `5m` bars. The chart title still describes it as the
intraday preset.

Changing the chart timeframe **does not** change the quote used by the Watchlist, Positions,
or Auto-Trader. Those always use the latest 1-minute quote snapshot (with its fallback).

The chart is fetched on demand when you select a new symbol or press `1`, `2`, or `3`; the
fetch runs in the background and can be superseded by a newer selection. Up to **60 bars**
are cached, and each mode draws a slightly shorter tail:

| Mode | Bars drawn |
|---|---:|
| Line | 60 |
| Candlesticks | 45 |
| OHLC bars | 40 |

### 7.2 Chart modes (`c`)

| Mode | What is drawn |
|---|---|
| **Line + SMA(5/15)** | Close-price line, plus a cyan SMA(5) and a magenta SMA(15). The line is green when the window change is ≥ 0, red otherwise. |
| **Candlesticks** | Classic OHLC candles on a date-time axis. Up/down candles are colored by the plotting library's up/down palette. |
| **OHLC Bars** | A vertical high–low stem for each bar, a left tick at the open, and a right tick at the close. Green when close ≥ open, red when close < open. |

SMA means **simple moving average of closes**. SMA(5) is drawn only when at least 5 bars are
available; SMA(15) only when at least 15 are available.

### 7.3 Horizontal reference lines

| Color | Meaning | When shown |
|---|---|---|
| **Yellow** | Your Bought Avg price for the active symbol | Only while you hold shares |
| **Blue** | Auto-Buy trigger (`Buy <=`) | Only when the rule is enabled and the value is greater than 0 |
| **Green** | Take-Profit trigger (`Sell >=`) | Only when the rule is enabled and the value is greater than 0 |
| **Red** | Stop-Loss trigger (`Sell <=`) | Only when the rule is enabled and the value is greater than 0 |

Because the auto-rule and average are drawn on the same price scale, they let you see at a
glance where your entry and exits sit relative to current prices.

### 7.4 Chart title

Example:

```text
RELIANCE.NS ₹1,202.00 (-0.84%) | Intraday (1-Min Bars) | Line + SMA(5/15) | Bought Avg: ₹1,180.00 | Updated 22:50:30
```

- `₹...` is the latest close.
- `(...)` is the same window change shown by the Watchlist.
- `Bought Avg` appears only when a position exists.
- `STALE` appears when the latest fetch failed but old bars are still cached.
- `Updated` is the local wall-clock time of the fetch.
- If plotting fails for any reason, the chart title shows `Chart error (...)` instead of
  crashing the application.

---

## 8. Auto-Trader banner

The blue strip under the chart summarizes the active symbol's rule.

When enabled:

```text
AUTO-TRADER [TCS.NS]: ENABLED | Qty: 5 | Buy <= ₹3,300.00 |
Take Profit >= ₹3,700.00 | Stop Loss <= ₹3,150.00 | SMA Cross: ON | Chart: Candlesticks ('c' to switch)
```

When disabled:

```text
AUTO-TRADER [TCS.NS]: DISABLED (Press 'a' to configure) | Chart: Line + SMA(5/15) ('c' to switch)
```

`ENABLED` means the rule participates in every poll. It does **not** mean a trade will
happen; at least one trigger (including the SMA crossover, if selected) must be met.

---

## 9. Trade Ledger panel

Every buy and sell is written permanently to SQLite. The 60 newest rows are shown, newest
first.

| Column | Exact meaning |
|---|---|
| **ID** | Auto-increment trade ID from the database. |
| **Time (UTC)** | Trade timestamp stored in UTC, displayed as `MM-DD HH:MM:SS` (the year is omitted for space). |
| **Symbol** | Ticker traded. |
| **Side** | `BUY` (cyan) or `SELL` (yellow). |
| **Mode** | `MANUAL` for a dialog order, `AUTO` for an engine trigger. |
| **Qty** | Whole shares traded. |
| **Bought @** | On a **SELL**: the average buy price at the moment of sale. On a **BUY**: the new weighted average after that purchase. |
| **Traded @** | The execution price used for this trade. |
| **Realized P&L** | On a **SELL**: `(Traded @ − Bought @) × Qty`, green for profit, red for loss. On a **BUY**: `-` because no profit is realized yet. |

The optional trade note is stored in the database but not displayed in the ledger.

---

## 10. Manual BUY (`b`)

Pressing `b` opens:

```text
MANUAL BUY — RELIANCE.NS
Latest Market Price (yfinance): ₹1,202.00
Available Cash: ₹100,000.00 (Max Buy: 83 shares)

Quantity (Shares):        [1]
Execution Price:          [1202.00]
Trade Note (Optional):    [...]
[Confirm BUY] [Cancel (Esc)]
```

| Field / item | Exact meaning |
|---|---|
| **Latest Market Price** | The LTP from the quote snapshot. If there is no live price, the dialog will not open; a warning asks you to wait or refresh. |
| **Available Cash** | Current cash balance. |
| **Max Buy** | `floor(cash / latest market price)`. It is only a hint and uses the displayed LTP, not an overridden execution price. |
| **Quantity (Shares)** | Integer number of shares to buy. Default `1`. Must be greater than 0. Fractional shares are not supported. |
| **Execution Price** | Price actually used by the engine. It defaults to the LTP and may be overridden. This lets you simulate a fill at a different price, but the app does **not** validate it against the market. |
| **Trade Note (Optional)** | Free text saved with the trade (`note` column in the database). It is not shown in the ledger. |
| **Confirm BUY** | Executes the order. Pressing `Enter` in any field also confirms. |
| **Cancel (Esc)** | Closes without trading. |

On success the engine, in one SQLite transaction:

1. Deducts `quantity × execution price` from cash.
2. Creates or updates the position.
3. Recomputes the weighted average:
   `new_avg = (old_qty × old_avg + qty × price) / (old_qty + qty)`.
4. Writes a `BUY` row to the trade ledger with mode `MANUAL`.

Possible errors:

- `Quantity must be greater than 0.`
- `Invalid market price (0) for SYMBOL.`
- `Insufficient cash! Need ₹..., have ₹....`
- Invalid number entered in the dialog.

---

## 11. Manual SELL (`s`)

Pressing `s` opens the same dialog in SELL mode:

```text
MANUAL SELL — RELIANCE.NS
Latest Market Price (yfinance): ₹1,202.00
Currently Holding: 10 shares | Bought Avg: ₹1,180.00
```

| Field / item | Exact meaning |
|---|---|
| **Currently Holding** | Shares currently held, including zero. |
| **Bought Avg** | Average cost of the held shares; this is the cost basis used to calculate realized P&L. |
| **Quantity** | Shares to sell. Must be > 0 and cannot exceed the held quantity. |
| **Execution Price** | Sell price used for proceeds and realized P&L. Defaults to LTP; may be overridden. |
| **Confirm SELL** | Executes, or shows why it cannot. |

On success the engine:

1. Credits `quantity × execution price` to cash.
2. Computes `realized_pnl = (execution price − average buy price) × quantity`.
3. Reduces the position. If the remaining quantity is zero, deletes the position row.
4. **Leaves the average buy price unchanged** for any remaining shares.
5. Writes a `SELL` row with `buy_avg_at_sale`, `trade_price`, and `realized_pnl`.

Possible errors:

- `Cannot sell N shares of SYMBOL. You only hold M.`
- Quantity/price validation errors as in the BUY dialog.

---

## 12. Auto-Trader configuration (`a`)

Pressing `a` opens the rule dialog for the active symbol. A rule is stored per symbol and
survives restarts.

| Option | Exact meaning |
|---|---|
| **Enable Automated Buying & Selling for this Stock** | Master switch. If unchecked, none of the thresholds or SMA logic is evaluated. The Watchlist badge shows `OFF`. |
| **Enable SMA(5) / SMA(15) Crossover Auto-Signals** | Adds a technical trigger. Requires the master switch to be enabled. |
| **Order Quantity per Auto-Trade** | Shares used for threshold buys and partial take-profit/stop-loss sells. Minimum stored value is 1. |
| **Auto-BUY when price drops at or below (₹)** | Buy trigger. Only fires when the price is `<=` this value **and you currently hold zero shares** of the symbol. `0` disables it. |
| **Auto-SELL (Take Profit) when price rises at or above (₹)** | Sells `min(order quantity, shares held)` when price is `>=` this value and you hold shares. `0` disables it. |
| **Auto-SELL (Stop Loss) when price falls at or below (₹)** | Sells `min(order quantity, shares held)` when price is `<=` this value and you hold shares. `0` disables it. |
| **Save Auto-Rule** | Persists the rule, refreshes the banner/chart lines, and requests an immediate poll. |
| **Cancel (Esc)** | Discards changes. |

Negative prices are clamped to `0`; quantities below 1 are clamped to `1`. Empty numeric
fields are treated as `0` (quantity defaults to `1`). Non-numeric input is rejected.

### 12.1 Trigger evaluation order

On every poll, for each **enabled** rule, the engine evaluates in this exact order:

1. **Threshold BUY** — `price <= buy_below` and held quantity is 0.
2. **Take Profit** — `price >= sell_above` and held quantity > 0.
3. **Stop Loss** — `price <= stop_loss` and held quantity > 0.
4. **SMA crossover** (only if selected and at least 16 closes are available):
   - Bullish: previous SMA(5) ≤ previous SMA(15) and current SMA(5) > current SMA(15),
     and you hold zero shares → **buy `order quantity`**.
   - Bearish: previous SMA(5) ≥ previous SMA(15) and current SMA(5) < current SMA(15),
     and you hold shares → **sell the entire holding**.

The quantity changes from an earlier step affect later steps in the same pass.

### 12.2 Important behavior details

- **Auto-buy does not average down.** It only buys when the position is empty. If you
  already hold shares, a "Buy Below" trigger is ignored.
- **Take-profit and stop-loss sell partially**, limited to the order quantity. Repeat polls
  can sell more until the position is empty.
- **SMA bearish crossover sells everything**, regardless of the configured order quantity.
- **Thresholds are not mutually exclusive.** A logically inconsistent configuration (for
  example `sell_above` below `stop_loss`, or a buy target above a sell target) can cause
  both a buy and a sell in one evaluation pass. Keep targets ordered sensibly:
  `stop_loss < buy_below < current price < sell_above` is the usual intent.
- **Stop-loss can lead to re-entry.** If a stop-loss empties the position and the price is
  still at or below the Buy Below target, the next poll can buy again. This is expected
  behavior, not a bug.
- **SMA closes** come from the quote snapshot (1-minute bars, or the 5-minute fallback), not
  from the chart timeframe you are viewing. The crossover is evaluated on close-to-close
  changes between the two most recent bars.
- **Stale data is never traded.** If the latest quote fetch failed, or the price is ≤ 0,
  the rule is skipped for that poll.
- An enabled rule with every threshold at `0` and SMA signals off never trades. The `ON`
  badge only means the rule is armed for evaluation.
- Auto-trades use the current quote price as the execution price and are recorded with
  mode `AUTO`.
- Every executed auto-trade produces a toast notification with the resulting message.

### 12.3 Example rule

For `TCS.NS` with LTP ₹3,500:

```text
Enable:        ON
SMA signals:   ON
Order qty:     5
Buy below:     ₹3,300
Take profit:   ₹3,700
Stop loss:     ₹3,150
```

This means:

- If TCS trades at or below ₹3,300 and you hold none, buy 5 shares.
- If you hold TCS and it reaches ₹3,700, sell up to 5 shares.
- If you hold TCS and it falls to ₹3,150, sell up to 5 shares.
- Additionally, an SMA(5)/SMA(15) bullish crossover can buy 5 shares when flat; a bearish
  crossover sells the whole position.
- The chart draws the yellow average, blue ₹3,300 line, green ₹3,700 line, and red ₹3,150
  line.

---

## 13. Watchlist manager (`w`)

Pressing `w` opens a dialog with a single symbol field and three buttons.

| Control | Exact meaning |
|---|---|
| **Symbol input** | Yahoo Finance ticker. Input is trimmed and uppercased. |
| **Add Symbol** | Adds the symbol, makes it active, refreshes the tables, and starts fetching data. A duplicate add is silently ignored. Pressing `Enter` also adds. |
| **Remove Symbol** | Deletes the symbol from the Watchlist. If it was active, the first remaining symbol alphabetically becomes active. |
| **Cancel** | Closes without changing anything. |

Ticker examples:

- Indian NSE: `RELIANCE.NS`, `TCS.NS`, `ITC.NS`
- Indian BSE: `RELIANCE.BO`
- US: `AAPL`, `NVDA`, `MSFT`

There is no automatic suffixing: `TCS` and `TCS.NS` are different Yahoo tickers. An invalid
ticker is shown as **No data** instead of crashing the app.

Removing a symbol from the Watchlist does **not**:

- delete an open position,
- delete its auto-rule,
- delete its trade history.

Positions and enabled rules are still polled even when their symbol is not in the
Watchlist. An enabled auto-rule therefore keeps trading even after you remove its symbol
from the Watchlist. If you remove every symbol, the chart keeps the last active symbol.

---

## 14. Refresh (`r`) and automatic polling

- Market data is polled automatically every **10 seconds**.
- `r` requests an immediate poll and re-fetches the active chart timeframe.
- A poll never overlaps another poll. If a refresh is requested while one is running, exactly
  one follow-up poll is queued.
- Network fetching runs in worker threads, so the interface remains responsive.
- All symbols in the Watchlist are refreshed in parallel, along with any symbol that has an
  open position or an enabled auto-rule.
- Quote snapshots are cached per **`(symbol, timeframe)`**. The quote data used for prices,
  positions, and auto-trading is separate from the data used by chart timeframes `2` and `3`.
- Fetch errors are cached too, so an invalid symbol does not cause a tight retry loop. It is
  retried on the next normal poll.

---

## 15. Data, persistence, and reset

`marketkernel.db` is SQLite in WAL mode and contains:

| Table | Contents |
|---|---|
| `account` | Starting capital, current cash, last update time (single row, id 1). |
| `watchlist` | Tracked symbols and when they were added. |
| `positions` | Symbol, quantity, weighted average buy price, update time. |
| `trades` | Permanent ledger of every buy/sell, including mode, prices, realized P&L, and note. |
| `auto_rules` | One rule per symbol: enabled flag, thresholds, SMA flag, quantity, update time. |

Trades commit atomically: if any part of a buy or sell fails, the cash, position, and ledger
changes are rolled back together.

### Reset options

**Full reset** (cash, positions, trades, watchlist, and auto-rules): close the app, then
delete the database from the project root.

```powershell
Remove-Item marketkernel.db, marketkernel.db-wal, marketkernel.db-shm -ErrorAction SilentlyContinue
```

The next launch recreates a fresh ₹100,000 account with the default five symbols.

**Portfolio-only reset** (cash, positions, trades; keeps watchlist and auto-rules):

```powershell
python -c "from marketkernel.db import Database; Database().reset_account()"
```

There is no reset button inside the TUI.

---

## 16. Common messages and what they mean

| Message / state | Meaning |
|---|---|
| `Fetching...` | No quote snapshot has arrived yet for that symbol. |
| `No data` | Yahoo Finance returned no usable bars or an error, and there is no cached chart data. |
| `STALE` on the chart | A later fetch failed, so the previously cached bars are still displayed. Auto-trading is disabled for this symbol while stale. |
| `No live price yet for this symbol...` | You pressed `b`/`s` before a quote was available. Wait for a poll or press `r`. |
| `Insufficient cash!` | The order cost exceeds the current cash balance. |
| `Cannot sell N shares... You only hold M.` | Sell quantity exceeds the position. |
| `Quantity must be greater than 0.` | Quantity was zero or negative. |
| `Invalid market price (0) for SYMBOL.` | Execution price was zero or negative. |
| `Chart error (...)` | The plotting library rejected something; the rest of the app keeps running. |
| `AUTO-TRADE EXECUTED` toast | An auto-rule bought or sold during a poll. The ledger has the full record. |

---

## 17. Suggested first walkthrough

1. **Launch** `python main.py` and wait a few seconds for quotes.
2. **Navigate** with `↓` through the Watchlist; watch the chart follow the highlighted row.
3. **Change chart timeframe** with `2`, then `3`, then `1`.
4. **Cycle chart modes** with `c` and confirm the title/banner update.
5. **Buy** with `b`: quantity `5`, keep the default price, add a note, and confirm. Check the
   Open Positions row, the summary bar, and the yellow average line on the chart.
6. **Sell** with `s`: quantity `2`. Confirm the Trade Ledger records `Bought @`, `Traded @`,
   and the realized P&L while the average of the remaining shares stays unchanged.
7. **Configure automation** with `a`: enable the rule, set order quantity `1`, and set a Buy
   Below and Take Profit around the current price. Save and watch the banner and reference
   lines. Auto-trades appear in the ledger with mode `AUTO`.
8. **Manage symbols** with `w`: add `ITC.NS`, wait for data, then try removing it.
9. **Refresh** with `r`, then **quit** with `q` and relaunch to confirm cash, positions,
   trades, watchlist, and rules persisted.
