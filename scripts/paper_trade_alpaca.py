"""
Paper-trade an existing ai-trader strategy against Alpaca's paper API.

Runs an unmodified ai-trader Backtrader strategy on a polling loop:
on each cycle it pulls the latest bars from Alpaca, replays them through
the strategy to determine the desired position (long / flat), and
reconciles that against your actual Alpaca paper position via a market
order if they differ.

Note: this uses REST polling rather than Alpaca's streaming API.
alpaca-backtrader-api (the Backtrader+Alpaca integration library) depends
on Alpaca's v1 data-streaming websocket, which Alpaca retired years ago —
every connection to it now fails with HTTP 401, regardless of credentials.
Polling REST bars on an interval is the reliable alternative and only
needs the (fully working) v2 REST API.

Setup:
    1. Create a free Alpaca account and generate PAPER API keys at
       https://app.alpaca.markets/paper/dashboard/overview
    2. Copy .env.example to .env and fill in ALPACA_API_KEY / ALPACA_SECRET_KEY
    3. Run:
       uv run python scripts/paper_trade_alpaca.py --strategy NaiveSMAStrategy --symbol AAPL

This is a long-running process. Stop it with Ctrl+C.
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest
from dotenv import load_dotenv

from ai_trader.backtesting.strategies import classic as classic_strategies
from ai_trader.core.logging import get_logger
from ai_trader.utils.backtest import run_backtest

logger = get_logger(__name__)


def resolve_strategy(name: str):
    import backtrader as bt

    strategy_cls = getattr(classic_strategies, name, None)
    if strategy_cls is None or not issubclass(strategy_cls, bt.Strategy):
        available = ", ".join(classic_strategies.__all__)
        raise SystemExit(f"Unknown strategy '{name}'. Available: {available}")
    return strategy_cls


def fetch_bars(data_client: StockHistoricalDataClient, symbol: str, timeframe: TimeFrame, lookback: int) -> pd.DataFrame:
    # Alpaca's `limit`-only requests default the start window to "today", which
    # returns nothing outside market hours. Always pass an explicit start far
    # enough back to cover `lookback` bars, then trim to the last `lookback` rows.
    calendar_days_back = 14 if timeframe.unit == TimeFrameUnit.Minute else max(10, lookback * 2)
    end = datetime.now(timezone.utc) - timedelta(minutes=16)  # IEX free-tier data has ~15min delay
    start = end - timedelta(days=calendar_days_back)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        feed=DataFeed.IEX,  # free-tier data feed; use DataFeed.SIP if you have a paid subscription
    )
    bars = data_client.get_stock_bars(request).df
    if bars.empty:
        raise RuntimeError(f"No bars returned for {symbol} between {start} and {end}")
    bars = bars.reset_index(level="symbol", drop=True)
    df = bars[["open", "high", "low", "close", "volume"]].tail(lookback).copy()
    df["adj_close"] = df["close"]
    df.index.name = "date"
    return df


def desired_position_is_long(strategy_cls, df: pd.DataFrame, strategy_params: dict) -> bool:
    # The strategy's own logger emits one line per simulated trade, which is
    # noisy since this replay reruns every poll cycle. Silence it locally.
    strategy_logger = logging.getLogger("ai_trader.backtesting.strategies.base")
    previous_level = strategy_logger.level
    strategy_logger.setLevel(logging.WARNING)
    try:
        results = run_backtest(
            strategy=strategy_cls,
            data_source=df,
            cash=1_000_000,
            commission=0.0,
            strategy_params=strategy_params,
            print_output=False,
            plot=False,
        )
    finally:
        strategy_logger.setLevel(previous_level)
    return results[0].position.size > 0


def reconcile_position(trading_client: TradingClient, symbol: str, want_long: bool, notional: float) -> None:
    try:
        position = trading_client.get_open_position(symbol)
        have_long = float(position.qty) > 0
    except Exception:
        have_long = False

    if want_long and not have_long:
        logger.info(f"Signal is LONG, no open position — submitting paper BUY for {symbol} (${notional})")
        order = MarketOrderRequest(
            symbol=symbol,
            notional=notional,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        trading_client.submit_order(order)
    elif not want_long and have_long:
        logger.info(f"Signal is FLAT, position open — closing {symbol}")
        trading_client.close_position(symbol)
    else:
        logger.info(f"No change: want_long={want_long} have_long={have_long}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", required=True, help="Strategy class name, e.g. NaiveSMAStrategy")
    parser.add_argument("--symbol", required=True, help="Ticker to trade, e.g. AAPL")
    parser.add_argument("--timeframe-minutes", type=int, default=5, help="Bar size in minutes (default: 5)")
    parser.add_argument("--lookback", type=int, default=300, help="Bars to fetch for indicator warm-up (default: 300)")
    parser.add_argument("--poll-seconds", type=int, default=300, help="Seconds between polls (default: 300)")
    parser.add_argument("--notional", type=float, default=1000.0, help="Dollar amount per buy order (default: 1000)")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        sys.exit(
            "Missing ALPACA_API_KEY / ALPACA_SECRET_KEY. "
            "Copy .env.example to .env and fill in your paper trading keys."
        )

    strategy_cls = resolve_strategy(args.strategy)
    timeframe = TimeFrame(args.timeframe_minutes, TimeFrameUnit.Minute)

    data_client = StockHistoricalDataClient(api_key, secret_key)
    trading_client = TradingClient(api_key, secret_key, paper=True)

    account = trading_client.get_account()
    logger.info(f"Connected to Alpaca paper account. Status={account.status} Cash=${account.cash}")

    logger.info(
        f"Starting PAPER trading: strategy={strategy_cls.__name__} symbol={args.symbol} "
        f"timeframe={args.timeframe_minutes}m poll={args.poll_seconds}s"
    )

    while True:
        clock = trading_client.get_clock()
        if not clock.is_open:
            logger.info(f"Market closed. Next open: {clock.next_open}. Sleeping {args.poll_seconds}s.")
            time.sleep(args.poll_seconds)
            continue

        try:
            df = fetch_bars(data_client, args.symbol, timeframe, args.lookback)
            want_long = desired_position_is_long(strategy_cls, df, {})
            reconcile_position(trading_client, args.symbol, want_long, args.notional)
        except Exception:
            logger.exception("Error during poll cycle; will retry next cycle")

        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
