from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import re

from wealth_monitor.config import MonitorConfig
from wealth_monitor.models import GiftNiftySnapshot, InstrumentSnapshot


def _pct_change(current: float, reference: float) -> float:
    if not reference:
        return 0.0
    return ((current - reference) / reference) * 100.0


def _index_to_datetime(index_value: object) -> datetime | None:
    if hasattr(index_value, "to_pydatetime"):
        return index_value.to_pydatetime()
    return None


def fetch_market_snapshots(symbols: Mapping[str, str]) -> dict[str, InstrumentSnapshot]:
    import yfinance as yf

    snapshots: dict[str, InstrumentSnapshot] = {}

    for symbol, display_name in symbols.items():
        ticker = yf.Ticker(symbol)
        intraday_history = ticker.history(period="5d", interval="15m", auto_adjust=False)
        daily_history = ticker.history(period="10d", interval="1d", auto_adjust=False)

        if intraday_history.empty and daily_history.empty:
            continue

        closes = (
            intraday_history["Close"].dropna()
            if not intraday_history.empty
            else daily_history["Close"].dropna()
        )
        highs = (
            intraday_history["High"].dropna()
            if not intraday_history.empty
            else daily_history["High"].dropna()
        )
        lows = (
            intraday_history["Low"].dropna()
            if not intraday_history.empty
            else daily_history["Low"].dropna()
        )
        returns = closes.pct_change().dropna()
        daily_closes = (
            daily_history["Close"].dropna() if not daily_history.empty else closes.tail(2)
        )

        if closes.empty:
            continue

        latest = float(closes.iloc[-1])
        prev_15m = float(closes.iloc[-2]) if len(closes) >= 2 else latest
        prev_1h = float(closes.iloc[-5]) if len(closes) >= 5 else prev_15m
        prev_1d = float(daily_closes.iloc[-2]) if len(daily_closes) >= 2 else latest
        volatility = float(returns.tail(20).std(ddof=0) * 100.0) if not returns.empty else 0.0

        intrabar_ranges = ((highs - lows) / closes.reindex(highs.index)).dropna()
        atr_proxy = (
            float(intrabar_ranges.tail(20).mean() * 100.0)
            if not intrabar_ranges.empty
            else 0.0
        )

        snapshots[symbol] = InstrumentSnapshot(
            symbol=symbol,
            display_name=display_name,
            last_price=latest,
            change_pct_15m=_pct_change(latest, prev_15m),
            change_pct_1h=_pct_change(latest, prev_1h),
            change_pct_1d=_pct_change(latest, prev_1d),
            volatility_pct=volatility,
            atr_proxy_pct=atr_proxy,
            sample_points=int(len(closes)),
            last_trade_time=_index_to_datetime(closes.index[-1]),
        )

    return snapshots


def fetch_gift_nifty_snapshot(config: MonitorConfig) -> GiftNiftySnapshot | None:
    import requests

    response = requests.get(
        config.gift_nifty_url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()
    text = response.text

    block_match = re.search(
        r'<p class="title-h3[^>]*>\s*GIFT NIFTY\s*</p>(.*?)gift-nifty-day',
        text,
        re.S,
    )
    if not block_match:
        return None

    block = block_match.group(1)
    level_match = re.search(r"(\d[\d,]*\.\d+)", block)
    change_match = re.search(
        r"([+-]?\d[\d,]*\.?\d*)\s*\(\s*([+-]?\d[\d,]*\.?\d*)\s*%\s*\)",
        block,
    )
    date_match = re.search(
        r'gift-nifty-day[^>]*>\s*([^<]+)\s*<',
        text[block_match.end() - 50 : block_match.end() + 150],
        re.S,
    )

    if not level_match or not change_match or not date_match:
        return None

    quote_time = datetime.strptime(date_match.group(1).strip(), "%d,%b %Y").replace(
        tzinfo=config.timezone
    )

    return GiftNiftySnapshot(
        level=float(level_match.group(1).replace(",", "")),
        change_points=float(change_match.group(1).replace(",", "")),
        change_pct=float(change_match.group(2).replace(",", "")),
        quote_time=quote_time,
        source=config.gift_nifty_url,
        freshness_label="latest available public quote",
    )
