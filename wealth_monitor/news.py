from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Iterable

from wealth_monitor.config import MonitorConfig
from wealth_monitor.models import NewsHeadline, NewsSentimentSnapshot


FALLBACK_GEMINI_API_KEY = "AIzaSyAhqG9azzqdegfxu6cG1XnTXfT9KPCwz6o"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_DOMINANT_THEME = "Macro Risk Watch"
THEME_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+")
NEWS_SENTIMENT_SYSTEM_PROMPT = (
    "You are a quantitative macro sentiment model. Convert the provided business "
    "headlines into a strict JSON object with only these fields: "
    "`fear_score` and `dominant_theme`. `fear_score` must be an integer from 1 "
    "to 100, where 100 means extreme global panic. `dominant_theme` must be "
    "exactly 3 words in Title Case, such as `Oil Supply Shock`. Base the result "
    "only on the supplied headlines."
)


NEGATIVE_TERMS = {
    "iran": -2.1,
    "strait of hormuz": -2.8,
    "hormuz": -2.0,
    "war": -2.5,
    "attack": -1.9,
    "missile": -2.2,
    "hawkish": -1.8,
    "inflation": -1.4,
    "tariff": -1.8,
    "sanctions": -1.7,
    "recession": -2.2,
    "layoffs": -1.3,
    "oil spike": -2.1,
    "crude surge": -1.5,
    "yield spike": -1.4,
    "default": -2.8,
    "conflict": -1.8,
}

POSITIVE_TERMS = {
    "rate cut": 2.0,
    "cooling inflation": 1.7,
    "stimulus": 1.8,
    "growth": 1.0,
    "beat": 1.2,
    "record high": 1.1,
    "deal": 1.0,
    "ceasefire": 1.7,
    "de-escalation": 1.8,
    "soft landing": 1.8,
    "surplus": 1.0,
}

IMPACT_TAGS = {
    "iran": "Iran",
    "rbi": "RBI",
    "fed": "FED",
    "gdp": "GDP",
    "war": "War",
    "oil": "Oil",
    "hormuz": "Hormuz",
    "gift nifty": "GIFT",
    "inflation": "Inflation",
    "tariff": "Trade",
    "rupee": "FX",
    "bond": "Rates",
}


def _news_sentiment_path(config: MonitorConfig) -> Path:
    return config.report_dir.parent / "news_sentiment.json"


def _gemini_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", FALLBACK_GEMINI_API_KEY)


def _gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


def _clamp_fear_score(raw_value: object) -> int:
    try:
        value = int(float(raw_value))
    except (TypeError, ValueError):
        value = 50
    return max(1, min(100, value))


def _normalize_theme(raw_value: object) -> str:
    words = [word.title() for word in THEME_WORD_PATTERN.findall(str(raw_value or ""))]
    if not words:
        words = DEFAULT_DOMINANT_THEME.split()
    words = words[:3]
    default_words = DEFAULT_DOMINANT_THEME.split()
    while len(words) < 3:
        words.append(default_words[len(words)])
    return " ".join(words)


def _headline_score(title: str) -> tuple[float, list[str]]:
    lowered = title.lower()
    score = 0.0

    for term, weight in NEGATIVE_TERMS.items():
        if term in lowered:
            score += weight

    for term, weight in POSITIVE_TERMS.items():
        if term in lowered:
            score += weight

    tags = [label for term, label in IMPACT_TAGS.items() if term in lowered]
    return score, sorted(set(tags))


def _parse_articles(articles: Iterable[dict]) -> list[NewsHeadline]:
    parsed: list[NewsHeadline] = []
    for article in articles:
        title = (article.get("title") or "").strip()
        if not title:
            continue

        published_at_raw = article.get("publishedAt")
        if not published_at_raw:
            continue

        published_at = datetime.fromisoformat(
            published_at_raw.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        score, tags = _headline_score(title)
        parsed.append(
            NewsHeadline(
                title=title,
                source=article.get("source", {}).get("name", "Unknown"),
                url=article.get("url", ""),
                published_at=published_at,
                sentiment_score=score,
                impact_tags=tags,
            )
        )

    parsed.sort(key=lambda item: item.published_at, reverse=True)
    return parsed


def _fallback_dominant_theme(headlines: list[NewsHeadline]) -> str:
    tag_counter = Counter(
        tag
        for headline in headlines
        for tag in headline.impact_tags
    )

    if (
        tag_counter["Oil"] + tag_counter["Hormuz"] + tag_counter["Iran"] + tag_counter["War"]
        >= 2
    ):
        return "Oil Supply Shock"
    if tag_counter["FED"] + tag_counter["Inflation"] + tag_counter["Rates"] >= 2:
        return "Fed Policy Shock"
    if tag_counter["GDP"] + tag_counter["Trade"] + tag_counter["FX"] >= 2:
        return "Growth Risk Reset"

    theme_by_tag = {
        "Iran": "Iran Risk Premium",
        "War": "Global War Risk",
        "Oil": "Oil Supply Shock",
        "Hormuz": "Oil Supply Shock",
        "FED": "Fed Policy Shock",
        "RBI": "India Policy Watch",
        "GDP": "Growth Outlook Reset",
        "Inflation": "Inflation Pressure Wave",
        "Trade": "Trade Tension Pulse",
        "FX": "Rupee Stress Signal",
        "GIFT": "Gap Risk Signal",
    }
    if tag_counter:
        return theme_by_tag.get(tag_counter.most_common(1)[0][0], DEFAULT_DOMINANT_THEME)
    return DEFAULT_DOMINANT_THEME


def _fallback_news_sentiment(headlines: list[NewsHeadline]) -> NewsSentimentSnapshot:
    if not headlines:
        return NewsSentimentSnapshot(
            fear_score=45,
            dominant_theme=DEFAULT_DOMINANT_THEME,
        )

    average_score = mean(headline.sentiment_score for headline in headlines[:10])
    negative_count = sum(1 for headline in headlines if headline.sentiment_score < 0)
    strong_negative_count = sum(
        1 for headline in headlines if headline.sentiment_score <= -1.5
    )
    positive_count = sum(1 for headline in headlines if headline.sentiment_score >= 1.0)
    oil_war_count = sum(
        1
        for headline in headlines
        if {"Oil", "Hormuz", "Iran", "War"} & set(headline.impact_tags)
    )

    fear_score = round(
        48
        + max(0.0, -average_score) * 14
        + (negative_count * 2.0)
        + (strong_negative_count * 4.0)
        + (oil_war_count * 2.0)
        - (positive_count * 2.0)
    )
    return NewsSentimentSnapshot(
        fear_score=_clamp_fear_score(fear_score),
        dominant_theme=_normalize_theme(_fallback_dominant_theme(headlines)),
    )


def _generate_news_sentiment_with_gemini(
    headlines: list[NewsHeadline],
) -> NewsSentimentSnapshot:
    if not headlines:
        return _fallback_news_sentiment(headlines)

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_gemini_api_key())
    prompt = "\n".join(
        [
            "Convert these market headlines into structured quantitative sentiment.",
            "Return JSON only.",
            "",
            "Headlines:",
            *[
                f"{index}. {headline.title} ({headline.source})"
                for index, headline in enumerate(headlines[:20], start=1)
            ],
        ]
    )
    response = client.models.generate_content(
        model=_gemini_model(),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=NEWS_SENTIMENT_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema={
                "type": "object",
                "properties": {
                    "fear_score": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "dominant_theme": {
                        "type": "string",
                        "description": "Exactly 3 words in Title Case.",
                    },
                },
                "required": ["fear_score", "dominant_theme"],
                "additionalProperties": False,
            },
            temperature=0.1,
        ),
    )
    raw_text = (response.text or "").strip()
    if not raw_text:
        raise RuntimeError("Gemini returned an empty news sentiment response.")

    payload = json.loads(raw_text)
    return NewsSentimentSnapshot(
        fear_score=_clamp_fear_score(payload.get("fear_score")),
        dominant_theme=_normalize_theme(payload.get("dominant_theme")),
    )


def save_news_sentiment(
    config: MonitorConfig,
    headlines: list[NewsHeadline],
) -> NewsSentimentSnapshot:
    try:
        sentiment = _generate_news_sentiment_with_gemini(headlines)
    except Exception as exc:
        print(f"Warning: Gemini news sentiment failed: {exc}")
        sentiment = _fallback_news_sentiment(headlines)

    _news_sentiment_path(config).write_text(
        json.dumps(
            {
                "fear_score": sentiment.fear_score,
                "dominant_theme": sentiment.dominant_theme,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return sentiment


def load_news_sentiment(
    config: MonitorConfig,
    headlines: list[NewsHeadline] | None = None,
) -> NewsSentimentSnapshot:
    sentiment_path = _news_sentiment_path(config)
    if not sentiment_path.exists():
        return _fallback_news_sentiment(headlines or [])

    try:
        payload = json.loads(sentiment_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Warning: news_sentiment.json could not be read: {exc}")
        return _fallback_news_sentiment(headlines or [])

    return NewsSentimentSnapshot(
        fear_score=_clamp_fear_score(payload.get("fear_score")),
        dominant_theme=_normalize_theme(payload.get("dominant_theme")),
    )


def fetch_market_moving_headlines(
    config: MonitorConfig,
    weekend_mode: bool = False,
) -> list[NewsHeadline]:
    if not config.newsapi_key:
        raise RuntimeError(
            "NEWSAPI_KEY is missing. Set it in .env or environment variables."
        )

    import requests

    now_utc = datetime.now(timezone.utc)
    lookback_hours = max(config.news_lookback_hours, 36) if weekend_mode else config.news_lookback_hours
    since_utc = now_utc - timedelta(hours=lookback_hours)
    query = (
        '(Iran OR war OR oil OR "Gift Nifty" OR Fed OR "Federal Reserve" OR '
        '"Strait of Hormuz") AND (finance OR market)'
        if weekend_mode
        else (
            '(RBI OR "Federal Reserve" OR Fed OR GDP OR inflation OR tariff OR war OR '
            'sanctions OR "crude oil" OR rupee OR yields OR recession) AND '
            "(market OR stocks OR economy OR Nifty OR Nasdaq OR India)"
        )
    )

    response = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": config.news_limit,
            "from": since_utc.isoformat(),
        },
        headers={"X-Api-Key": config.newsapi_key},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    headlines = _parse_articles(payload.get("articles", []))
    save_news_sentiment(config, headlines)
    return headlines
