import review
from conftest import FakeClient, position
from test_momentum import _closes


def test_executes_valid_claude_decisions_and_ignores_the_rest(monkeypatch):
    monkeypatch.setattr(review, "_log_decision", lambda *a: None)
    c = FakeClient(equity=100_000, positions=[position("HELD", value=1000)])
    c.history[0].client_order_id = "review:HELD:buy:test"
    syms = {s: 0.5 for s in ("AAPL", "MSFT", "NVDA")}
    syms["HELD"] = 0.1

    def ask(system, user):
        return {}, [
            {"symbol": "HELD", "action": "sell", "confidence": 50, "reasoning": "x"},
            {"symbol": "AAPL", "action": "buy", "confidence": 80, "reasoning": "x"},
            {"symbol": "NOTLISTED", "action": "buy", "confidence": 99, "reasoning": "x"},  # not on the watchlist
        ]

    notes = review.run(c, closes=_closes(syms), ask=ask)
    assert notes == ["sell HELD", "buy AAPL"] and c.closed == ["HELD"]
    assert review.run(c, closes=_closes(syms), ask=ask) == []  # once a day
