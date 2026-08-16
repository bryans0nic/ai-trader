"""
End-to-end unattended run: scrape Motley Fool Stock Advisor's New Recs
(deterministic), detect anything new since the last run, have the local Qwen
model decide what to do with each new signal, and execute the resulting
trade against the Alpaca paper account. Every AI decision is appended to
data/motley_fool/decisions.jsonl with its full reasoning, whether or not it
led to a trade.

This is the script meant to run unattended (e.g. via Windows Task Scheduler).
It never asks for input; on any hard failure (expired session, scrape
returning nothing, API errors) it raises rather than silently doing nothing,
so a broken run is loud, not invisible.

Usage:
    uv run python scripts/motley_fool/ai_reconcile.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_decide import decide  # noqa: E402
from portfolio import _client, current_holdings, exit_position, reconcile_new_pick  # noqa: E402
from scrape_new_recs import scrape_stock_advisor_rows  # noqa: E402
from state import ingest_scraped_rows, load_state, save_state, set_confidence  # noqa: E402

from ai_trader.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


def build_portfolio_context() -> dict:
    trading_client = _client()
    account = trading_client.get_account()
    holdings = current_holdings(trading_client)
    return {
        "portfolio_value": float(account.portfolio_value),
        "cash": float(account.cash),
        "buying_power": float(account.buying_power),
        "holdings": holdings,  # [{symbol, confidence, market_value}, ...]
        "num_holdings": len(holdings),
        "max_holdings": 10,
    }


def _set_status(symbol: str, status: str) -> None:
    state = load_state()
    if symbol in state["picks"]:
        state["picks"][symbol]["status"] = status
        save_state(state)


def process_pick(pick: dict) -> None:
    symbol = pick["symbol"]
    portfolio_context = build_portfolio_context()

    already_held = any(h["symbol"] == symbol for h in portfolio_context["holdings"])
    if pick["action"] == "Sell" and not already_held:
        logger.info(f"{symbol}: MF Sell signal but we don't hold it. No action.")
        _set_status(symbol, "no_action")
        return

    decision = decide(pick, portfolio_context)
    logger.info(f"{symbol}: AI decision={decision['action']} confidence={decision.get('confidence')} -- {decision['reasoning']}")

    if decision["action"] == "exit":
        exit_position(symbol)  # sets status to "exited"
    elif decision["action"] == "buy":
        set_confidence(symbol, float(decision.get("confidence", 0)))
        reconcile_new_pick(symbol)  # sets status to "active" or "queued_not_bought"
    else:
        _set_status(symbol, "ignored")


def main() -> None:
    logger.info("Scraping Motley Fool Stock Advisor New Recs...")
    rows = scrape_stock_advisor_rows()
    logger.info(f"Scraped {len(rows)} Stock Advisor rows.")

    new_picks = ingest_scraped_rows(rows, seed_baseline=False)
    if not new_picks:
        logger.info("No new picks or sell signals since last run.")
        return

    logger.info(f"{len(new_picks)} new signal(s) detected: {[p['symbol'] for p in new_picks]}")
    for pick in new_picks:
        try:
            process_pick(pick)
        except Exception:
            logger.exception(f"Error processing {pick['symbol']}; continuing with remaining picks.")


if __name__ == "__main__":
    main()
