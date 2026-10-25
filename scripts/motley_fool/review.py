"""Claude's own-picks sleeve: once a day Claude sees price stats for the watchlist plus this sleeve's holdings
and decides what to buy and what to sell. Same stocks as the momentum sleeve, but judgment instead of a rule."""

import json
import subprocess
from datetime import date

import sleeves
from ai_decide import _call_claude, _log_decision
from alerts import DATA_DIR, notify
from momentum import MAX_POSITIONS, WEIGHT, WATCHLIST, _closes
from portfolio import daily_loss_tripped

SLEEVE = "review"
LAST_RUN_PATH = DATA_DIR / "review_last_run.json"

SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "action": {"type": "string", "enum": ["buy", "sell"]},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reasoning": {"type": "string"},
                },
                "required": ["symbol", "action", "confidence", "reasoning"],
            },
        }
    },
    "required": ["decisions"],
}

SYSTEM_PROMPT = f"""You manage a small automated paper-trading portfolio, competing against rule-based \
strategies. You get price stats (percent return over 1, 3 and 6 months) for a watchlist of large US stocks, \
plus your current holdings with profit/loss. Hold at most {MAX_POSITIONS} positions, each sized automatically. \
Reply with ONLY a JSON object: {{"decisions": [{{"symbol", "action": "buy" | "sell", "confidence": 0-100, \
"reasoning": "<1-2 sentences>"}}]}}. Only list changes: sell a holding you no longer want, buy a watchlist \
stock you are not holding. An empty list means no changes, which is a fine answer. This is paper trading \
for testing; use your own judgment and be decisive."""


def _stats(closes) -> dict:
    out = {}
    for sym in closes.columns:
        c = closes[sym]
        out[sym] = {f"{m}m_pct": round((c.iloc[-1] / c.iloc[-n] - 1) * 100, 1) for m, n in ((1, 22), (3, 64), (6, 126))}
    return out


def _ask(system_prompt: str, user_prompt: str):
    out = _call_claude(system_prompt, user_prompt, SCHEMA)
    return out, json.loads(out["content"])["decisions"]


def run(client, closes=None, ask=_ask) -> list[str]:
    """One daily pass. Returns notes on what it did (empty if it already ran today or Claude was unreachable)."""
    if LAST_RUN_PATH.exists() and json.loads(LAST_RUN_PATH.read_text())["day"] == date.today().isoformat():
        return []
    closes = _closes() if closes is None else closes
    held = {h["symbol"]: h for h in sleeves.holdings(client, SLEEVE)}
    equity = sleeves.equity(client, SLEEVE)
    ctx = {
        "sleeve_equity": round(equity),
        "max_positions": MAX_POSITIONS,
        "holdings": {s: {"profit_pct": round(h["unrealized_plpc"], 1)} for s, h in held.items()},
        "watchlist": _stats(closes),
    }
    try:
        model_output, decisions = ask(SYSTEM_PROMPT, json.dumps(ctx))
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError, KeyError) as e:
        notify("model_unreachable", f"AI model unreachable for the review sleeve: {e}", dedupe_key="model_unreachable")
        return []  # not marked as run, so the next pipeline run tries again
    notes, killed = [], daily_loss_tripped(client.get_account())
    for d in sorted(decisions, key=lambda d: d["action"] != "sell"):  # sells first, to free slots
        sym, buy = d["symbol"], d["action"] == "buy"
        if buy and (killed or sym in held or sym not in WATCHLIST or len(held) >= MAX_POSITIONS):
            continue
        if buy and sleeves.buy(client, SLEEVE, sym, WEIGHT * equity):
            held[sym] = {}
        elif not buy and sleeves.sell_all(client, SLEEVE, sym):
            held.pop(sym, None)
        else:
            continue
        notes.append(f"{d['action']} {sym}")
        _log_decision(
            {"symbol": sym, "strategy": "review"}, {"sleeve_equity": equity}, model_output,
            {"confidence": d["confidence"], "action": "buy" if buy else "exit", "reasoning": d["reasoning"]},
        )
    LAST_RUN_PATH.write_text(json.dumps({"day": date.today().isoformat()}))
    return notes
