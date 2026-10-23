"""Scraper tests with a fake browser: the real Motley Fool site is never opened."""

import pytest
import scrape_new_recs as scrape

SA = scrape.STOCK_ADVISOR_SLUG


class FakePage:
    def __init__(self, rows, url="https://www.fool.com/premium/new-recs", skeleton_clears=True):
        self.rows, self.url, self.skeleton_clears = rows, url, skeleton_clears
        self.waited_for_skeletons = False

    def goto(self, *_, **__):
        pass

    def wait_for_selector(self, *_, **__):
        pass

    def wait_for_function(self, js, **__):
        # Playwright polls this until the skeletons are gone, then raises on timeout.
        assert "react-loading-skeleton" in js
        self.waited_for_skeletons = True
        if not self.skeleton_clears:
            raise TimeoutError("skeleton rows never went away")

    def evaluate(self, _js):
        return self.rows


class FakePlaywright:
    def __init__(self, page):
        self.page = page
        self.chromium = self
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def launch(self, **_):
        return self

    def new_context(self, **_):
        return self

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


@pytest.fixture
def scrape_with(tmp_path, monkeypatch):
    session = tmp_path / "session.json"
    session.write_text("{}")
    monkeypatch.setattr(scrape, "SESSION_PATH", session)

    def _go(page):
        fake = FakePlaywright(page)
        monkeypatch.setattr(scrape, "sync_playwright", lambda: fake)
        return fake

    return _go


def test_scrape_reads_real_rows_after_waiting_out_placeholders(scrape_with):
    page = FakePage(
        [
            {"symbol": "AAA", "service_href": SA},
            {"symbol": "BBB", "service_href": "/premium/my-services/rule-breakers"},
        ]
    )
    scrape_with(page)
    rows = scrape.scrape_stock_advisor_rows()
    assert page.waited_for_skeletons
    assert [r["symbol"] for r in rows] == ["AAA"]  # only Stock Advisor rows kept


def test_scrape_placeholder_that_never_clears_is_a_loud_failure(scrape_with):
    page = FakePage([{"symbol": "", "service_href": None}], skeleton_clears=False)
    fake = scrape_with(page)
    with pytest.raises(scrape.SessionExpiredError, match="did not finish loading"):
        scrape.scrape_stock_advisor_rows()
    assert fake.closed


def test_scrape_zero_rows_is_an_error_not_no_new_picks(scrape_with):
    scrape_with(FakePage([]))
    with pytest.raises(RuntimeError, match="zero rows"):
        scrape.scrape_stock_advisor_rows()


def test_scrape_redirect_to_login_means_expired_session(scrape_with):
    scrape_with(FakePage([], url="https://www.fool.com/login"))
    with pytest.raises(scrape.SessionExpiredError, match="Redirected"):
        scrape.scrape_stock_advisor_rows()


def test_scrape_missing_session_file_raises(scrape_with, monkeypatch, tmp_path):
    monkeypatch.setattr(scrape, "SESSION_PATH", tmp_path / "nope.json")
    with pytest.raises(scrape.SessionExpiredError, match="No saved session"):
        scrape.scrape_stock_advisor_rows()
