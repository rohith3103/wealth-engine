from __future__ import annotations

import argparse
from datetime import datetime

from wealth_monitor.config import load_config
from wealth_monitor.demo import build_demo_dataset
from wealth_monitor.engine import assess_cycle
from wealth_monitor.markets import fetch_gift_nifty_snapshot, fetch_market_snapshots
from wealth_monitor.news import fetch_market_moving_headlines
from wealth_monitor.reporting import render_cycle_report, save_cycle_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one market-intelligence monitoring cycle."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use synthetic data so the project can be verified without APIs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    timestamp = datetime.now(config.timezone)
    weekend_mode = timestamp.weekday() >= 5

    if args.demo:
        headlines, snapshots, gift_nifty = build_demo_dataset(config)
    else:
        try:
            headlines = fetch_market_moving_headlines(config, weekend_mode=weekend_mode)
        except Exception as exc:
            print(f"Warning: headline fetch failed: {exc}")
            headlines = []
        snapshots = fetch_market_snapshots(config.market_symbols)
        if weekend_mode:
            try:
                gift_nifty = fetch_gift_nifty_snapshot(config)
            except Exception as exc:
                print(f"Warning: GIFT NIFTY fetch failed: {exc}")
                gift_nifty = None
        else:
            gift_nifty = None

    assessment = assess_cycle(
        config=config,
        timestamp=timestamp,
        headlines=headlines,
        snapshots=snapshots,
        gift_nifty=gift_nifty,
    )

    report_text, report_payload = render_cycle_report(assessment)
    print(report_text)
    save_cycle_report(config.report_dir, assessment, report_text, report_payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
