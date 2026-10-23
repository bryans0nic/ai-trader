import alerts
import portfolio
import pytest


def test_client_is_always_paper(monkeypatch):
    seen = {}
    monkeypatch.setattr(portfolio, "load_dotenv", lambda: None)
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    monkeypatch.setattr(portfolio, "TradingClient", lambda *a, **kw: seen.update(kw))
    portfolio._client()
    assert seen == {"paper": True}


def test_no_setting_can_turn_off_paper_mode():
    assert not any("paper" in k or "live" in k for k in alerts.DEFAULTS)
    with pytest.raises(KeyError):
        alerts.save_settings(paper=False)
