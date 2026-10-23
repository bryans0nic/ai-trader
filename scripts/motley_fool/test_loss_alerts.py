import alerts
import ai_reconcile
import portfolio
import state
from conftest import FakeClient, position


def test_lowered_stop_loss_limit_alerts_on_trip(monkeypatch):
    alerts.save_settings(stop_loss_pct=2)
    monkeypatch.setattr(ai_reconcile, "_client", lambda: FakeClient(positions=[position("DIP", plpc=-0.03)]))
    sold = ai_reconcile.check_stop_losses(ai_reconcile._client())
    assert sold == ["DIP"]
    [a] = alerts.load_alerts()
    assert a["kind"] == "stop_loss" and "DIP" in a["message"]


def test_lowered_daily_loss_limit_alerts_on_trip(monkeypatch):
    alerts.save_settings(daily_loss_pct=1)
    state.save_state({"picks": {"NEW": {"symbol": "NEW", "confidence": 90, "status": "scored"}}, "last_scraped": None})
    monkeypatch.setattr(portfolio, "_client", lambda: FakeClient(equity=98_000, last_equity=100_000))  # -2%
    portfolio.reconcile_new_pick("NEW")
    [a] = alerts.load_alerts()
    assert a["kind"] == "kill_switch" and "halted" in a["message"]


def test_no_alert_inside_limits(monkeypatch):
    c = FakeClient(equity=99_500, last_equity=100_000, positions=[position("OK", plpc=-0.01)])
    assert portfolio.check_stop_losses(c) == [] and not portfolio.daily_loss_tripped(c.account)
    assert alerts.load_alerts() == []
