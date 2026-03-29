from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class NewsHeadline:
    title: str
    source: str
    url: str
    published_at: datetime
    sentiment_score: float
    impact_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NewsSentimentSnapshot:
    fear_score: int
    dominant_theme: str


@dataclass(slots=True)
class ScreenedAsset:
    symbol: str
    display_name: str
    current_price: float
    previous_close: float
    momentum_1d: float
    defensive_hedge: bool
    rationale: str


@dataclass(slots=True)
class InstrumentSnapshot:
    symbol: str
    display_name: str
    last_price: float
    change_pct_15m: float
    change_pct_1h: float
    change_pct_1d: float
    volatility_pct: float
    atr_proxy_pct: float
    sample_points: int
    last_trade_time: datetime | None = None


@dataclass(slots=True)
class GiftNiftySnapshot:
    level: float
    change_points: float
    change_pct: float
    quote_time: datetime
    source: str
    freshness_label: str


@dataclass(slots=True)
class SetupCandidate:
    symbol: str
    display_name: str
    reference_price: float
    confidence: int
    rationale: str


@dataclass(slots=True)
class TradePlan:
    action: str
    symbol: str
    entry_price: float
    stop_loss_price: float
    target_price: float
    stop_loss_gap: float
    risk_amount: float
    risk_based_quantity: int
    max_affordable_quantity: int
    target_quantity: int
    total_investment_amount: float


@dataclass(slots=True)
class CycleAssessment:
    timestamp: datetime
    mode_label: str
    weekend_mode: bool
    fear_score: int
    dominant_theme: str
    market_sentiment: str
    global_risk: int
    status: str
    recommended_action: str
    confidence: int
    confidence_threshold: int
    news_bias: float
    rationale: str
    divergence_note: str
    monday_open_prediction: str
    predicted_gap_pct: float | None
    gift_gap_pct: float | None
    friday_nse_close: float | None
    hedge_strategy: str
    sector_biases: list[str]
    kill_switch_reason: str | None
    candidate: SetupCandidate | None
    trade_plan: TradePlan | None
    available_capital: float
    risk_per_trade: float
    risk_amount: float
    gift_nifty: GiftNiftySnapshot | None
    risk_cap_pct: float
    headlines: list[NewsHeadline]
    snapshots: dict[str, InstrumentSnapshot]
