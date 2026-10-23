import metrics


def _rec(action, price=None):
    return {
        "timestamp": "2026-10-01T10:00:00+00:00",
        "symbol": "X",
        "price": price,
        "decision": {"action": action},
    }


def test_return_uses_logged_price(monkeypatch):
    monkeypatch.setattr(metrics, "latest_price", lambda s: 110.0)
    rows = metrics.ignored_performance([_rec("ignore", 100.0), _rec("buy", 100.0)])
    assert len(rows) == 1 and round(rows[0]["change_pct"]) == 10


def test_old_record_falls_back_to_day_close(monkeypatch):
    monkeypatch.setattr(metrics, "pct_change_since", lambda s, d: 5.0)
    assert metrics.ignored_performance([_rec("ignore")])[0]["change_pct"] == 5.0
