import ai_reconcile
import backoff
import pytest
from scrape_new_recs import SessionExpiredError


def test_waits_double_then_cap():
    waits = [backoff.retry_wait(n, base=60, cap=500) for n in range(1, 7)]
    assert waits == [60, 120, 240, 480, 500, 500]


def test_min_interval(tmp_path):
    p = tmp_path / "hit.json"
    assert backoff.may_hit_site(now=1000, path=p, min_interval=900)
    backoff.record_hit(now=1000, path=p)
    assert not backoff.may_hit_site(now=1500, path=p, min_interval=900)
    assert backoff.may_hit_site(now=1900, path=p, min_interval=900)


def test_two_quick_runs_hit_site_once(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ai_reconcile, "scrape_stock_advisor_rows", lambda: calls.append(1) or [{"symbol": "X"}]
    )
    assert ai_reconcile.scrape_politely() == [{"symbol": "X"}]
    assert ai_reconcile.scrape_politely() is None
    assert len(calls) == 1


def test_failures_retry_with_growing_waits(monkeypatch):
    attempts, sleeps = [], []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("boom")
        return ["ok"]

    monkeypatch.setattr(ai_reconcile, "scrape_stock_advisor_rows", flaky)
    assert ai_reconcile.scrape_politely(sleep=sleeps.append) == ["ok"]
    assert sleeps == [60, 120]


def test_expired_session_alerts_once_and_is_not_retried(monkeypatch, tmp_path):
    import alerts

    def expired():
        raise SessionExpiredError("redirected to login")

    monkeypatch.setattr(ai_reconcile, "scrape_stock_advisor_rows", expired)
    for _ in range(2):
        backoff.LAST_HIT_PATH.unlink(missing_ok=True)
        with pytest.raises(SessionExpiredError):
            ai_reconcile.scrape_politely(sleep=lambda s: pytest.fail("must not retry"))
    found = [a for a in alerts.load_alerts() if a["kind"] == "session_expired"]
    assert len(found) == 1
