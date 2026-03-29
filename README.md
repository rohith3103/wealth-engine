# Wealth Intelligence Monitor

This project builds a local market-monitoring loop that:

- pulls macro-sensitive headlines from NewsAPI
- fetches 15-minute market data from yfinance
- scores news/price divergence
- switches into a weekend Monday-gap workflow when Indian cash markets are shut
- scrapes a public GIFT NIFTY quote page for the latest available weekend reference
- sizes valid intraday signals using available capital and per-trade risk inputs
- writes a plain-English summary file using Gemini-compatible SDK support
- applies a kill-switch before surfacing any setup as worth manual review
- saves a timestamped markdown and JSON report for each cycle

## Important safety notes

- The code does **not** place trades or submit orders to Zerodha.
- The code does **not** hardcode API keys. Set them in `.env` or your shell environment.
- If the API keys you shared are real, rotate them. They should be treated as exposed credentials.
- Confidence scores are heuristic and are **not** a promise of edge or execution quality.

## Setup

1. Create a virtual environment if you want one:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in `NEWSAPI_KEY`.

   Optional sizing and summary variables:

   - `AVAILABLE_CAPITAL`
   - `RISK_PER_TRADE`
   - `GEMINI_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

4. Run a demo cycle without external APIs:

   ```powershell
   python .\run_cycle.py --demo
   ```

5. Run a live monitoring cycle:

   ```powershell
   python .\run_cycle.py
   ```

6. Run the standalone IPO scanner:

   ```powershell
   python .\ipo_scanner.py
   ```

## 15-minute execution

You have two local options:

- `run_loop.ps1` keeps the process alive and runs every 15 minutes.
- `register_task.ps1` registers a Windows Scheduled Task that runs every 15 minutes.

Neither helper is auto-enabled. You choose if and when to run them.

## Output

Each cycle writes two files under `reports/`:

- `cycle_YYYYMMDD_HHMMSS.md`
- `cycle_YYYYMMDD_HHMMSS.json`
- `english_summary_YYYYMMDD_HHMMSS.txt`

The IPO scanner writes:

- `ipo_scan_YYYYMMDD_HHMMSS.json`
- `ipo_summary_YYYYMMDD_HHMMSS.txt`

If Telegram credentials are present, each cycle also pushes the plain-English summary to your Telegram chat.

The report format is intentionally conservative. If the kill-switch fires or confidence is below threshold, the cycle prints:

`STATUS: MONITORING - NO TRADE`

On Saturdays and Sundays, the engine automatically ignores 15-minute tape and produces a `MONDAY OPEN PREDICTION` plus `Hedge Strategy` instead.
