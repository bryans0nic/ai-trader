"""
One-time (and re-run whenever the session expires) interactive login.

Opens a real Chromium window, you log into Motley Fool by hand, then press
Enter here to save the authenticated session to disk. The unattended scraper
reuses that saved session -- no credentials are ever stored by this script,
only the resulting browser cookies/local storage, exactly like staying
logged in in a normal browser.

Usage:
    uv run python scripts/motley_fool/login_and_save_session.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

SESSION_PATH = Path(__file__).resolve().parents[2] / "data" / "motley_fool" / "session.json"


def main() -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.fool.com/premium/new-recs")

        print("A browser window opened. Log into your Motley Fool account there.")
        print("Once you can see the New Recs table, come back here and press Enter.")
        input()

        context.storage_state(path=str(SESSION_PATH))
        browser.close()

    print(f"Session saved to {SESSION_PATH}")
    print("Re-run this script whenever the unattended scraper starts failing to authenticate.")


if __name__ == "__main__":
    main()
