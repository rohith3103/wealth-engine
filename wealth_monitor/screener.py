from __future__ import annotations

from collections.abc import Mapping

from wealth_monitor.models import InstrumentSnapshot, ScreenedAsset

DEFENSIVE_HEDGE_SYMBOLS = ("GOLDBEES.NS", "BTC-USD")


def _pct_change(current: float, previous_close: float) -> float:
    if not previous_close:
        return 0.0
    return ((current - previous_close) / previous_close) * 100.0


def _build_screened_asset(
    symbol: str,
    display_name: str,
    current_price: float,
    previous_close: float,
    defensive_hedge: bool,
) -> ScreenedAsset:
    momentum_1d = _pct_change(current_price, previous_close)
    hedge_label = "defensive hedge" if defensive_hedge else "momentum leader"
    rationale = (
        f"{display_name} is the current {hedge_label} with 1-day momentum at "
        f"{momentum_1d:+.2f}%."
    )
    return ScreenedAsset(
        symbol=symbol,
        display_name=display_name,
        current_price=round(current_price, 2),
        previous_close=round(previous_close, 2),
        momentum_1d=round(momentum_1d, 2),
        defensive_hedge=defensive_hedge,
        rationale=rationale,
    )


def fetch_asset_momentum_with_yfinance(
    screener_symbols: Mapping[str, str],
) -> list[ScreenedAsset]:
    import yfinance as yf

    screened_assets: list[ScreenedAsset] = []
    for symbol, display_name in screener_symbols.items():
        history = yf.Ticker(symbol).history(period="10d", interval="1d", auto_adjust=False)
        closes = history["Close"].dropna() if not history.empty else []
        if len(closes) < 2:
            continue

        screened_assets.append(
            _build_screened_asset(
                symbol=symbol,
                display_name=display_name,
                current_price=float(closes.iloc[-1]),
                previous_close=float(closes.iloc[-2]),
                defensive_hedge=symbol in DEFENSIVE_HEDGE_SYMBOLS,
            )
        )

    return screened_assets


def screen_assets_from_snapshots(
    screener_symbols: Mapping[str, str],
    snapshots: Mapping[str, InstrumentSnapshot],
) -> list[ScreenedAsset]:
    screened_assets: list[ScreenedAsset] = []
    for symbol, display_name in screener_symbols.items():
        snapshot = snapshots.get(symbol)
        if not snapshot:
            continue

        previous_close = snapshot.last_price / (1.0 + (snapshot.change_pct_1d / 100.0))
        screened_assets.append(
            _build_screened_asset(
                symbol=symbol,
                display_name=display_name,
                current_price=snapshot.last_price,
                previous_close=previous_close,
                defensive_hedge=symbol in DEFENSIVE_HEDGE_SYMBOLS,
            )
        )

    return screened_assets


def select_target_asset(
    screener_symbols: Mapping[str, str],
    fear_score: int,
    snapshots: Mapping[str, InstrumentSnapshot] | None = None,
) -> ScreenedAsset | None:
    screened_assets = (
        screen_assets_from_snapshots(screener_symbols, snapshots)
        if snapshots is not None
        else fetch_asset_momentum_with_yfinance(screener_symbols)
    )
    if not screened_assets:
        return None

    if fear_score > 75:
        defensive_assets = [
            asset for asset in screened_assets if asset.symbol in DEFENSIVE_HEDGE_SYMBOLS
        ]
        if defensive_assets:
            return max(defensive_assets, key=lambda asset: asset.momentum_1d)

    positive_assets = [asset for asset in screened_assets if asset.momentum_1d > 0]
    if positive_assets:
        return max(positive_assets, key=lambda asset: asset.momentum_1d)

    return max(screened_assets, key=lambda asset: asset.momentum_1d)
