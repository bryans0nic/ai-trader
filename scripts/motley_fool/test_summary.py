import metrics
from summary import render


def _rec(action, sym):
    return {"timestamp": "2026-10-01T10:00:00+00:00", "symbol": sym, "decision": {"action": action}}


def test_totals(monkeypatch):
    moves = {"A": -5.0, "B": 3.0, "C": 10.0, "^GSPC": 4.0}
    monkeypatch.setattr(metrics, "pct_change_since", lambda s, d: moves[s])
    s = metrics.summarize([_rec("ignore", "A"), _rec("ignore", "B"), _rec("buy", "C")])
    assert (s["ignores"], s["ignores_won"], s["buys"], s["buys_won"]) == (2, 1, 1, 1)
    assert s["diff_avg"] == 6.0
    assert "+6.0%" in render(s)


def test_empty():
    assert metrics.summarize([])["diff_avg"] is None
