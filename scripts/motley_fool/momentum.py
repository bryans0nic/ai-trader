"""Momentum sleeve: once a day, rank a watchlist by 6-month return (skipping the last month), let Claude vet
the leaders, hold the top few, and rotate out names that have fallen well down the ranking."""

import json
from datetime import date

import sleeves
import yfinance as yf
from ai_decide import decide
from alerts import DATA_DIR
from portfolio import daily_loss_tripped

SLEEVE = "momentum"
# ponytail: fixed list of liquid large caps; swap for a fetched S&P 500 list if it needs to be wider
WATCHLIST = (
    "AAPL MSFT NVDA AMZN GOOGL META AVGO TSLA LLY JPM V UNH XOM MA COST HD PG NFLX ORCL CRM AMD ADBE WMT "
    "BAC KO PEP CSCO ABBV MRK TMO MCD ACN LIN GE CAT NOW IBM QCOM UBER INTU"
).split()
MAX_POSITIONS = 5
WEIGHT = 0.20  # of the sleeve's equity per position
KEEP_RANK = 15  # a holding is sold once it falls below this rank
LAST_RUN_PATH = DATA_DIR / "momentum_last_run.json"

SYSTEM_PROMPT = """You vet buy candidates for an automated paper-trading momentum strategy. You get one \
stock from a watchlist that ranks near the top by 6-month price return (skipping the latest month), plus \
the strategy's current holdings. Reply with ONLY one JSON object:
{"confidence": <0-100>, "action": "buy" | "ignore", "reasoning": "<2-3 sentences>"}
Say "buy" unless something specific argues against it (e.g. a known blow-up, an extreme one-off spike, \
or too much overlap with what is already held). This is paper trading for testing: be decisive."""


def rank(closes) -> list[str]:
    """Symbols best-first by return from 6 months ago to 1 month ago."""
    score = closes.iloc[-22] / closes.iloc[-126] - 1
    return list(score.dropna().sort_values(ascending=False).index)


def _closes():
    return yf.download(WATCHLIST, period="8mo", progress=False, auto_adjust=True)["Close"]


def _ran_today() -> bool:
    return LAST_RUN_PATH.exists() and json.loads(LAST_RUN_PATH.read_text())["day"] == date.today().isoformat()


def run(client, closes=None, vet=decide) -> list[str]:
    """One daily pass. Returns notes on what it did (empty if it already ran today)."""
    if _ran_today():
        return []
    ranked = rank(_closes() if closes is None else closes)
    notes = []
    for h in sleeves.holdings(client, SLEEVE):
        if h["symbol"] not in ranked[:KEEP_RANK] and sleeves.sell_all(client, SLEEVE, h["symbol"]):
            notes.append(f"sold {h['symbol']}")
    held = {h["symbol"] for h in sleeves.holdings(client, SLEEVE)}
    slots = MAX_POSITIONS - len(held)
    if slots > 0 and not daily_loss_tripped(client.get_account()):
        for symbol in [s for s in ranked[:MAX_POSITIONS] if s not in held][:slots]:
            equity = sleeves.equity(client, SLEEVE)
            pick = {"symbol": symbol, "strategy": "momentum", "rank": ranked.index(symbol) + 1}
            ctx = {"sleeve_equity": equity, "holdings": sorted(held)}
            if vet(pick, ctx, SYSTEM_PROMPT)["action"] == "buy" and sleeves.buy(client, SLEEVE, symbol, WEIGHT * equity):
                notes.append(f"bought {symbol}")
    LAST_RUN_PATH.write_text(json.dumps({"day": date.today().isoformat()}))
    return notes
