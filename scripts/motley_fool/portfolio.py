"""
Reconcile the Alpaca paper portfolio against confidence-scored Motley Fool picks.

Rule: hold at most MAX_HOLDINGS positions, ranked by confidence. A newly-scored
pick can only enter by beating the lowest-confidence current holding (once the
portfolio is full). Position size scales with confidence between MIN_WEIGHT and
MAX_WEIGHT of total portfolio value.

Holdings with no confidence on file (e.g. bought manually, outside this
pipeline) are treated as confidence=0 -- unscored positions are not protected
from being supplanted.
"""

import os
import sys

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from state import get_confidence, load_state, save_state  # noqa: E402

from ai_trader.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

MAX_HOLDINGS = 10
MIN_WEIGHT = 0.05
MAX_WEIGHT = 0.20


def _client() -> TradingClient:
    load_dotenv()
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        sys.exit("Missing ALPACA_API_KEY / ALPACA_SECRET_KEY in .env")
    return TradingClient(api_key, secret_key, paper=True)


def target_weight(confidence: float) -> float:
    """Map a 0-100 confidence score to a portfolio weight in [MIN_WEIGHT, MAX_WEIGHT]."""
    confidence = max(0.0, min(100.0, confidence))
    return MIN_WEIGHT + (MAX_WEIGHT - MIN_WEIGHT) * (confidence / 100.0)


def current_holdings(trading_client: TradingClient) -> list[dict]:
    positions = trading_client.get_all_positions()
    holdings = []
    for p in positions:
        confidence = get_confidence(p.symbol) or 0.0
        holdings.append({"symbol": p.symbol, "confidence": confidence, "market_value": float(p.market_value)})
    return holdings


def reconcile_new_pick(symbol: str) -> None:
    """Given a symbol that just received a confidence score, decide whether to trade it."""
    confidence = get_confidence(symbol)
    if confidence is None:
        raise ValueError(f"{symbol} has no confidence score on file")

    trading_client = _client()
    account = trading_client.get_account()
    portfolio_value = float(account.portfolio_value)
    holdings = current_holdings(trading_client)

    already_held = any(h["symbol"] == symbol for h in holdings)
    if already_held:
        logger.info(f"{symbol} is already held; confidence updated but no trade needed.")
        return

    weight = target_weight(confidence)
    desired_notional = weight * portfolio_value

    if len(holdings) < MAX_HOLDINGS:
        logger.info(
            f"Portfolio has {len(holdings)}/{MAX_HOLDINGS} holdings. "
            f"Buying {symbol} (confidence={confidence}, target weight={weight:.1%}, notional=${desired_notional:,.2f})"
        )
        _buy(trading_client, symbol, desired_notional, account)
        return

    weakest = min(holdings, key=lambda h: h["confidence"])
    if confidence <= weakest["confidence"]:
        logger.info(
            f"Portfolio full ({MAX_HOLDINGS} holdings). {symbol} confidence={confidence} does not "
            f"beat weakest holding {weakest['symbol']} (confidence={weakest['confidence']}). No trade."
        )
        state = load_state()
        state["picks"][symbol]["status"] = "queued_not_bought"
        save_state(state)
        return

    logger.info(
        f"Portfolio full. {symbol} (confidence={confidence}) beats weakest holding "
        f"{weakest['symbol']} (confidence={weakest['confidence']}). Supplanting."
    )
    trading_client.close_position(weakest["symbol"])
    logger.info(f"Closed {weakest['symbol']}.")

    account = trading_client.get_account()
    _buy(trading_client, symbol, desired_notional, account)


def exit_position(symbol: str) -> None:
    """Close a held position outright (e.g. AI-recommended exit on an MF Sell signal)."""
    trading_client = _client()
    holdings = current_holdings(trading_client)
    if not any(h["symbol"] == symbol for h in holdings):
        logger.info(f"{symbol} is not currently held; nothing to exit.")
        return

    trading_client.close_position(symbol)
    logger.info(f"Closed {symbol} on AI-recommended exit.")

    state = load_state()
    if symbol in state["picks"]:
        state["picks"][symbol]["status"] = "exited"
        save_state(state)


def _buy(trading_client: TradingClient, symbol: str, notional: float, account) -> None:
    buying_power = float(account.buying_power)
    notional = min(notional, buying_power)
    if notional < 1.0:
        logger.warning(f"Insufficient buying power (${buying_power:,.2f}) to buy {symbol}. Skipping.")
        return

    order = MarketOrderRequest(
        symbol=symbol,
        notional=round(notional, 2),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    trading_client.submit_order(order)
    logger.info(f"Submitted paper BUY: {symbol} notional=${notional:,.2f}")

    state = load_state()
    if symbol in state["picks"]:
        state["picks"][symbol]["status"] = "active"
        save_state(state)


def print_status() -> None:
    trading_client = _client()
    account = trading_client.get_account()
    holdings = current_holdings(trading_client)
    state = load_state()

    print(f"Portfolio value: ${float(account.portfolio_value):,.2f}  Cash: ${float(account.cash):,.2f}")
    print(f"Holdings ({len(holdings)}/{MAX_HOLDINGS}):")
    for h in sorted(holdings, key=lambda x: -x["confidence"]):
        print(f"  {h['symbol']:<6} confidence={h['confidence']:>5.1f}  value=${h['market_value']:,.2f}")

    pending = [p for p in state["picks"].values() if p["status"] == "pending_decision"]
    if pending:
        print(f"\nPending AI decision ({len(pending)}):")
        for p in pending:
            quant = f" (MF Quant:5Y={p['quant_5y']})" if p.get("quant_5y") is not None else ""
            print(f"  {p['symbol']:<6} {p['action']} rec'd {p['rec_date']}{quant}")


if __name__ == "__main__":
    print_status()
