from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

import yfinance as yf


TIMEFRAME_PRESETS: dict[str, tuple[str, str, str]] = {
    "1": ("1d", "1m", "Intraday (1-Min Bars)"),
    "2": ("5d", "5m", "5-Day (5-Min Bars)"),
    "3": ("3mo", "1d", "3-Month (Daily Bars)"),
}

QUOTE_PRESET = "1"
MAX_BARS = 60
DATETIME_FMT = "%d/%m/%Y %H:%M:%S"


@dataclass(slots=True)
class SymbolSnapshot:
    symbol: str
    latest_price: float = 0.0
    prev_close: float = 0.0
    change_pct: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    timestamps: list[str] = field(default_factory=list)   # short axis labels (HH:MM or DD/MM/YYYY)
    datetimes: list[str] = field(default_factory=list)    # full "DD/MM/YYYY HH:MM:SS" (for candlesticks)
    opens: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)
    fetched_at: str = ""
    error: str = ""


class MarketDataFeed:
    """Fetches latest possible quotes and OHLCV bars from yfinance (parallel)."""

    def __init__(self) -> None:
        # Keyed by (SYMBOL, preset_key)
        self.cache: dict[tuple[str, str], SymbolSnapshot] = {}

    # --- Cache accessors ---

    def quote(self, symbol: str) -> SymbolSnapshot | None:
        """Latest 1-minute-bar snapshot: used for prices, watchlist and auto-trading."""
        return self.cache.get((symbol.strip().upper(), QUOTE_PRESET))

    def chart(self, symbol: str, preset_key: str) -> SymbolSnapshot | None:
        """Snapshot for the currently selected chart timeframe."""
        return self.cache.get((symbol.strip().upper(), preset_key))

    # --- Fetching ---

    def _store_error(
        self, key: tuple[str, str], sym: str, now_str: str, message: str
    ) -> SymbolSnapshot:
        cached = self.cache.get(key)
        if cached is not None and cached.closes:
            cached.error = f"Stale ({message})"
            return cached
        snap = SymbolSnapshot(symbol=sym, fetched_at=now_str, error=message)
        self.cache[key] = snap
        return snap

    def fetch_symbol(self, symbol: str, preset_key: str = QUOTE_PRESET) -> SymbolSnapshot:
        sym = symbol.strip().upper()
        if preset_key not in TIMEFRAME_PRESETS:
            preset_key = QUOTE_PRESET
        period, interval, _ = TIMEFRAME_PRESETS[preset_key]
        key = (sym, preset_key)
        now_str = datetime.now().strftime("%H:%M:%S")

        try:
            ticker = yf.Ticker(sym)
            df = ticker.history(period=period, interval=interval, auto_adjust=False)

            # Fallback to 5d/5m ONLY for the quote preset if 1d/1m is empty (pre-open / holiday)
            if (df is None or df.empty) and preset_key == QUOTE_PRESET:
                interval = "5m"
                df = ticker.history(period="5d", interval="5m", auto_adjust=False)

            if df is None or df.empty:
                return self._store_error(key, sym, now_str, "No data returned from yfinance")

            df = df.dropna(subset=["Open", "High", "Low", "Close"])
            if df.empty:
                return self._store_error(key, sym, now_str, "Empty OHLC bars")

            closes = [round(float(x), 2) for x in df["Close"].tolist()]
            opens = [round(float(x), 2) for x in df["Open"].tolist()]
            highs = [round(float(x), 2) for x in df["High"].tolist()]
            lows = [round(float(x), 2) for x in df["Low"].tolist()]
            volumes = [int(x) for x in df["Volume"].fillna(0).tolist()]

            short_fmt = "%H:%M" if interval.endswith("m") else "%d/%m/%Y"
            timestamps = [idx.strftime(short_fmt) for idx in df.index]
            datetimes = [idx.strftime(DATETIME_FMT) for idx in df.index]

            latest_price = closes[-1]
            first_price = opens[0] if opens[0] > 0 else closes[0]
            change_pct = (
                round(((latest_price - first_price) / first_price) * 100.0, 2)
                if first_price > 0
                else 0.0
            )

            snap = SymbolSnapshot(
                symbol=sym,
                latest_price=latest_price,
                prev_close=first_price,
                change_pct=change_pct,
                high=max(highs),
                low=min(lows),
                volume=sum(volumes),
                timestamps=timestamps[-MAX_BARS:],
                datetimes=datetimes[-MAX_BARS:],
                opens=opens[-MAX_BARS:],
                highs=highs[-MAX_BARS:],
                lows=lows[-MAX_BARS:],
                closes=closes[-MAX_BARS:],
                fetched_at=now_str,
            )
            self.cache[key] = snap
            return snap

        except Exception as exc:
            return self._store_error(key, sym, now_str, str(exc))

    def fetch_all(self, symbols: list[str], active_symbol: str, preset_key: str) -> None:
        """Refresh quotes for all symbols (in parallel) plus the active chart timeframe."""
        jobs: list[tuple[str, str]] = [
            (s.strip().upper(), QUOTE_PRESET) for s in dict.fromkeys(symbols)
        ]
        if preset_key != QUOTE_PRESET and active_symbol:
            jobs.append((active_symbol.strip().upper(), preset_key))
        if not jobs:
            return

        workers = min(8, len(jobs))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda job: self.fetch_symbol(job[0], job[1]), jobs))
