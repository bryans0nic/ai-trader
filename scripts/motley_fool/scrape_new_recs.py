"""
Deterministic (no AI) scrape of the Motley Fool "New Recs" table, filtered to
Stock Advisor. Extraction is plain DOM parsing by column position and by the
stable /premium/my-services/{slug} link -- no model involved, since this is a
well-structured table, not a task requiring judgment.

Requires a saved session from login_and_save_session.py. Raises a clear error
if the session has expired (redirected to a login page / table not found)
rather than silently returning nothing.
"""

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

SESSION_PATH = Path(__file__).resolve().parents[2] / "data" / "motley_fool" / "session.json"
NEW_RECS_URL = "https://www.fool.com/premium/new-recs"
STOCK_ADVISOR_SLUG = "/premium/my-services/stock-advisor"


class SessionExpiredError(RuntimeError):
    """Saved Motley Fool login is missing/expired: needs a human to re-run login_and_save_session.py."""


_EXTRACT_ROWS_JS = """
() => {
  const table = document.querySelector('table');
  if (!table) return null;
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  return rows.map(row => {
    const tds = Array.from(row.querySelectorAll('td'));
    const cell = (i) => (tds[i] ? tds[i].innerText.trim() : '');
    const serviceLink = tds[3] ? tds[3].querySelector('a[href*="/premium/my-services/"]') : null;
    const estReturn = cell(7).split('\\n').filter(Boolean);
    return {
      symbol: cell(0).replace('expand current row', '').trim(),
      company: cell(1),
      action: cell(2),
      service_label: cell(3),
      service_href: serviceLink ? serviceLink.getAttribute('href') : null,
      rec_date: cell(5),
      type: cell(6),
      est_return_low: estReturn[0] || null,
      est_return_high: estReturn[estReturn.length - 1] || null,
      est_max_drawdown: cell(8),
      market_cap: cell(9),
      times_recd: cell(10),
    };
  });
}
"""


def scrape_stock_advisor_rows() -> list[dict]:
    if not SESSION_PATH.exists():
        raise SessionExpiredError(
            f"No saved session at {SESSION_PATH}. "
            "Run: uv run python scripts/motley_fool/login_and_save_session.py"
        )
    try:
        json.loads(SESSION_PATH.read_text())
    except (OSError, ValueError) as e:
        raise SessionExpiredError(
            f"Saved session at {SESSION_PATH} is unreadable ({e}). "
            "Re-run: uv run python scripts/motley_fool/login_and_save_session.py"
        ) from e

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(SESSION_PATH))
        page = context.new_page()
        # Not "networkidle": fool.com has continuous background polling (tickers,
        # analytics) that never goes idle within the timeout. We wait for the
        # actual table selector below instead, which is the real readiness signal.
        page.goto(NEW_RECS_URL, wait_until="load")

        # A bad login lands on /premium/api/auth/signin, so "/premium" alone isn't enough.
        if not urlparse(page.url).path.startswith("/premium/new-recs"):
            browser.close()
            raise SessionExpiredError(
                f"Redirected to {page.url} -- session likely expired. "
                "Re-run: uv run python scripts/motley_fool/login_and_save_session.py"
            )

        try:
            page.wait_for_selector("table tbody tr", timeout=15000)
            # The table renders React loading-skeleton placeholder rows first
            # (aria-busy="true", empty content) before real data hydrates in.
            # Waiting for the row selector alone catches the skeleton, not the
            # data -- wait for the skeletons to be gone too.
            page.wait_for_function(
                "document.querySelectorAll('table tbody tr .react-loading-skeleton').length === 0",
                timeout=15000,
            )
        except Exception as e:
            browser.close()
            raise SessionExpiredError(
                "New Recs table did not finish loading -- session may have expired or the "
                "page layout changed. Re-run login_and_save_session.py or check the page manually."
            ) from e

        rows = page.evaluate(_EXTRACT_ROWS_JS)
        browser.close()

    if not rows:
        raise RuntimeError("Scrape returned zero rows -- treat as a failure, not 'no new picks'.")

    return [r for r in rows if r["service_href"] == STOCK_ADVISOR_SLUG]


def main() -> None:
    """Run from the command line: same minimum wait (and failure back-off) as the pipeline."""
    import backoff

    if not backoff.may_hit_site():
        minutes = backoff.current_interval() // 60
        print(f"Skipped: the site was visited less than {minutes:.0f} min ago. Try again later.")
        return
    backoff.record_hit()
    try:
        rows = scrape_stock_advisor_rows()
    except Exception:
        backoff.record_failure()
        raise
    backoff.record_success()
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
