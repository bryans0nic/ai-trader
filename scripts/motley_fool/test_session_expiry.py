from contextlib import contextmanager
from types import SimpleNamespace

import ai_reconcile
import alerts
import pytest
import scrape_new_recs
from scrape_new_recs import SessionExpiredError

# Where fool.com actually sends a request carrying a bad login (checked with curl, 2026-10-22).
SIGNIN_URL = "https://www.fool.com/premium/api/auth/signin?returnPath=%2Fpremium%2Fnew-recs"
ROW = {"symbol": "ABC", "service_href": scrape_new_recs.STOCK_ADVISOR_SLUG}


def fake_playwright(landed_url):
    page = SimpleNamespace(
        url=None,
        goto=lambda url, **k: setattr(page, "url", landed_url),
        wait_for_selector=lambda *a, **k: None,
        wait_for_function=lambda *a, **k: None,
        evaluate=lambda js: [ROW],
    )
    context = SimpleNamespace(new_page=lambda: page)
    browser = SimpleNamespace(new_context=lambda **k: context, close=lambda: None)

    @contextmanager
    def sync_playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **k: browser))

    return sync_playwright


def run_with_session(monkeypatch, tmp_path, contents, landed_url=SIGNIN_URL):
    session = tmp_path / "session.json"
    session.write_text(contents)
    monkeypatch.setattr(scrape_new_recs, "SESSION_PATH", session)
    monkeypatch.setattr(scrape_new_recs, "sync_playwright", fake_playwright(landed_url))
    sleeps = []
    return ai_reconcile.scrape_politely(sleep=sleeps.append), sleeps


@pytest.mark.parametrize("contents", ['{"cookies": [], "origins": []}', "not json{"])
def test_invalid_saved_login_sends_expiry_alert(monkeypatch, tmp_path, contents):
    with pytest.raises(SessionExpiredError):
        run_with_session(monkeypatch, tmp_path, contents)
    found = [a for a in alerts.load_alerts() if a["kind"] == "session_expired"]
    assert len(found) == 1
    assert "expired" in found[0]["message"]


def test_valid_login_still_scrapes(monkeypatch, tmp_path):
    rows, sleeps = run_with_session(
        monkeypatch, tmp_path, "{}", "https://www.fool.com/premium/new-recs"
    )
    assert rows == [ROW] and sleeps == []
    assert alerts.load_alerts() == []
