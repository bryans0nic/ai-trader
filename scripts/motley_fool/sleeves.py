"""Strategy sleeves: several strategies share one Alpaca paper account, each with its own slice of money.

Every order a sleeve places carries its name in the client_order_id ("motley_fool:AAPL:buy:1a2b3c4d").
A sleeve's cash and positions are rebuilt from Alpaca's own order history by that prefix, so there is no
second ledger to drift out of sync. Orders without a sleeve prefix (older or manual) belong to no sleeve.
"""

import json
import uuid
from datetime import UTC, datetime

from alerts import DATA_DIR, get_settings
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

SLEEVES = ("motley_fool", "momentum", "review", "news", "spy")  # equal split between all of these
SLEEVES_PATH = DATA_DIR / "sleeves.json"
ORDER_HISTORY_LIMIT = 500  # ponytail: newest 500 orders; paginate by date if a sleeve ever outgrows this


def start_equity(client) -> float:
    """Account equity when the competition began, saved the first time it is needed."""
    if SLEEVES_PATH.exists():
        return float(json.loads(SLEEVES_PATH.read_text())["start_equity"])
    equity = float(client.get_account().equity)
    SLEEVES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SLEEVES_PATH.write_text(json.dumps({"start_equity": equity, "started": datetime.now(UTC).isoformat()}))
    return equity


def allocation(client) -> float:
    return start_equity(client) / len(SLEEVES)


def _sleeve_orders(client, sleeve: str) -> list:
    orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, limit=ORDER_HISTORY_LIMIT))
    mine = [o for o in orders if (getattr(o, "client_order_id", "") or "").startswith(f"{sleeve}:")]
    return sorted(mine, key=lambda o: str(getattr(o, "submitted_at", "")))


def _is_open(order) -> bool:
    return str(getattr(order, "status", "")).lower().rsplit(".", 1)[-1] in {
        "new", "accepted", "pending_new", "partially_filled", "held",
    }


def book(client, sleeve: str) -> dict:
    """{"cash", "positions": {symbol: {"qty", "cost"}}, "trades_today"} for one sleeve."""
    cash = allocation(client)
    positions: dict[str, dict] = {}
    today = datetime.now(UTC).date().isoformat()
    trades_today = trades_total = 0
    for o in _sleeve_orders(client, sleeve):
        side = str(o.side).lower().rsplit(".", 1)[-1]
        if str(o.status).lower().rsplit(".", 1)[-1] not in {"canceled", "expired", "rejected"}:
            trades_total += 1
            trades_today += str(getattr(o, "submitted_at", ""))[:10] == today
        qty = float(getattr(o, "filled_qty", 0) or 0)
        if qty > 0:
            value = qty * float(o.filled_avg_price)
            pos = positions.setdefault(o.symbol, {"qty": 0.0, "cost": 0.0})
            if side == "buy":
                cash -= value
                pos["qty"] += qty
                pos["cost"] += value
            else:
                cash += value
                pos["cost"] *= max(0.0, 1 - qty / pos["qty"]) if pos["qty"] else 0
                pos["qty"] -= qty
        if side == "buy" and _is_open(o):  # money promised to an order still waiting to fill
            cash -= float(o.notional or 0) - qty * float(getattr(o, "filled_avg_price", 0) or 0)
    positions = {s: p for s, p in positions.items() if p["qty"] > 1e-6}
    return {"cash": cash, "positions": positions, "trades_today": trades_today, "trades_total": trades_total}


def prices(client) -> dict[str, float]:
    return {p.symbol: float(p.current_price) for p in client.get_all_positions()}


def holdings(client, sleeve: str, price_map: dict[str, float] | None = None, b: dict | None = None) -> list[dict]:
    """Positions of one sleeve with market value and unrealized P/L %."""
    price_map = prices(client) if price_map is None else price_map
    out = []
    for symbol, p in (b or book(client, sleeve))["positions"].items():
        value = p["qty"] * price_map.get(symbol, p["cost"] / p["qty"])
        out.append({
            "symbol": symbol,
            "qty": p["qty"],
            "market_value": value,
            "unrealized_plpc": (value / p["cost"] - 1) * 100 if p["cost"] else 0.0,
        })
    return out


def equity(client, sleeve: str, price_map: dict[str, float] | None = None) -> float:
    return book(client, sleeve)["cash"] + sum(h["market_value"] for h in holdings(client, sleeve, price_map))


def leaderboard(client) -> list[dict]:
    """One row per sleeve, best return first. Return is measured against the sleeve's starting share."""
    start, price_map = allocation(client), prices(client)
    rows = []
    for sleeve in SLEEVES:
        b = book(client, sleeve)
        held = holdings(client, sleeve, price_map, b)
        value = b["cash"] + sum(h["market_value"] for h in held)
        rows.append({
            "sleeve": sleeve, "equity": value, "return_pct": (value / start - 1) * 100,
            "cash": b["cash"], "positions": len(held), "trades": b["trades_total"],
        })
    return sorted(rows, key=lambda r: -r["return_pct"])


def days_running() -> int:
    if not SLEEVES_PATH.exists():
        return 0
    return (datetime.now(UTC) - datetime.fromisoformat(json.loads(SLEEVES_PATH.read_text())["started"])).days


def _place(client, sleeve: str, symbol: str, side: str, **size) -> None:
    client.submit_order(
        MarketOrderRequest(
            symbol=symbol,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=f"{sleeve}:{symbol}:{side}:{uuid.uuid4().hex[:8]}",
            **size,
        )
    )


def can_trade(client, sleeve: str) -> bool:
    """False once the sleeve has used its trades for today."""
    return book(client, sleeve)["trades_today"] < get_settings()["max_trades_per_sleeve_per_day"]


def buy(client, sleeve: str, symbol: str, notional: float) -> float:
    """Buy up to `notional` dollars with the sleeve's own cash. Returns the dollars actually ordered."""
    b = book(client, sleeve)
    if b["trades_today"] >= get_settings()["max_trades_per_sleeve_per_day"]:
        return 0.0
    notional = round(min(notional, b["cash"]), 2)
    if notional < 1.0:
        return 0.0
    _place(client, sleeve, symbol, "buy", notional=notional)
    return notional


def sell_all(client, sleeve: str, symbol: str) -> bool:
    """Sell the sleeve's whole position in a symbol (never another sleeve's shares)."""
    pos = book(client, sleeve)["positions"].get(symbol)
    if not pos:
        return False
    _place(client, sleeve, symbol, "sell", qty=round(pos["qty"], 6))
    return True
