import portfolio
import state
from conftest import FakeClient, position


def test_already_held_pick_is_not_bought_again(monkeypatch):
    state.save_state(
        {"picks": {"HELD": {"symbol": "HELD", "confidence": 90, "status": "scored"}}, "last_scraped": None}
    )
    c = FakeClient(positions=[position("HELD")])
    monkeypatch.setattr(portfolio, "_client", lambda: c)
    portfolio.reconcile_new_pick("HELD")
    assert c.orders == [] and c.closed == []
