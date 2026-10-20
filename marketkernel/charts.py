from __future__ import annotations

from typing import Any

from textual_plotext import PlotextPlot

from marketkernel.data_feed import TIMEFRAME_PRESETS, SymbolSnapshot


# (mode key, human label) — the 'c' key cycles through this list in order.
CHART_MODES: list[tuple[str, str]] = [
    ("LINE", "Line + SMA(5/15)"),
    ("CANDLE", "Candlesticks"),
    ("OHLC", "OHLC Bars"),
]

# Max bars drawn per mode (keeps candles/bars readable in a terminal).
BARS_SHOWN: dict[str, int] = {"LINE": 60, "CANDLE": 45, "OHLC": 40}

PLOTEXT_DATE_FORM = "d/m/Y H:M:S"
UP_COLOR = "green+"
DOWN_COLOR = "red+"


def _rolling_sma(values: list[float], window: int) -> list[float]:
    result: list[float] = []
    for i in range(len(values)):
        if i + 1 < window:
            result.append(values[i])
        else:
            chunk = values[i + 1 - window : i + 1]
            result.append(round(sum(chunk) / window, 2))
    return result


def _apply_ticks(plt: Any, labels: list[str]) -> None:
    if not labels:
        return
    step = max(1, len(labels) // 6)
    positions = list(range(0, len(labels), step))
    plt.xticks(positions, [labels[i] for i in positions])


class PriceChart(PlotextPlot):
    """Native Textual chart widget: Line+SMA, Candlestick, or OHLC bar modes."""

    def show(
        self,
        snap: SymbolSnapshot | None,
        preset_key: str,
        mode: str,
        avg_buy_price: float = 0.0,
        auto_rule: dict[str, Any] | None = None,
    ) -> None:
        plt = self.plt
        plt.clear_figure()
        plt.theme("dark")
        try:
            self._draw(snap, preset_key, mode, avg_buy_price, auto_rule)
        except Exception as exc:  # never let a chart error crash the TUI
            plt.clear_figure()
            plt.theme("dark")
            plt.title(f"Chart error ({mode}): {exc}")
            plt.plot([0, 1], [0, 1])
        self.refresh()

    def _draw(
        self,
        snap: SymbolSnapshot | None,
        preset_key: str,
        mode: str,
        avg_buy_price: float,
        auto_rule: dict[str, Any] | None,
    ) -> None:
        plt = self.plt
        _, _, tf_label = TIMEFRAME_PRESETS.get(preset_key, TIMEFRAME_PRESETS["1"])
        mode_label = dict(CHART_MODES).get(mode, mode)

        if snap is None:
            plt.title("Waiting for yfinance data...")
            plt.plot([0, 1], [0, 1])
            return
        if not snap.closes:
            plt.title(f"{snap.symbol}: {snap.error or 'No data'}")
            plt.plot([0, 1], [0, 1])
            return

        n = BARS_SHOWN.get(mode, 60)
        opens = snap.opens[-n:]
        highs = snap.highs[-n:]
        lows = snap.lows[-n:]
        closes = snap.closes[-n:]
        stamps = snap.timestamps[-n:]
        dtimes = snap.datetimes[-n:]
        count = len(closes)
        xs = list(range(count))

        if mode == "CANDLE" and len(dtimes) == count:
            # True candlesticks on a date axis
            plt.date_form(PLOTEXT_DATE_FORM)
            plt.candlestick(
                dtimes,
                {"Open": opens, "Close": closes, "High": highs, "Low": lows},
            )

        elif mode == "OHLC":
            # Traditional OHLC bars: High-Low stem, left tick = Open, right tick = Close
            half = 0.35
            for i in xs:
                color = UP_COLOR if closes[i] >= opens[i] else DOWN_COLOR
                plt.plot([i, i], [lows[i], highs[i]], color=color, marker="braille")
                plt.plot([i - half, i], [opens[i], opens[i]], color=color, marker="braille")
                plt.plot([i, i + half], [closes[i], closes[i]], color=color, marker="braille")
            plt.xlim(-1, count)
            _apply_ticks(plt, stamps)

        else:
            # LINE mode: close line + SMA(5) + SMA(15) (SMA computed on the full snapshot)
            line_color = UP_COLOR if snap.change_pct >= 0 else DOWN_COLOR
            plt.plot(xs, closes, label=f"{snap.symbol} Close", color=line_color, marker="braille")
            all_closes = snap.closes
            if len(all_closes) >= 5:
                plt.plot(xs, _rolling_sma(all_closes, 5)[-n:], label="SMA(5)", color="cyan", marker="braille")
            if len(all_closes) >= 15:
                plt.plot(xs, _rolling_sma(all_closes, 15)[-n:], label="SMA(15)", color="magenta", marker="braille")
            _apply_ticks(plt, stamps)

        # Reference line: user's Average Buy Price
        if avg_buy_price > 0:
            plt.hline(avg_buy_price, color="yellow")

        # Reference lines: Auto-Trader triggers
        if auto_rule and auto_rule.get("enabled"):
            if float(auto_rule.get("buy_below_price", 0)) > 0:
                plt.hline(float(auto_rule["buy_below_price"]), color="blue")
            if float(auto_rule.get("sell_above_price", 0)) > 0:
                plt.hline(float(auto_rule["sell_above_price"]), color="green")
            if float(auto_rule.get("stop_loss_price", 0)) > 0:
                plt.hline(float(auto_rule["stop_loss_price"]), color="red")

        sign = "+" if snap.change_pct >= 0 else ""
        buy_badge = f" | Bought Avg: ₹{avg_buy_price:,.2f}" if avg_buy_price > 0 else ""
        stale_badge = " | STALE" if snap.error else ""
        plt.title(
            f"{snap.symbol} ₹{snap.latest_price:,.2f} ({sign}{snap.change_pct:.2f}%) | "
            f"{tf_label} | {mode_label}{buy_badge}{stale_badge} | Updated {snap.fetched_at}"
        )
