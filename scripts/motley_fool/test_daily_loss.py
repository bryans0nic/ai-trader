import alerts
import portfolio
import pytest
import state
from conftest import FakeClient


def _try_buy(monkeypatch, client):
    state.save_state(
        {"picks": {"NEW": {"symbol": "NEW", "confidence": 90, "status": "scored"}}, "last_scraped": None}
    )
    monkeypatch.setattr(portfolio, "_client", lambda: client)
    portfolio.reconcile_new_pick("NEW")
    return client


def test_daily_loss_blocks_buys_once_limit_trips(monkeypatch):
    c = _try_buy(monkeypatch, FakeClient(equity=94_000, last_equity=100_000))  # -6% vs 5% limit
    assert c.orders == []
    assert state.load_state()["picks"]["NEW"]["status"] == "halted_kill_switch"


def test_daily_loss_allows_buys_inside_limit(monkeypatch):
    c = _try_buy(monkeypatch, FakeClient(equity=97_000, last_equity=100_000))  # -3%
    assert len(c.orders) == 1


def test_daily_loss_limit_is_adjustable(monkeypatch):
    alerts.save_settings(daily_loss_pct=2)
    c = _try_buy(monkeypatch, FakeClient(equity=97_000, last_equity=100_000))
    assert c.orders == []
