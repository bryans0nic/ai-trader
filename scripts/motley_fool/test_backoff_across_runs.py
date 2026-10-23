import ai_reconcile
import backoff
import pytest

MIN = backoff.MIN_INTERVAL_S


def fail():
    raise RuntimeError("boom")


def failed_run(monkeypatch):
    monkeypatch.setattr(ai_reconcile, "scrape_stock_advisor_rows", fail)
    with pytest.raises(RuntimeError):
        ai_reconcile.scrape_politely(sleep=lambda s: None)


def test_backoff_waits_grow_per_failed_run_then_cap_then_reset(monkeypatch):
    waits = []
    for _ in range(8):
        failed_run(monkeypatch)
        waits.append(backoff.current_interval())
        backoff.record_hit(now=0)  # pretend time passed; only the interval is under test
    assert waits[:4] == [MIN, 2 * MIN, 4 * MIN, 8 * MIN]
    assert waits[-1] == backoff.FAIL_CAP_S == waits[-2]

    monkeypatch.setattr(ai_reconcile, "scrape_stock_advisor_rows", lambda: ["ok"])
    assert ai_reconcile.scrape_politely() == ["ok"]
    assert backoff.current_interval() == MIN


def test_backoff_blocks_visit_until_grown_wait_has_passed(monkeypatch):
    failed_run(monkeypatch)
    backoff.record_hit(now=0)
    failed_run(monkeypatch)  # second failed run in a row
    failed_run_at = backoff._load(backoff.LAST_HIT_PATH)["at"]
    assert not backoff.may_hit_site(now=failed_run_at + MIN + 1)  # normal gap is not enough now
    assert backoff.may_hit_site(now=failed_run_at + 2 * MIN)


def test_backoff_corrupt_record_does_not_block():
    backoff.LAST_HIT_PATH.write_text("{nope")
    assert backoff.may_hit_site()
