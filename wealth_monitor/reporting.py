from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import requests

from wealth_monitor.models import CycleAssessment

FALLBACK_GEMINI_API_KEY = "AIzaSyAhqG9azzqdegfxu6cG1XnTXfT9KPCwz6o"
FALLBACK_TELEGRAM_BOT_TOKEN = "8759152666:AAFrtVPyT9Ew5f7iUKT045RRnKrpV_LfQ0U"
FALLBACK_TELEGRAM_CHAT_ID = "6208167034"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
PLAIN_ENGLISH_SYSTEM_PROMPT = (
    "You are a direct, highly accurate financial assistant. Read the provided "
    "trading JSON data. Write a short, 3-to-4 sentence summary in plain English. "
    "You MUST include: \n"
    "1. The overall market mood (e.g., 'The market is panicking due to high oil prices'). \n"
    "2. The exact action to take (e.g., 'Do nothing and hold cash' OR 'Buy [Quantity] shares of [Stock Symbol] at [Entry Price]'). \n"
    "3. The exact total investment amount required. \n"
    "4. The AI Fear Score and dominant theme. \n"
    "5. The main reason for this action. \n"
    "Do not use complex jargon. Be absolute and clear."
)


def _format_trade_time(assessment: CycleAssessment, symbol: str) -> str:
    snapshot = assessment.snapshots.get(symbol)
    if not snapshot or not snapshot.last_trade_time:
        return "n/a"
    return snapshot.last_trade_time.astimezone(assessment.timestamp.tzinfo).strftime(
        "%Y-%m-%d %H:%M %Z"
    )


def _gemini_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", FALLBACK_GEMINI_API_KEY)


def _gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


def _telegram_bot_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", FALLBACK_TELEGRAM_BOT_TOKEN)


def _telegram_chat_id() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", FALLBACK_TELEGRAM_CHAT_ID)


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    return "429" in text or "quota" in text or "resource_exhausted" in text


def _generate_with_current_sdk(prompt: str, system_prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_gemini_api_key())
    response = client.models.generate_content(
        model=_gemini_model(),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2,
        ),
    )
    return (response.text or "").strip()


def _fallback_english_summary(json_data: dict) -> str:
    mood = json_data.get("market_sentiment", "Mixed")
    reason = json_data.get("rationale", "The engine did not produce a stronger edge.")
    action = json_data.get("recommended_action", "HOLD_CASH")
    fear_score = int(json_data.get("fear_score") or 0)
    dominant_theme = json_data.get("dominant_theme", "Macro Risk Watch")
    total_investment_amount = float(json_data.get("total_investment_amount") or 0.0)
    trade_plan = json_data.get("trade_plan")

    if trade_plan:
        action_sentence = (
            f"{action} {trade_plan['target_quantity']} shares of {trade_plan['symbol']} "
            f"at {trade_plan['entry_price']:.2f}."
        )
    else:
        action_sentence = "Do nothing and hold cash."

    return (
        f"The market mood is {mood.lower()}. The AI Fear Score is {fear_score}/100 and the dominant theme is {dominant_theme}. "
        f"{action_sentence} "
        f"The total investment amount required is {total_investment_amount:.2f}. "
        f"The main reason is {reason}"
    )


def generate_gemini_text(
    prompt: str,
    system_prompt: str,
    fallback_text: str | None = None,
) -> str:
    last_error: Exception | None = None

    try:
        summary = _generate_with_current_sdk(prompt, system_prompt)
        if summary:
            return summary
    except Exception as exc:
        last_error = exc

    fallback_summary = fallback_text or "Gemini summary unavailable."
    if last_error:
        if _is_quota_error(last_error):
            return (
                f"{fallback_summary}\n\n"
                "[Gemini quota limit reached. Fallback summary used.]"
            )
        return f"{fallback_summary}\n\n[Gemini generation unavailable: {last_error}]"
    return fallback_summary


def generate_plain_english_report(json_data: dict) -> str:
    prompt = "Trading JSON data:\n```json\n" + json.dumps(json_data, indent=2) + "\n```"
    fallback_summary = _fallback_english_summary(json_data)
    return generate_gemini_text(
        prompt=prompt,
        system_prompt=PLAIN_ENGLISH_SYSTEM_PROMPT,
        fallback_text=fallback_summary,
    )


def send_telegram_alert(summary_text: str) -> None:
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{_telegram_bot_token()}/sendMessage",
            json={
                "chat_id": _telegram_chat_id(),
                "text": summary_text,
            },
            timeout=15,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"Warning: Telegram alert failed: {exc}")


def render_cycle_report(assessment: CycleAssessment) -> tuple[str, dict]:
    candidate = assessment.candidate
    trade_plan = assessment.trade_plan
    headline_lines = []
    for headline in assessment.headlines[:5]:
        tag_suffix = f" [{' / '.join(headline.impact_tags)}]" if headline.impact_tags else ""
        headline_lines.append(f"- {headline.title}{tag_suffix} ({headline.source})")

    market_lines = []
    for symbol in (
        "^NSEI",
        "RELIANCE.NS",
        "HDFCBANK.NS",
        "ICICIBANK.NS",
        "GOLDBEES.NS",
        "^INDIAVIX",
        "^VIX",
        "CL=F",
        "^IXIC",
        "BTC-USD",
    ):
        snapshot = assessment.snapshots.get(symbol)
        if not snapshot:
            continue
        market_lines.append(
            f"- {snapshot.display_name}: last {snapshot.last_price:.2f} | "
            f"15m {snapshot.change_pct_15m:+.2f}% | 1h {snapshot.change_pct_1h:+.2f}% | "
            f"1d {snapshot.change_pct_1d:+.2f}% | last trade {_format_trade_time(assessment, symbol)}"
        )

    signal_block = [
        f"- Recommended Action: {assessment.recommended_action}",
        f"- AI Fear Score: {assessment.fear_score}/100",
        f"- Dominant Theme: {assessment.dominant_theme}",
        f"- Available Capital: {assessment.available_capital:.2f}",
        f"- Risk Per Trade: {assessment.risk_per_trade:.2%}",
        f"- Risk Amount: {assessment.risk_amount:.2f}",
    ]

    if assessment.weekend_mode:
        signal_block.extend(
            [
                f"- Prediction Confidence: {assessment.confidence}%",
                f"- Confidence Threshold For Live Risk: {assessment.confidence_threshold}%",
                f"- Rationale: {assessment.rationale}",
                f"- Hedge Strategy: {assessment.hedge_strategy}",
            ]
        )
    elif trade_plan:
        signal_block.extend(
            [
                f"- Signal Symbol: {trade_plan.symbol}",
                f"- Entry Price: {trade_plan.entry_price:.2f}",
                f"- Stop Loss: {trade_plan.stop_loss_price:.2f}",
                f"- Target Price: {trade_plan.target_price:.2f}",
                f"- Stop Loss Gap: {trade_plan.stop_loss_gap:.2f}",
                f"- Risk-Based Quantity: {trade_plan.risk_based_quantity}",
                f"- Max Affordable Quantity: {trade_plan.max_affordable_quantity}",
                f"- Target Quantity: {trade_plan.target_quantity}",
                f"- Total Investment Amount: {trade_plan.total_investment_amount:.2f}",
                f"- Confidence: {assessment.confidence}%",
                f"- Confidence Threshold: {assessment.confidence_threshold}%",
                f"- Rationale: {assessment.rationale}",
            ]
        )
    elif candidate:
        signal_block.extend(
            [
                f"- Screened Asset: {candidate.symbol} ({candidate.display_name})",
                f"- Reference Price: {candidate.reference_price:.2f}",
                f"- Confidence: {assessment.confidence}%",
                f"- Confidence Threshold: {assessment.confidence_threshold}%",
                f"- Rationale: {assessment.rationale}",
            ]
        )
    else:
        signal_block.extend(
            [
                "- Screened Asset: None",
                "- Confidence: 0%",
                f"- Confidence Threshold: {assessment.confidence_threshold}%",
                f"- Rationale: {assessment.rationale}",
            ]
        )

    if assessment.kill_switch_reason:
        signal_block.append(f"- Kill Switch: {assessment.kill_switch_reason}")

    if assessment.sector_biases:
        signal_block.append(f"- Oil Bias: {' '.join(assessment.sector_biases)}")

    signal_block.append(
        f"- Risk Guardrail: Manual risk cap {assessment.risk_cap_pct:.2f}% of portfolio."
    )

    monday_open_lines = [f"- {assessment.monday_open_prediction}"]
    if assessment.friday_nse_close is not None:
        monday_open_lines.append(f"- Friday NSE Close: {assessment.friday_nse_close:.2f}")
    if assessment.gift_nifty:
        monday_open_lines.append(
            f"- GIFT NIFTY: {assessment.gift_nifty.level:.2f} | "
            f"change {assessment.gift_nifty.change_points:+.2f} ({assessment.gift_nifty.change_pct:+.2f}%) | "
            f"as of {assessment.gift_nifty.quote_time.strftime('%Y-%m-%d %Z')} | "
            f"{assessment.gift_nifty.freshness_label}"
        )
    else:
        monday_open_lines.append(
            "- GIFT NIFTY: unavailable, so macro headlines carried more weight."
        )
    if assessment.gift_gap_pct is not None:
        monday_open_lines.append(f"- Implied GIFT vs Friday Gap: {assessment.gift_gap_pct:+.2f}%")
    monday_open_lines.append(f"- Hedge Strategy: {assessment.hedge_strategy}")

    payload = {
        "timestamp": assessment.timestamp.isoformat(),
        "mode_label": assessment.mode_label,
        "weekend_mode": assessment.weekend_mode,
        "fear_score": assessment.fear_score,
        "dominant_theme": assessment.dominant_theme,
        "market_sentiment": assessment.market_sentiment,
        "global_risk": assessment.global_risk,
        "status": assessment.status,
        "recommended_action": assessment.recommended_action,
        "confidence": assessment.confidence,
        "confidence_threshold": assessment.confidence_threshold,
        "news_bias": assessment.news_bias,
        "rationale": assessment.rationale,
        "divergence_note": assessment.divergence_note,
        "monday_open_prediction": assessment.monday_open_prediction,
        "predicted_gap_pct": assessment.predicted_gap_pct,
        "gift_gap_pct": assessment.gift_gap_pct,
        "friday_nse_close": assessment.friday_nse_close,
        "hedge_strategy": assessment.hedge_strategy,
        "sector_biases": assessment.sector_biases,
        "kill_switch_reason": assessment.kill_switch_reason,
        "available_capital": assessment.available_capital,
        "risk_per_trade": assessment.risk_per_trade,
        "risk_amount": assessment.risk_amount,
        "risk_cap_pct": assessment.risk_cap_pct,
        "candidate": asdict(candidate) if candidate else None,
        "trade_plan": asdict(trade_plan) if trade_plan else None,
        "target_quantity": trade_plan.target_quantity if trade_plan else 0,
        "total_investment_amount": trade_plan.total_investment_amount if trade_plan else 0.0,
        "gift_nifty": (
            {
                "level": assessment.gift_nifty.level,
                "change_points": assessment.gift_nifty.change_points,
                "change_pct": assessment.gift_nifty.change_pct,
                "quote_time": assessment.gift_nifty.quote_time.isoformat(),
                "source": assessment.gift_nifty.source,
                "freshness_label": assessment.gift_nifty.freshness_label,
            }
            if assessment.gift_nifty
            else None
        ),
        "headlines": [
            {
                "title": headline.title,
                "source": headline.source,
                "url": headline.url,
                "published_at": headline.published_at.isoformat(),
                "sentiment_score": headline.sentiment_score,
                "impact_tags": headline.impact_tags,
            }
            for headline in assessment.headlines
        ],
        "snapshots": {
            symbol: {
                **asdict(snapshot),
                "last_trade_time": (
                    snapshot.last_trade_time.isoformat()
                    if snapshot.last_trade_time
                    else None
                ),
            }
            for symbol, snapshot in assessment.snapshots.items()
        },
    }

    report = "\n".join(
        [
            f"## CYCLE UPDATE: {assessment.timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"Mode: {assessment.mode_label}",
            f"Market Sentiment: {assessment.market_sentiment} | Global Risk: {assessment.global_risk}/10 | News Bias: {assessment.news_bias:+.2f}",
            f"AI Fear Score: {assessment.fear_score}/100 | Dominant Theme: {assessment.dominant_theme}",
            "",
            "**ACTIONABLE SIGNAL**",
            assessment.status,
            *signal_block,
            "",
            "**MONDAY OPEN PREDICTION**",
            *monday_open_lines,
            "",
            "**DIVERGENCE CHECK**",
            f"- {assessment.divergence_note}",
            "",
            "**MARKET SNAPSHOT**",
            *(market_lines or ["- Market data unavailable."]),
            "",
            "**TOP HEADLINES**",
            *(headline_lines or ["- No qualifying headlines returned."]),
        ]
    )

    return report, payload


def save_cycle_report(
    report_dir: Path,
    assessment: CycleAssessment,
    report_text: str,
    report_payload: dict,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = assessment.timestamp.strftime("%Y%m%d_%H%M%S")
    markdown_path = report_dir / f"cycle_{stamp}.md"
    json_path = report_dir / f"cycle_{stamp}.json"
    english_summary_path = report_dir / f"english_summary_{stamp}.txt"

    markdown_path.write_text(report_text, encoding="utf-8")
    json_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    english_summary_path.write_text(
        generate_plain_english_report(report_payload),
        encoding="utf-8",
    )
    send_telegram_alert(english_summary_path.read_text(encoding="utf-8"))
