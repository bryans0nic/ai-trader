"""Persisted state for the Motley Fool -> Alpaca paper trading pipeline."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "motley_fool" / "state.json"


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"picks": {}, "last_scraped": None}
    with open(STATE_PATH) as f:
        return json.load(f)


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)


def ingest_scraped_rows(rows: list[dict], seed_baseline: bool = False) -> list[dict]:
    """
    Merge freshly scraped Stock Advisor rows into state.

    Each row is the full structured record from the New Recs table: symbol,
    company, action, rec_date, type, est_return_low/high, est_max_drawdown,
    market_cap, times_recd, quant_5y (optional, cross-referenced separately).

    If seed_baseline is True (first run), every row is recorded as already-known
    without being queued for a decision. Otherwise, any symbol not already in
    state is a genuinely new pick (or a Sell on a symbol we hold) and gets queued.

    Returns the list of newly-queued picks (empty if seed_baseline).
    """
    state = load_state()
    newly_queued = []

    for row in rows:
        symbol = row["symbol"]
        if symbol in state["picks"]:
            continue  # already seen in a previous scrape

        entry = {
            **row,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "confidence": None,
            "status": "baseline" if seed_baseline else "pending_decision",
        }
        state["picks"][symbol] = entry
        if not seed_baseline:
            newly_queued.append(entry)

    state["last_scraped"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    return newly_queued


def set_confidence(symbol: str, confidence: float) -> dict:
    state = load_state()
    if symbol not in state["picks"]:
        raise KeyError(f"No pending pick for symbol '{symbol}'. Run the scraper first.")
    entry = state["picks"][symbol]
    entry["confidence"] = confidence
    entry["status"] = "scored"
    save_state(state)
    return entry


def get_confidence(symbol: str) -> Optional[float]:
    state = load_state()
    entry = state["picks"].get(symbol)
    return entry["confidence"] if entry else None


def list_pending() -> list[dict]:
    state = load_state()
    return [p for p in state["picks"].values() if p["status"] == "pending_decision"]
