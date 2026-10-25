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
from datetime import date

from alpaca.trading.client import TradingClient
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
import sleeves  # noqa: E402
from alerts import get_settings, notify  # noqa: E402
from state import get_confidence, load_state, save_state  # noqa: E402

from ai_trader.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

SLEEVE = "motley_fool"  # this module trades only this sleeve
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


def daily_loss_tripped(account) -> bool:
    """True (and alerts once per day) when equity is down past the daily-loss limit vs last close."""
    last_equity = float(account.last_equity)
    if last_equity <= 0:
        return False
    change_pct = (float(account.equity) - last_equity) / last_equity * 100
    limit = get_settings()["daily_loss_pct"]
    if change_pct > -limit:
        return False
    notify(
        "kill_switch",
        f"Daily-loss kill switch tripped: portfolio {change_pct:.2f}% today (limit -{limit:g}%). New buys halted.",
        dedupe_key=f"kill_switch:{date.today().isoformat()}",
    )
    return True


def check_stop_losses(trading_client: TradingClient) -> list[str]:
    """Place a sell for any sleeve holding whose unrealized loss is past the stop-loss limit, skipping
    exempt symbols and ones that already have an order waiting. Returns the symbols sold."""
    settings = get_settings()
    limit = settings["stop_loss_pct"]
    skip = set(settings["stop_loss_exempt"]) | {o.symbol for o in trading_client.get_orders()}
    price_map = sleeves.prices(trading_client)
    sold = []
    for sleeve in sleeves.SLEEVES:
        for h in sleeves.holdings(trading_client, sleeve, price_map):
            loss_pct = h["unrealized_plpc"]
            if loss_pct > -limit or h["symbol"] in skip:
                continue
            sleeves.sell_all(trading_client, sleeve, h["symbol"])
            sold.append(h["symbol"])
            notify(
                "stop_loss",
                f"Stop-loss ({sleeve}): sell order placed for {h['symbol']} at {loss_pct:.2f}% (limit -{limit:g}%).",
            )
            _set_pick_status(h["symbol"], "stopped_out")
    return sold


def manual_sell(trading_client: TradingClient, symbol: str) -> None:
    """Sell a holding on request from the dashboard, out of every sleeve that holds it."""
    sold_from = [s for s in sleeves.SLEEVES if sleeves.sell_all(trading_client, s, symbol)]
    if not sold_from:
        if not any(p.symbol == symbol for p in trading_client.get_all_positions()):
            raise ValueError(f"{symbol} is not currently held.")
        trading_client.close_position(symbol)  # held outside every sleeve (bought by hand)
    notify("manual_sell", f"Manual sell order placed for {symbol} from the dashboard.")
    _set_pick_status(symbol, "sold_manually")


def _set_pick_status(symbol: str, status: str) -> None:
    state = load_state()
    if symbol in state["picks"]:
        state["picks"][symbol]["status"] = status
        save_state(state)


def current_holdings(trading_client: TradingClient, sleeve: str = SLEEVE) -> list[dict]:
    return [
        {
            "symbol": h["symbol"],
            "confidence": get_confidence(h["symbol"]) or 0.0,
            "market_value": h["market_value"],
        }
        for h in sleeves.holdings(trading_client, sleeve)
    ]


def reconcile_new_pick(symbol: str) -> None:
    """Given a symbol that just received a confidence score, decide whether to trade it."""
    confidence = get_confidence(symbol)
    if confidence is None:
        raise ValueError(f"{symbol} has no confidence score on file")

    trading_client = _client()
    account = trading_client.get_account()
    portfolio_value = sleeves.equity(trading_client, SLEEVE)
    holdings = current_holdings(trading_client)

    if daily_loss_tripped(account):
        logger.warning(f"Kill switch active; not buying {symbol}.")
        state = load_state()
        state["picks"][symbol]["status"] = "halted_kill_switch"
        save_state(state)
        return

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
        _buy(trading_client, symbol, desired_notional)
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
    sleeves.sell_all(trading_client, SLEEVE, weakest["symbol"])
    logger.info(f"Closed {weakest['symbol']}.")
    _buy(trading_client, symbol, desired_notional)


def exit_position(symbol: str) -> None:
    """Close a held position outright (e.g. AI-recommended exit on an MF Sell signal)."""
    trading_client = _client()
    holdings = current_holdings(trading_client)
    if not any(h["symbol"] == symbol for h in holdings):
        logger.info(f"{symbol} is not currently held; nothing to exit.")
        return

    sleeves.sell_all(trading_client, SLEEVE, symbol)
    logger.info(f"Closed {symbol} on AI-recommended exit.")

    state = load_state()
    if symbol in state["picks"]:
        state["picks"][symbol]["status"] = "exited"
        save_state(state)


def _buy(trading_client: TradingClient, symbol: str, notional: float) -> None:
    spent = sleeves.buy(trading_client, SLEEVE, symbol, notional)
    if not spent:
        logger.warning(f"Sleeve {SLEEVE} has no cash or no trades left today; skipping {symbol}.")
        return
    logger.info(f"Submitted paper BUY: {symbol} notional=${spent:,.2f}")

    state = load_state()
    if symbol in state["picks"]:
        state["picks"][symbol]["status"] = "active"
        save_state(state)


def print_status() -> None:
    trading_client = _client()
    account = trading_client.get_account()
    holdings = current_holdings(trading_client)
    state = load_state()

    print(
        f"Account value: ${float(account.portfolio_value):,.2f}  "
        f"{SLEEVE} sleeve: ${sleeves.equity(trading_client, SLEEVE):,.2f}, "
        f"cash ${sleeves.book(trading_client, SLEEVE)['cash']:,.2f}"
    )
    print(f"Holdings ({len(holdings)}/{MAX_HOLDINGS}):")
    for h in sorted(holdings, key=lambda x: -x["confidence"]):
        print(
            f"  {h['symbol']:<6} confidence={h['confidence']:>5.1f}  value=${h['market_value']:,.2f}"
        )

    pending = [p for p in state["picks"].values() if p["status"] == "pending_decision"]
    if pending:
        print(f"\nPending AI decision ({len(pending)}):")
        for p in pending:
            quant = f" (MF Quant:5Y={p['quant_5y']})" if p.get("quant_5y") is not None else ""
            print(f"  {p['symbol']:<6} {p['action']} rec'd {p['rec_date']}{quant}")


if __name__ == "__main__":
    print_status()
