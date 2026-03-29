from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from wealth_monitor.config import load_config
from wealth_monitor.reporting import generate_gemini_text, send_telegram_alert

IPO_SOURCE_URL = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"
IPO_SYSTEM_PROMPT = (
    "You are an expert IPO analyst for the Indian market. Look at this data for "
    "upcoming IPOs. Write a 3-sentence summary telling the user if there are any "
    "IPOs worth applying for based on a strong Grey Market Premium (GMP). If the GMP "
    "is weak or negative, tell them to avoid it."
)
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0"}
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _parse_numeric_value(text: str) -> float | None:
    matches = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not matches:
        return None
    return float(matches[-1])


def _parse_issue_price(text: str) -> float | None:
    values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))]
    if not values:
        return None
    return max(values)


def _table_after_heading(soup: BeautifulSoup, heading_text: str):
    for table in soup.find_all("table"):
        for prev in table.find_all_previous(["h1", "h2", "h3", "h4"], limit=4):
            if heading_text.lower() in prev.get_text(" ", strip=True).lower():
                return table
    return None


def _parse_issue_window(date_text: str, today: date) -> tuple[date | None, date | None]:
    text = " ".join(date_text.split())
    if re.fullmatch(r"\d{4}", text):
        return None, None

    match = re.match(r"(\d{1,2})-(\d{1,2})\s+([A-Za-z]+)", text)
    if not match:
        return None, None

    start_day = int(match.group(1))
    end_day = int(match.group(2))
    end_month = MONTHS.get(match.group(3).lower())
    if not end_month:
        return None, None

    end_year = today.year
    if end_month < today.month - 6:
        end_year += 1

    if start_day <= end_day:
        start_month = end_month
        start_year = end_year
    else:
        start_month = 12 if end_month == 1 else end_month - 1
        start_year = end_year - 1 if end_month == 1 else end_year

    return date(start_year, start_month, start_day), date(end_year, end_month, end_day)


def _infer_status(date_text: str, today: date) -> str:
    start_date, end_date = _parse_issue_window(date_text, today)
    if start_date is None or end_date is None:
        return "Upcoming"
    if today < start_date:
        return "Upcoming"
    if start_date <= today <= end_date:
        return "Open"
    return "Closed"


def fetch_mainboard_ipos(today: date) -> list[dict]:
    response = requests.get(IPO_SOURCE_URL, timeout=30, headers=HTTP_HEADERS)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    table = _table_after_heading(soup, "Mainboard IPO GMP")
    if table is None:
        raise RuntimeError("Could not find the Mainboard IPO GMP table.")

    rows: list[dict] = []
    for row in table.find_all("tr")[1:]:
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if len(cells) < 5:
            continue

        ipo_name, gmp_text, issue_price_text, _, date_text = cells[:5]
        issue_price = _parse_issue_price(issue_price_text)
        gmp = _parse_numeric_value(gmp_text)
        status = _infer_status(date_text, today)
        expected_listing_gain_pct = (
            round((gmp / issue_price) * 100.0, 2)
            if issue_price and gmp is not None
            else None
        )

        rows.append(
            {
                "ipo_name": ipo_name,
                "normalized_name": _normalize_name(ipo_name),
                "status": status,
                "issue_window": date_text,
                "issue_price": issue_price,
                "gmp": gmp,
                "expected_listing_gain_pct": expected_listing_gain_pct,
                "source_url": IPO_SOURCE_URL,
            }
        )

    return rows


def filter_active_ipos(ipos: list[dict]) -> list[dict]:
    active = [ipo for ipo in ipos if ipo["status"] in {"Upcoming", "Open"}]
    return sorted(
        active,
        key=lambda ipo: (ipo["status"] != "Open", -(ipo["expected_listing_gain_pct"] or -999.0)),
    )


def _fallback_ipo_summary(active_ipos: list[dict]) -> str:
    if not active_ipos:
        return (
            "There are no mainboard IPOs currently open or upcoming in the GMP scan. "
            "There is nothing with a strong grey market premium to act on today. "
            "Avoid applying until a better setup appears."
        )

    strong_ipos = [
        ipo
        for ipo in active_ipos
        if (ipo["gmp"] or 0) > 0 and (ipo["expected_listing_gain_pct"] or 0) >= 10
    ]
    if strong_ipos:
        best = strong_ipos[0]
        return (
            f"There are {len(active_ipos)} active mainboard IPOs in the scan. "
            f"{best['ipo_name']} looks strongest with GMP {best['gmp']:.2f} and an expected listing gain of {best['expected_listing_gain_pct']:.2f}%. "
            "Based on GMP strength, this is the only one worth considering while weaker names should be avoided."
        )

    best = active_ipos[0]
    best_gain = best["expected_listing_gain_pct"] or 0.0
    return (
        f"There are {len(active_ipos)} active mainboard IPOs in the scan. "
        f"The best GMP setup is only {best['ipo_name']} at {best_gain:.2f}%, which is not strong enough to justify confidence. "
        "Avoid applying for now because the grey market signal is weak or negative."
    )


def save_ipo_outputs(report_dir: Path, payload: dict, summary_text: str, stamp: str) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"ipo_scan_{stamp}.json"
    summary_path = report_dir / f"ipo_summary_{stamp}.txt"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary_path.write_text(summary_text, encoding="utf-8")
    return json_path, summary_path


def main() -> int:
    config = load_config()
    timestamp = datetime.now(config.timezone)
    stamp = timestamp.strftime("%Y%m%d_%H%M%S")
    today = timestamp.date()

    try:
        all_ipos = fetch_mainboard_ipos(today)
        active_ipos = filter_active_ipos(all_ipos)
        payload = {
            "timestamp": timestamp.isoformat(),
            "source_url": IPO_SOURCE_URL,
            "scan_type": "mainboard_ipo_gmp",
            "active_ipos_count": len(active_ipos),
            "active_ipos": active_ipos,
        }
        prompt = "Upcoming mainboard IPO GMP data:\n```json\n" + json.dumps(payload, indent=2) + "\n```"
        summary_text = generate_gemini_text(
            prompt=prompt,
            system_prompt=IPO_SYSTEM_PROMPT,
            fallback_text=_fallback_ipo_summary(active_ipos),
        )
    except Exception as exc:
        payload = {
            "timestamp": timestamp.isoformat(),
            "source_url": IPO_SOURCE_URL,
            "scan_type": "mainboard_ipo_gmp",
            "error": str(exc),
            "active_ipos_count": 0,
            "active_ipos": [],
        }
        summary_text = (
            f"The IPO scanner could not fetch today's mainboard GMP data because {exc}. "
            "Do not act on this run. "
            "Retry after the source site is reachable again."
        )

    json_path, summary_path = save_ipo_outputs(config.report_dir, payload, summary_text, stamp)
    send_telegram_alert(summary_path.read_text(encoding="utf-8"))
    print(summary_text)
    print(f"Saved: {json_path}")
    print(f"Saved: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
