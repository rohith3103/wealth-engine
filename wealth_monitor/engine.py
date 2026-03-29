from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from math import floor
from statistics import mean

from wealth_monitor.config import MonitorConfig
from wealth_monitor.database import log_cycle
from wealth_monitor.news import load_news_sentiment
from wealth_monitor.models import (
    CycleAssessment,
    GiftNiftySnapshot,
    InstrumentSnapshot,
    NewsHeadline,
    ScreenedAsset,
    SetupCandidate,
    TradePlan,
)
from wealth_monitor.screener import select_target_asset

OIL_NEGATIVE_SECTORS = [
    "Auto sector: negative bias while crude stays above $95.",
    "Paint sector: margin pressure risk rises with expensive crude derivatives.",
    "Aviation sector: fuel-cost sensitivity argues for defensive sizing.",
]


def _news_bias(headlines: list[NewsHeadline], timestamp: datetime) -> float:
    if not headlines:
        return 0.0

    weighted_scores: list[float] = []
    for headline in headlines:
        hours_old = max(
            0.0,
            (timestamp.astimezone(headline.published_at.tzinfo) - headline.published_at)
            .total_seconds()
            / 3600.0,
        )
        recency_weight = max(0.35, 1.2 - (hours_old / 24.0))
        weighted_scores.append(headline.sentiment_score * recency_weight)

    return mean(weighted_scores)


def _preferred_vix(snapshots: dict[str, InstrumentSnapshot]) -> InstrumentSnapshot | None:
    return snapshots.get("^INDIAVIX") or snapshots.get("^VIX")


def _confidence_threshold(snapshots: dict[str, InstrumentSnapshot]) -> int:
    vix = _preferred_vix(snapshots)
    if vix and vix.last_price > 25:
        return 95
    return 85


def _global_risk(
    news_bias: float,
    snapshots: dict[str, InstrumentSnapshot],
    gift_gap_pct: float | None,
) -> int:
    risk_score = 5.0
    risk_score += min(2.5, abs(min(news_bias, 0.0)))

    vix = _preferred_vix(snapshots)
    if vix:
        if vix.last_price > 25:
            risk_score += 2.0
        elif vix.last_price > 18:
            risk_score += 0.7

    crude = snapshots.get("CL=F")
    if crude:
        if crude.last_price > 95:
            risk_score += 1.5
        elif crude.change_pct_1h > 1.2:
            risk_score += 0.8

    nasdaq = snapshots.get("^IXIC")
    if nasdaq and min(nasdaq.change_pct_1h, nasdaq.change_pct_1d) < -0.8:
        risk_score += 0.7

    bitcoin = snapshots.get("BTC-USD")
    if bitcoin and bitcoin.change_pct_1h < -1.5:
        risk_score += 0.5

    if gift_gap_pct is not None and gift_gap_pct < 0:
        risk_score += min(1.5, abs(gift_gap_pct))

    return max(1, min(10, round(risk_score)))


def _divergence_note(
    news_bias: float,
    nifty: InstrumentSnapshot | None,
    weekend_mode: bool,
    gift_gap_pct: float | None,
    gift_nifty: GiftNiftySnapshot | None,
) -> str:
    if not nifty:
        return "NIFTY data unavailable, so divergence could not be confirmed."

    if weekend_mode:
        if gift_nifty and gift_gap_pct is not None:
            return (
                "Weekend mode is active, so 15-minute tape is ignored. "
                f"Latest GIFT NIFTY is {gift_gap_pct:+.2f}% versus Friday's NIFTY close."
            )
        return (
            "Weekend mode is active, so 15-minute tape is ignored. "
            "The model is leaning on macro headlines, crude, and volatility instead."
        )

    if news_bias <= -1.0 and nifty.change_pct_1h >= -0.15:
        return "Headline flow is bearish, but NIFTY is still holding near flat over the last hour."

    if news_bias >= 1.0 and nifty.change_pct_1h <= 0.15:
        return "Headline flow is supportive, but NIFTY is not yet confirming the move."

    if abs(news_bias) < 0.5 and abs(nifty.change_pct_1h) < 0.25:
        return "Both headlines and price action are muted, so edge is limited."

    return "News flow and price action are broadly aligned."


def _snapshot_score(
    snapshot: InstrumentSnapshot,
    market_sentiment: str,
    force_long: bool = False,
) -> tuple[float, int]:
    bearish_mode = "BEARISH" in market_sentiment.upper() and not force_long
    direction_bonus = snapshot.change_pct_1h if not bearish_mode else -snapshot.change_pct_1h
    daily_alignment = snapshot.change_pct_1d if not bearish_mode else -snapshot.change_pct_1d
    stability_bonus = max(0.0, 1.5 - snapshot.volatility_pct)
    score = direction_bonus + (0.4 * daily_alignment) + stability_bonus - snapshot.atr_proxy_pct
    confidence = max(
        35,
        min(
            98,
            round(
                55
                + abs(snapshot.change_pct_1h) * 18
                + abs(snapshot.change_pct_1d) * 6
                + max(0.0, 1.2 - snapshot.volatility_pct) * 12
                - snapshot.atr_proxy_pct * 8
            ),
        ),
    )
    return score, confidence


def _pick_candidate(
    watchlist_symbols: tuple[str, ...],
    snapshots: dict[str, InstrumentSnapshot],
    market_sentiment: str,
) -> SetupCandidate | None:
    best_symbol: InstrumentSnapshot | None = None
    best_score = float("-inf")

    bearish_mode = "BEARISH" in market_sentiment.upper()

    for symbol in watchlist_symbols:
        snapshot = snapshots.get(symbol)
        if not snapshot:
            continue

        score, _ = _snapshot_score(snapshot, market_sentiment, force_long=not bearish_mode)

        if score > best_score:
            best_score = score
            best_symbol = snapshot

    if not best_symbol:
        return None

    _, confidence = _snapshot_score(best_symbol, market_sentiment, force_long=not bearish_mode)

    return SetupCandidate(
        symbol=best_symbol.symbol,
        display_name=best_symbol.display_name,
        reference_price=best_symbol.last_price,
        confidence=confidence,
        rationale=(
            f"{best_symbol.display_name} has the cleanest 1-hour move "
            f"({best_symbol.change_pct_1h:+.2f}%) and 1-day move "
            f"({best_symbol.change_pct_1d:+.2f}%), with volatility at "
            f"{best_symbol.volatility_pct:.2f}%."
        ),
    )


def _pick_candidate_from_screened_asset(
    screened_asset: ScreenedAsset | None,
    snapshots: dict[str, InstrumentSnapshot],
    market_sentiment: str,
) -> SetupCandidate | None:
    if not screened_asset:
        return None

    snapshot = snapshots.get(screened_asset.symbol)
    if not snapshot:
        return None

    _, confidence = _snapshot_score(
        snapshot,
        market_sentiment,
        force_long=screened_asset.defensive_hedge,
    )
    rationale = (
        f"{screened_asset.rationale} {snapshot.display_name} is printing "
        f"{snapshot.change_pct_1h:+.2f}% over 1 hour and {snapshot.change_pct_1d:+.2f}% "
        f"over 1 day, with volatility at {snapshot.volatility_pct:.2f}%."
    )
    return SetupCandidate(
        symbol=snapshot.symbol,
        display_name=snapshot.display_name,
        reference_price=snapshot.last_price,
        confidence=confidence,
        rationale=rationale,
    )


def _kill_switch(
    weekend_mode: bool,
    headlines: list[NewsHeadline],
    nifty: InstrumentSnapshot | None,
    snapshots: dict[str, InstrumentSnapshot],
    candidate: SetupCandidate | None,
    confidence_threshold: int,
) -> str | None:
    if weekend_mode:
        return "Weekend protocol active. Use this as a Monday hedge map, not a live entry signal."

    if len(headlines) < 5:
        return "Headline sample is too thin for a reliable cycle."

    if not nifty:
        return "NIFTY confirmation is missing."

    vix = _preferred_vix(snapshots)
    if vix and vix.last_price > 25 and (not candidate or candidate.confidence < confidence_threshold):
        return "VIX is above 25, so the kill switch now requires 95%+ confidence."

    if nifty.volatility_pct > 1.4 or nifty.atr_proxy_pct > 1.2:
        return "Index volatility is elevated, so the setup may be a trap."

    if vix and vix.change_pct_1h > 4:
        return "VIX is expanding too quickly for a controlled scalp."

    if candidate and candidate.confidence >= confidence_threshold and abs(nifty.change_pct_1h) < 0.2:
        return "The candidate is strong on paper, but the index still lacks confirmation."

    return None


def _predict_monday_open(
    news_bias: float,
    snapshots: dict[str, InstrumentSnapshot],
    friday_nse_close: float | None,
    gift_nifty: GiftNiftySnapshot | None,
) -> tuple[str, float | None, float | None]:
    if friday_nse_close:
        gift_gap_pct = (
            ((gift_nifty.level - friday_nse_close) / friday_nse_close) * 100.0
            if gift_nifty
            else None
        )
    else:
        gift_gap_pct = None

    predicted_gap_pct = news_bias * 0.22 if gift_gap_pct is None else gift_gap_pct

    crude = snapshots.get("CL=F")
    if crude and crude.last_price > 95:
        predicted_gap_pct -= 0.25

    vix = _preferred_vix(snapshots)
    if vix and vix.last_price > 25:
        predicted_gap_pct -= 0.20

    if news_bias <= -1.0:
        predicted_gap_pct += max(-0.35, news_bias * 0.12)
    elif news_bias >= 1.0:
        predicted_gap_pct += min(0.30, news_bias * 0.10)

    nasdaq = snapshots.get("^IXIC")
    if nasdaq and nasdaq.change_pct_1d < -1.0:
        predicted_gap_pct -= 0.10

    predicted_gap_pct = max(-3.0, min(3.0, predicted_gap_pct))

    if predicted_gap_pct <= -0.15:
        direction = "Gap Down"
    elif predicted_gap_pct >= 0.15:
        direction = "Gap Up"
    else:
        direction = "Flat to Slightly Mixed"

    return (
        f"{direction} around {predicted_gap_pct:+.2f}% at Monday 9:15 AM.",
        predicted_gap_pct,
        gift_gap_pct,
    )


def _weekend_confidence(
    headlines: list[NewsHeadline],
    gift_nifty: GiftNiftySnapshot | None,
    gift_gap_pct: float | None,
    snapshots: dict[str, InstrumentSnapshot],
) -> int:
    confidence = 56
    if len(headlines) >= 5:
        confidence += 10
    if gift_nifty:
        confidence += 12
    if gift_gap_pct is not None and abs(gift_gap_pct) >= 0.30:
        confidence += 8

    crude = snapshots.get("CL=F")
    if crude and crude.last_price > 95:
        confidence += 4

    vix = _preferred_vix(snapshots)
    if vix and vix.last_price > 25:
        confidence += 4

    return max(40, min(96, confidence))


def _hedge_strategy(
    weekend_mode: bool,
    predicted_gap_pct: float | None,
    market_sentiment: str,
) -> str:
    if weekend_mode:
        if market_sentiment == "EXTREME BEARISH" or (predicted_gap_pct is not None and predicted_gap_pct <= -1.0):
            return "Keep cash high into Monday. If the gap confirms with weak breadth, check protective NIFTY PUTs instead of trying to catch the first bounce."
        if predicted_gap_pct is not None and predicted_gap_pct <= -0.25:
            return "Treat Monday as a defensive open. Prefer staying in cash at the bell or checking PUT hedges only after spreads and breadth settle."
        if predicted_gap_pct is not None and predicted_gap_pct >= 0.40:
            return "Avoid chasing the first green print. Let the first 15 minutes settle before considering directional exposure."
        return "Base case is a mixed open. Stay selective, keep size small, and prefer cash over premium decay risk."

    if "BEARISH" in market_sentiment.upper():
        return "Favor cash preservation first. If volatility expands, reduce size and avoid low-liquidity option premiums."
    return "If breadth confirms, stick to liquid names and keep risk capped before adding exposure."


def _build_trade_plan(
    config: MonitorConfig,
    snapshots: dict[str, InstrumentSnapshot],
    candidate: SetupCandidate | None,
    weekend_mode: bool,
    market_sentiment: str,
    status: str,
    defensive_hedge: bool = False,
) -> tuple[TradePlan | None, str | None]:
    if weekend_mode or not candidate:
        return None, None

    if status != "STATUS: REVIEW SETUP - MANUAL CONFIRMATION REQUIRED":
        return None, None

    snapshot = snapshots.get(candidate.symbol)
    if not snapshot:
        return None, "Live snapshot missing for the selected symbol."

    entry_price = round(candidate.reference_price, 2)
    stop_gap_pct = max(
        0.35,
        min(
            1.50,
            max(snapshot.atr_proxy_pct * 1.25, snapshot.volatility_pct * 1.75, 0.35),
        ),
    )
    stop_loss_gap = round(entry_price * (stop_gap_pct / 100.0), 2)
    if stop_loss_gap <= 0:
        return None, "Stop-loss gap is invalid, so position sizing could not be calculated."

    action = "BUY" if defensive_hedge else ("SELL" if "BEARISH" in market_sentiment.upper() else "BUY")
    stop_loss_price = (
        round(entry_price + stop_loss_gap, 2)
        if action == "SELL"
        else round(entry_price - stop_loss_gap, 2)
    )
    target_price = (
        round(entry_price - (2 * stop_loss_gap), 2)
        if action == "SELL"
        else round(entry_price + (2 * stop_loss_gap), 2)
    )
    risk_amount = round(config.available_capital * config.risk_per_trade, 2)
    risk_based_quantity = floor(risk_amount / stop_loss_gap)
    max_affordable_quantity = floor(config.available_capital / entry_price)
    target_quantity = min(risk_based_quantity, max_affordable_quantity)

    if target_quantity <= 0:
        return (
            None,
            "Available capital cannot fund even one unit at the current entry price.",
        )

    return (
        TradePlan(
            action=action,
            symbol=candidate.symbol,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            target_price=target_price,
            stop_loss_gap=stop_loss_gap,
            risk_amount=risk_amount,
            risk_based_quantity=risk_based_quantity,
            max_affordable_quantity=max_affordable_quantity,
            target_quantity=target_quantity,
            total_investment_amount=round(target_quantity * entry_price, 2),
        ),
        None,
    )


def _apply_fear_risk_controls(
    trade_plan: TradePlan | None,
    fear_score: int,
    snapshots: dict[str, InstrumentSnapshot],
) -> tuple[TradePlan | None, str | None]:
    if not trade_plan or fear_score <= 75:
        return trade_plan, None

    vix = _preferred_vix(snapshots)
    if vix and vix.last_price > 25:
        return (
            None,
            "AI fear score is above 75 and VIX is elevated, so the engine is overriding to HOLD_CASH.",
        )

    reduced_quantity = floor(trade_plan.target_quantity / 2)
    if reduced_quantity <= 0:
        return (
            None,
            "AI fear score is above 75, and the defensive size reduction rounds the position down to zero.",
        )

    return (
        replace(
            trade_plan,
            target_quantity=reduced_quantity,
            total_investment_amount=round(reduced_quantity * trade_plan.entry_price, 2),
        ),
        "AI fear score is above 75, so target quantity was cut in half.",
    )


def assess_cycle(
    config: MonitorConfig,
    timestamp: datetime,
    headlines: list[NewsHeadline],
    snapshots: dict[str, InstrumentSnapshot],
    gift_nifty: GiftNiftySnapshot | None = None,
) -> CycleAssessment:
    news_sentiment = load_news_sentiment(config, headlines=headlines)
    weekend_mode = timestamp.weekday() >= 5
    screened_asset = (
        None
        if weekend_mode
        else select_target_asset(
            config.screener_symbols,
            news_sentiment.fear_score,
            snapshots=snapshots,
        )
    )
    news_bias = _news_bias(headlines, timestamp)
    nifty = snapshots.get("^NSEI")
    friday_nse_close = nifty.last_price if nifty else None
    monday_open_prediction, predicted_gap_pct, gift_gap_pct = _predict_monday_open(
        news_bias=news_bias,
        snapshots=snapshots,
        friday_nse_close=friday_nse_close,
        gift_nifty=gift_nifty,
    )
    confidence_threshold = _confidence_threshold(snapshots)

    if weekend_mode and gift_gap_pct is not None and gift_gap_pct <= -1.0:
        market_sentiment = "EXTREME BEARISH"
    elif weekend_mode:
        market_sentiment = "Bullish" if (predicted_gap_pct or 0.0) > 0 else "Bearish"
    else:
        market_sentiment = "Bullish" if news_bias + (nifty.change_pct_1h if nifty else 0.0) >= 0 else "Bearish"

    global_risk = _global_risk(news_bias, snapshots, gift_gap_pct)
    divergence_note = _divergence_note(news_bias, nifty, weekend_mode, gift_gap_pct, gift_nifty)
    candidate = None
    if not weekend_mode:
        candidate = _pick_candidate_from_screened_asset(
            screened_asset,
            snapshots,
            market_sentiment,
        ) or _pick_candidate(config.watchlist_symbols, snapshots, market_sentiment)
    kill_switch_reason = _kill_switch(
        weekend_mode=weekend_mode,
        headlines=headlines,
        nifty=nifty,
        snapshots=snapshots,
        candidate=candidate,
        confidence_threshold=confidence_threshold,
    )

    if weekend_mode:
        confidence = _weekend_confidence(headlines, gift_nifty, gift_gap_pct, snapshots)
        status = "STATUS: WEEKEND GAP WATCH - NO TRADE"
        rationale = (
            f"AI fear score is {news_sentiment.fear_score}/100 with dominant theme "
            f"{news_sentiment.dominant_theme}. Weekend macro bias scored {news_bias:+.2f}. "
            f"{divergence_note} "
            f"{monday_open_prediction}"
        )
    else:
        confidence = candidate.confidence if candidate else 0
        if kill_switch_reason or confidence < confidence_threshold:
            status = "STATUS: MONITORING - NO TRADE"
        else:
            status = "STATUS: REVIEW SETUP - MANUAL CONFIRMATION REQUIRED"

        if candidate:
            rationale = (
                f"AI fear score is {news_sentiment.fear_score}/100 with dominant theme "
                f"{news_sentiment.dominant_theme}. News bias scored {news_bias:+.2f}. "
                f"{candidate.rationale} "
                f"{divergence_note}"
            )
        else:
            rationale = (
                f"AI fear score is {news_sentiment.fear_score}/100 with dominant theme "
                f"{news_sentiment.dominant_theme}. News bias scored {news_bias:+.2f}. "
                "No screened asset candidate stood out."
            )

    crude = snapshots.get("CL=F")
    sector_biases = OIL_NEGATIVE_SECTORS if crude and crude.last_price > 95 else []
    hedge_strategy = _hedge_strategy(weekend_mode, predicted_gap_pct, market_sentiment)
    trade_plan, sizing_blocker = _build_trade_plan(
        config=config,
        snapshots=snapshots,
        candidate=candidate,
        weekend_mode=weekend_mode,
        market_sentiment=market_sentiment,
        status=status,
        defensive_hedge=bool(screened_asset and screened_asset.defensive_hedge),
    )
    trade_plan, fear_control_reason = _apply_fear_risk_controls(
        trade_plan=trade_plan,
        fear_score=news_sentiment.fear_score,
        snapshots=snapshots,
    )
    if fear_control_reason:
        rationale = f"{rationale} {fear_control_reason}"
        if not trade_plan:
            status = "STATUS: MONITORING - NO TRADE"
            kill_switch_reason = (
                fear_control_reason
                if not kill_switch_reason
                else f"{kill_switch_reason} {fear_control_reason}"
            )

    if not weekend_mode and status == "STATUS: REVIEW SETUP - MANUAL CONFIRMATION REQUIRED" and not trade_plan:
        status = "STATUS: MONITORING - NO TRADE"
        if sizing_blocker and not kill_switch_reason:
            kill_switch_reason = sizing_blocker
    recommended_action = trade_plan.action if trade_plan else "HOLD_CASH"
    risk_amount = round(config.available_capital * config.risk_per_trade, 2)
    recommended_asset = (
        screened_asset.symbol
        if screened_asset
        else (candidate.symbol if candidate else None)
    )
    india_vix = _preferred_vix(snapshots)

    assessment = CycleAssessment(
        timestamp=timestamp,
        mode_label="Weekend Gap Analysis" if weekend_mode else "Intraday Reaction Monitor",
        weekend_mode=weekend_mode,
        fear_score=news_sentiment.fear_score,
        dominant_theme=news_sentiment.dominant_theme,
        market_sentiment=market_sentiment,
        global_risk=global_risk,
        status=status,
        recommended_action=recommended_action,
        confidence=confidence,
        confidence_threshold=confidence_threshold,
        news_bias=news_bias,
        rationale=rationale,
        divergence_note=divergence_note,
        monday_open_prediction=monday_open_prediction,
        predicted_gap_pct=predicted_gap_pct,
        gift_gap_pct=gift_gap_pct,
        friday_nse_close=friday_nse_close,
        hedge_strategy=hedge_strategy,
        sector_biases=sector_biases,
        kill_switch_reason=kill_switch_reason,
        candidate=candidate,
        trade_plan=trade_plan,
        available_capital=config.available_capital,
        risk_per_trade=config.risk_per_trade,
        risk_amount=risk_amount,
        gift_nifty=gift_nifty,
        risk_cap_pct=config.risk_cap_pct,
        headlines=headlines,
        snapshots=snapshots,
    )
    try:
        log_cycle(
            database_path=config.database_path,
            timestamp=timestamp,
            fear_score=news_sentiment.fear_score,
            dominant_theme=news_sentiment.dominant_theme,
            india_vix=india_vix.last_price if india_vix else None,
            recommended_asset=recommended_asset,
            action_taken=recommended_action,
            position_size=trade_plan.target_quantity if trade_plan else 0,
        )
    except Exception as exc:
        print(f"Warning: cycle logging failed: {exc}")

    return assessment
