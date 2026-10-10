"""Live account numbers and performance tracking for the dashboard."""

import time
from datetime import UTC, date, datetime, timedelta

import yfinance as yf
from state import load_state

BENCHMARK = "^GSPC"  # S&P 500
_latest_cache: dict[str, tuple[float, float]] = {}


_close_cache: dict[tuple[str, str], float] = {}  # historical closes don't change


def price_on(symbol: str, day: str) -> float | None:
    """Close on `day` (YYYY-MM-DD) or the first trading day after it."""
    if (symbol, day) in _close_cache:
        return _close_cache[symbol, day]
    start = date.fromisoformat(day)
    hist = yf.Ticker(symbol).history(
        start=start.isoformat(), end=(start + timedelta(days=366)).isoformat()
    )
    if not len(hist):
        return None  # not cached: today's close may simply not exist yet
    _close_cache[symbol, day] = float(hist["Close"].iloc[0])
    return _close_cache[symbol, day]


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
            "avg_entry_price": float(getattr(p, "avg_entry_price", 0) or 0),
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


def recent_orders(client, limit: int = 15) -> list[dict]:
    """Latest orders in any state (queued, filled, cancelled), newest first."""
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit))
    return [
        {
            "symbol": o.symbol,
            "side": getattr(o.side, "value", str(o.side)),
            "status": getattr(o.status, "value", str(o.status)).replace("_", " "),
            "qty": float(o.qty) if o.qty else None,
            "notional": float(o.notional) if o.notional else None,
            "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
            "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
        }
        for o in orders
    ]


RANGES = {"1w": "1W", "1m": "1M", "1y": "1A"}


def equity_history(client, range_key: str = "1m") -> list[tuple[str, float]]:
    """[(YYYY-MM-DD, account equity)] for the range, oldest first, skipping days before funding."""
    from alpaca.trading.requests import GetPortfolioHistoryRequest

    h = client.get_portfolio_history(
        GetPortfolioHistoryRequest(period=RANGES.get(range_key, "1M"), timeframe="1D")
    )
    return [
        (datetime.fromtimestamp(ts, UTC).date().isoformat(), float(eq))
        for ts, eq in zip(h.timestamp, h.equity, strict=False)
        if eq
    ]


def sp500_closes(start_day: str) -> dict[str, float]:
    """{YYYY-MM-DD: S&P 500 close} from start_day (a few days earlier, to cover weekends)."""
    start = date.fromisoformat(start_day) - timedelta(days=5)
    hist = yf.Ticker(BENCHMARK).history(start=start.isoformat())
    return {ts.date().isoformat(): float(close) for ts, close in hist["Close"].items()}


def equity_vs_sp500(client, range_key: str = "1m") -> list[dict]:
    """Per day: % change since the start of the range for the account and for the S&P 500."""
    history = equity_history(client, range_key)
    if len(history) < 2:
        return []
    closes = sp500_closes(history[0][0])
    days = sorted(closes)
    rows, base_sp = [], None
    for day, equity in history:
        prior = [d for d in days if d <= day]  # last close on or before this day
        sp = closes[prior[-1]] if prior else None
        base_sp = base_sp or sp
        rows.append(
            {
                "day": day,
                "equity": equity,
                "portfolio": (equity / history[0][1] - 1) * 100,
                "sp500": (sp / base_sp - 1) * 100 if sp and base_sp else None,
            }
        )
    return rows
