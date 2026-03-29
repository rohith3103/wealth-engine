from __future__ import annotations

from datetime import datetime, timedelta, timezone

from wealth_monitor.config import MonitorConfig
from wealth_monitor.models import GiftNiftySnapshot, InstrumentSnapshot, NewsHeadline


def build_demo_dataset(
    config: MonitorConfig,
) -> tuple[list[NewsHeadline], dict[str, InstrumentSnapshot], GiftNiftySnapshot]:
    now_utc = datetime.now(timezone.utc)
    headlines = [
        NewsHeadline(
            title="Fed speakers signal caution as inflation remains uneven amid oil shock fears",
            source="Demo Feed",
            url="https://example.com/fed-caution",
            published_at=now_utc - timedelta(minutes=25),
            sentiment_score=-1.8,
            impact_tags=["FED", "Inflation"],
        ),
        NewsHeadline(
            title="Crude oil climbs after Iran-linked conflict concerns near the Strait of Hormuz",
            source="Demo Feed",
            url="https://example.com/oil-conflict",
            published_at=now_utc - timedelta(minutes=40),
            sentiment_score=-3.0,
            impact_tags=["Iran", "Oil", "War", "Hormuz"],
        ),
        NewsHeadline(
            title="Gift Nifty signals cautious start even as India GDP outlook holds steady",
            source="Demo Feed",
            url="https://example.com/india-gdp",
            published_at=now_utc - timedelta(minutes=55),
            sentiment_score=-0.2,
            impact_tags=["GIFT", "GDP"],
        ),
        NewsHeadline(
            title="RBI seen staying patient as core inflation cools",
            source="Demo Feed",
            url="https://example.com/rbi-patient",
            published_at=now_utc - timedelta(minutes=70),
            sentiment_score=1.2,
            impact_tags=["RBI", "Inflation"],
        ),
        NewsHeadline(
            title="Nasdaq futures drift lower as traders reassess rate path",
            source="Demo Feed",
            url="https://example.com/nasdaq-rates",
            published_at=now_utc - timedelta(minutes=85),
            sentiment_score=-1.0,
            impact_tags=["FED", "Rates"],
        ),
        NewsHeadline(
            title="Ceasefire hopes temper some safe-haven demand in early trade",
            source="Demo Feed",
            url="https://example.com/ceasefire",
            published_at=now_utc - timedelta(minutes=95),
            sentiment_score=1.4,
            impact_tags=["War"],
        ),
    ]

    snapshots = {
        "^NSEI": InstrumentSnapshot("^NSEI", "NIFTY 50", 22345.20, 0.05, 0.12, -0.44, 0.38, 0.42, 64, now_utc),
        "RELIANCE.NS": InstrumentSnapshot("RELIANCE.NS", "Reliance Industries", 2948.50, 0.18, 0.74, -0.20, 0.56, 0.44, 64, now_utc),
        "HDFCBANK.NS": InstrumentSnapshot("HDFCBANK.NS", "HDFC Bank", 1682.20, -0.02, 0.21, -0.10, 0.41, 0.39, 64, now_utc),
        "ICICIBANK.NS": InstrumentSnapshot("ICICIBANK.NS", "ICICI Bank", 1219.70, 0.09, 0.34, -0.32, 0.47, 0.35, 64, now_utc),
        "GOLDBEES.NS": InstrumentSnapshot("GOLDBEES.NS", "GoldBeES ETF", 63.40, 0.11, 0.56, 1.44, 0.26, 0.21, 64, now_utc),
        "^INDIAVIX": InstrumentSnapshot("^INDIAVIX", "India VIX", 26.80, 0.80, 2.10, 8.40, 1.05, 0.98, 64, now_utc),
        "^VIX": InstrumentSnapshot("^VIX", "CBOE VIX", 31.05, 0.80, 2.10, 12.50, 1.05, 0.98, 64, now_utc),
        "CL=F": InstrumentSnapshot("CL=F", "Crude Oil", 99.64, 0.55, 1.45, 10.20, 0.72, 0.68, 64, now_utc),
        "GC=F": InstrumentSnapshot("GC=F", "Gold", 2199.10, 0.14, 0.28, 1.20, 0.31, 0.26, 64, now_utc),
        "^IXIC": InstrumentSnapshot("^IXIC", "NASDAQ Composite", 17890.40, -0.12, -0.94, -1.12, 0.63, 0.58, 64, now_utc),
        "BTC-USD": InstrumentSnapshot("BTC-USD", "Bitcoin", 68210.00, -0.30, -1.88, -2.30, 1.10, 0.92, 64, now_utc),
    }

    gift_nifty = GiftNiftySnapshot(
        level=22210.00,
        change_points=-130.0,
        change_pct=-0.58,
        quote_time=now_utc,
        source="https://example.com/gift-nifty-demo",
        freshness_label="demo quote",
    )

    return headlines[: config.news_limit], snapshots, gift_nifty
