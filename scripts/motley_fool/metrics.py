"""Live account numbers and performance tracking for the dashboard."""

import time
from datetime import date, datetime

import yfinance as yf
from state import load_state

BENCHMARK = "^GSPC"  # S&P 500
_latest_cache: dict[str, tuple[float, float]] = {}


def price_on(symbol: str, day: str) -> float | None:
    """Close on `day` (YYYY-MM-DD) or the first trading day after it."""
    start = date.fromisoformat(day)
    hist = yf.Ticker(symbol).history(
        start=start.isoformat(), end=(start.replace(year=start.year + 1)).isoformat()
    )
    return float(hist["Close"].iloc[0]) if len(hist) else None


def latest_price(symbol: str) -> float | None:
    hit = _latest_cache.get(symbol)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    hist = yf.Ticker(symbol).history(period="5d")
    if not len(hist):
        return None
    _latest_cache[symbol] = (time.time(), float(hist["Close"].iloc[-1]))
    return _latest_cache[symbol][1]


def pct_change_since(symbol: str, day: str) -> float | None:
    """Percent price change from `day` to now, or None if either price is unavailable."""
    try:
        then, now = price_on(symbol, day), latest_price(symbol)
    except Exception:
        return None
    return None if not then or now is None else (now - then) / then * 100


def account_snapshot(client) -> dict:
    account = client.get_account()
    equity, last_equity = float(account.equity), float(account.last_equity)
    positions = [
        {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "market_value": float(p.market_value),
            "unrealized_pl": float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc) * 100,
        }
        for p in client.get_all_positions()
    ]
    return {
        "equity": equity,
        "cash": float(account.cash),
        "buying_power": float(account.buying_power),
        "day_pl": equity - last_equity,
        "day_pl_pct": (equity - last_equity) / last_equity * 100 if last_equity else 0.0,
        "positions": positions,
        "total_unrealized_pl": sum(p["unrealized_pl"] for p in positions),
    }


def _day(record: dict) -> str:
    return record["timestamp"][:10]


def ignored_performance(decisions: list[dict]) -> list[dict]:
    """Each ignored pick with its price change since the decision (newest first)."""
    rows = [
        {
            "id": r.get("id"),
            "symbol": r["symbol"],
            "day": _day(r),
            "change_pct": pct_change_since(r["symbol"], _day(r)),
        }
        for r in decisions
        if r["decision"]["action"] == "ignore"
    ]
    return rows


def _avg(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _rec_day(rec_date: str) -> str | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(rec_date.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def benchmarks(decisions: list[dict]) -> dict:
    """Equal-weight average % return since each pick's date for: our buys, the S&P 500 over
    the same dates, and every Stock Advisor Buy rec we've seen (a proxy for the scorecard)."""
    buys = [r for r in decisions if r["decision"]["action"] == "buy"]
    ours = _avg([pct_change_since(r["symbol"], _day(r)) for r in buys])
    sp500 = _avg([pct_change_since(BENCHMARK, _day(r)) for r in buys])

    recs = [
        p
        for p in load_state()["picks"].values()
        if p.get("action") == "Buy" and _rec_day(p.get("rec_date", ""))
    ]
    advisor = _avg([pct_change_since(p["symbol"], _rec_day(p["rec_date"])) for p in recs])
    return {
        "ours": ours,
        "sp500": sp500,
        "advisor": advisor,
        "n_buys": len(buys),
        "n_recs": len(recs),
    }
