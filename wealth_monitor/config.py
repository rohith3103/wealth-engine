from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo


DEFAULT_MARKET_SYMBOLS = {
    "^NSEI": "NIFTY 50",
    "RELIANCE.NS": "Reliance Industries",
    "HDFCBANK.NS": "HDFC Bank",
    "ICICIBANK.NS": "ICICI Bank",
    "GOLDBEES.NS": "GoldBeES ETF",
    "^INDIAVIX": "India VIX",
    "^VIX": "CBOE VIX",
    "CL=F": "Crude Oil",
    "GC=F": "Gold",
    "^IXIC": "NASDAQ Composite",
    "BTC-USD": "Bitcoin",
}

WATCHLIST_SYMBOLS = ("RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "^NSEI")
SCREENER_SYMBOLS = {
    "RELIANCE.NS": "Reliance Industries",
    "HDFCBANK.NS": "HDFC Bank",
    "GOLDBEES.NS": "GoldBeES ETF",
    "BTC-USD": "Bitcoin",
}


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(slots=True)
class MonitorConfig:
    newsapi_key: str | None
    timezone: ZoneInfo
    news_lookback_hours: int
    news_limit: int
    available_capital: float
    risk_per_trade: float
    risk_cap_pct: float
    gift_nifty_url: str
    market_symbols: Mapping[str, str]
    watchlist_symbols: tuple[str, ...]
    screener_symbols: Mapping[str, str]
    report_dir: Path
    database_path: Path


def load_config(project_root: Path | None = None) -> MonitorConfig:
    root = project_root or Path(__file__).resolve().parent.parent
    _load_dotenv(root / ".env")

    timezone_name = os.getenv("TIMEZONE", "Asia/Kolkata")

    return MonitorConfig(
        newsapi_key=os.getenv("NEWSAPI_KEY"),
        timezone=ZoneInfo(timezone_name),
        news_lookback_hours=int(os.getenv("NEWS_LOOKBACK_HOURS", "12")),
        news_limit=int(os.getenv("NEWS_LIMIT", "20")),
        available_capital=float(os.getenv("AVAILABLE_CAPITAL", "50000")),
        risk_per_trade=float(os.getenv("RISK_PER_TRADE", "0.02")),
        risk_cap_pct=float(os.getenv("RISK_CAP_PCT", "1.5")),
        gift_nifty_url=os.getenv(
            "GIFT_NIFTY_URL",
            "https://www.icicidirect.com/equity/index/gift-nifty",
        ),
        market_symbols=DEFAULT_MARKET_SYMBOLS,
        watchlist_symbols=WATCHLIST_SYMBOLS,
        screener_symbols=SCREENER_SYMBOLS,
        report_dir=root / "reports",
        database_path=root / "wealth_logs.duckdb",
    )
