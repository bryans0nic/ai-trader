import alerts
import portfolio
import pytest
import state
from conftest import FakeClient, position


@pytest.fixture
def run(monkeypatch):
    def _run(symbol, confidence, client):
        state.save_state(
            {
                "picks": {symbol: {"symbol": symbol, "confidence": confidence, "status": "scored"}},
                "last_scraped": None,
            }
        )
        monkeypatch.setattr(portfolio, "_client", lambda: client)
        portfolio.reconcile_new_pick(symbol)
        return client

    return _run


def test_target_weight_scales_and_clamps():
    assert portfolio.target_weight(0) == pytest.approx(0.05)
    assert portfolio.target_weight(100) == pytest.approx(0.20)
    assert portfolio.target_weight(50) == pytest.approx(0.125)
    assert portfolio.target_weight(500) == pytest.approx(0.20)
    assert portfolio.target_weight(-5) == pytest.approx(0.05)


def test_position_size_is_weight_of_portfolio(run):
    c = run("NEW", 100, FakeClient(equity=100_000))
    # the sleeve holds 1/5 of the account ($20k), and 100 confidence means 20% of it
    assert len(c.orders) == 1 and c.orders[0].notional == pytest.approx(4_000)
    assert state.load_state()["picks"]["NEW"]["status"] == "active"


def test_sleeve_cash_caps_then_skips(run):
    # sleeve holds $18k of its $20k, so only $2k of cash is left
    c = run("NEW", 100, FakeClient(equity=100_000, positions=[position("OLD", value=18_000)]))
    assert c.orders[0].notional == pytest.approx(2_000)  # capped to the sleeve's cash
    c = run("NEW", 100, FakeClient(equity=100_000, positions=[position("OLD", value=19_999.5)]))
    assert c.orders == []  # < $1: skipped


def test_other_sleeves_money_is_not_touched(run):
    c = run("NEW", 100, FakeClient(equity=100_000, buying_power=100_000))
    assert c.orders[0].notional <= 20_000 and c.orders[0].client_order_id.startswith("motley_fool:NEW:buy:")


def test_trade_cap_blocks_buys(run):
    alerts.save_settings(max_trades_per_sleeve_per_day=0)
    assert run("NEW", 100, FakeClient()).orders == []


def _full_portfolio(weakest_conf):
    syms = [f"S{i}" for i in range(10)]
    confs = {s: 50 + i for i, s in enumerate(syms)}
    confs["S0"] = weakest_conf
    st = {
        "picks": {s: {"symbol": s, "confidence": confs[s], "status": "active"} for s in syms},
        "last_scraped": None,
    }
    return FakeClient(positions=[position(s) for s in syms]), st


def test_full_portfolio_supplants_weakest_when_beaten(monkeypatch):
    c, st = _full_portfolio(weakest_conf=40)
    st["picks"]["NEW"] = {"symbol": "NEW", "confidence": 90, "status": "scored"}
    state.save_state(st)
    monkeypatch.setattr(portfolio, "_client", lambda: c)
    portfolio.reconcile_new_pick("NEW")
    assert c.closed == ["S0"] and c.orders[-1].symbol == "NEW"


def test_full_portfolio_no_trade_when_not_beating_weakest(monkeypatch):
    c, st = _full_portfolio(weakest_conf=40)
    st["picks"]["NEW"] = {
        "symbol": "NEW",
        "confidence": 40,
        "status": "scored",
    }  # tie does not supplant
    state.save_state(st)
    monkeypatch.setattr(portfolio, "_client", lambda: c)
    portfolio.reconcile_new_pick("NEW")
    assert c.closed == [] and c.orders == []
    assert state.load_state()["picks"]["NEW"]["status"] == "queued_not_bought"


# --- stop-loss / kill switch / settings (S8, S9, S10, S17) ---


def test_stop_loss_sells_and_notifies():
    c = FakeClient(positions=[position("BAD", plpc=-0.12), position("OK", plpc=-0.05)])
    assert portfolio.check_stop_losses(c) == ["BAD"]
    assert c.closed == ["BAD"]
    assert [a["kind"] for a in alerts.load_alerts()] == ["stop_loss"]


def test_limits_default_then_adjustable():
    s = alerts.get_settings()
    assert (s["stop_loss_pct"], s["daily_loss_pct"], s["trading_paused"]) == (10.0, 5.0, False)
    c = FakeClient(positions=[position("A", plpc=-0.07)])
    assert portfolio.check_stop_losses(c) == []  # -7% inside default 10%
    alerts.save_settings(stop_loss_pct=5)
    assert portfolio.check_stop_losses(c) == ["A"]  # now past the 5% limit
    with pytest.raises(ValueError):
        alerts.save_settings(stop_loss_pct=0)


def test_kill_switch_blocks_buys_and_alerts_once(run):
    c = run("NEW", 90, FakeClient(equity=94_000, last_equity=100_000))  # -6% today
    assert c.orders == []
    assert state.load_state()["picks"]["NEW"]["status"] == "halted_kill_switch"
    run("NEW", 90, FakeClient(equity=94_000, last_equity=100_000))
    assert [a["kind"] for a in alerts.load_alerts()] == ["kill_switch"]  # deduped per day


def test_kill_switch_not_tripped_inside_limit(run):
    c = run("NEW", 90, FakeClient(equity=97_000, last_equity=100_000))  # -3%
    assert len(c.orders) == 1
    alerts.save_settings(daily_loss_pct=2)
    c = run("NEW", 90, FakeClient(equity=97_000, last_equity=100_000))
    assert c.orders == []


def test_stop_loss_skips_exempt_and_pending_orders():
    from types import SimpleNamespace

    c = FakeClient(
        positions=[
            position("EX", plpc=-0.2),
            position("PEND", plpc=-0.2),
            position("BAD", plpc=-0.2),
        ]
    )
    c.open_orders = [SimpleNamespace(symbol="PEND")]
    alerts.set_stop_loss_exempt("EX", True)
    assert portfolio.check_stop_losses(c) == ["BAD"]
    alerts.set_stop_loss_exempt("EX", False)
    assert portfolio.check_stop_losses(c) == ["EX"]


def test_manual_sell_only_for_held_symbols():
    c = FakeClient(positions=[position("AAA")])
    portfolio.manual_sell(c, "AAA")
    assert c.closed == ["AAA"] and alerts.load_alerts()[0]["kind"] == "manual_sell"
    with pytest.raises(ValueError):
        portfolio.manual_sell(c, "ZZZ")
