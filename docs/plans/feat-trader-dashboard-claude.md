# Trader dashboard and Claude switch

Started 2026-10-10 on `feat/trader-dashboard-claude`.

## Goal
See trading history, the AI's reasoning and live metrics in a web page, with decisions made by your Claude subscription (the Claude Code command line you're logged into, done the same way as in the ClaudeOS and SocialOS repos) instead of the local model. The page runs on this MacBook and is reachable from your other devices over Tailscale, and alerts show up in a notification center on it. Along the way, add the basic safety, alerting and politeness fixes the pipeline lacks.

## Steps
### Claude replaces local model
- [x] S1 Switch the buy/ignore decision call from the local model to Claude, using the logged-in Claude Code command line and copying the approach from the ClaudeOS and SocialOS repos
  Check: Run one decision on a saved recommendation and confirm a reply from Claude is logged with reasoning.
- [x] S2 Keep the fallback for malformed Claude replies so a bad answer never trades (#4)
  Check: Run `pytest scripts/motley_fool/test_ai_decide.py`; a garbled reply must produce an 'ignore' result.

### History and reasoning page
- [x] S3 Add a web page listing every past decision, newest first
  Check: Open the page in a browser and see the entries from the decision log.
- [x] S4 Show the full AI reasoning when a decision is opened
  Check: Click a decision and confirm its reasoning text matches the log entry.
- [x] S18 Serve the web page from this MacBook so it can be opened locally and from your other devices over Tailscale, but not the public internet
  Check: Open the page on this MacBook, then from another device on your Tailscale network; both load it.

### Live metrics and performance
- [x] S5 Show current positions, buying power and profit/loss on the page
  Check: Compare the numbers on the page against the paper account; they must match.
- [x] S6 Track how ignored picks later performed and show it on the page (#6)
  Check: Open the page and see each ignored pick with its price change since the decision.
- [x] S7 Compare bought picks against the S&P 500 and Stock Advisor's return (#6)
  Check: Page shows one return figure for each of: our buys, S&P 500, Stock Advisor scorecard.

### Loss protection and alerts
- [x] S16 Add a notification center to the web page that lists alerts, newest first
  Check: Add a test alert and see it appear in the notification center on the page.
- [x] S17 Add adjustable settings for the per-position stop-loss and daily-loss limits, with defaults of 10% per position and 5% per day
  Check: Change a limit in the settings, rerun the S8/S9 checks, and confirm the new limit is used; with nothing set, the defaults apply.
- [x] S8 Add a per-position stop-loss that sells when a holding falls too far (#1)
  Check: Run the portfolio check against a fake position down past the limit; it must sell.
- [x] S9 Add a daily-loss kill switch that halts new buys when tripped (#1)
  Check: Simulate a day's loss over the limit; the next run must place no buys.
- [x] S10 Send one shared notification whenever a stop-loss or kill switch trips (#1)
  Check: Trigger a fake stop-loss and confirm a notification appears in the web page's notification center, not only in the log file.

### Scraper reliability
- [x] S11 Alert on expired Motley Fool session and add polite backoff between site hits (#3, #8)
  Check: Force an expired session and see the alert; re-run twice quickly and see only one site hit.
- [x] S12 Retry failed scrapes with growing waits instead of the same schedule (#8)
  Check: Run `pytest scripts/motley_fool/test_backoff.py`; waits must double after each failure up to a cap.

### Tests and graduation checklist
- [x] S13 Test position sizing, supplanting at max holdings, and insufficient buying power (#4)
  Check: Run `pytest scripts/motley_fool/test_portfolio.py`; all cases pass.
- [x] S14 Test duplicate handling and baseline seeding when new recommendations arrive (#4)
  Check: Run `pytest scripts/motley_fool/test_state.py`; ingesting the same pick twice adds one.
- [x] S15 Write the paper-to-live checklist document with the sign-off item (#7)
  Check: Open the document and confirm each listed requirement is a checkbox that links to its issue.

## Done when
- The web page shows past decisions, their reasoning, current positions and performance against the benchmarks.
- The page opens on this MacBook and from your devices over Tailscale.
- Decisions are made by Claude through your logged-in Claude Code subscription, the same way as in ClaudeOS and SocialOS, and no local model is needed.
- A stop-loss or kill switch trip, or an expired Motley Fool session, appears in the web page's notification center.
- The stop-loss and daily-loss limits can be adjusted, with sensible defaults.
- The scraper never hits the site more often than the minimum interval and backs off after failures.
- The new tests for sizing, state handling and backoff pass.
- The graduation checklist exists.

## Out of scope
- Sector or correlation concentration limits (#5)
- Tracking how long sessions last for proactive re-login (bonus in #3)
- Tests for the scraper's loading-skeleton handling and other parts of the pipeline not named in the steps
- Actually moving to live trading
- Email, phone or other notifications outside the web page (for now)
- Making the web page reachable from the public internet

## Open questions

## Log
- S1: `ai_decide.py` now calls `claude -p` (subscription login, JSON schema, no tools) instead of LM Studio/Qwen; logs the model Claude actually used; README updated.
- S2: `decide()` now ignores on any invalid action or failed/timed-out Claude call (PARSE_ERROR / CALL_ERROR); added `scripts/motley_fool/test_ai_decide.py` (9 cases pass; run with `-o addopts=""` as pytest-cov isn't installed here).
- S3: `scripts/motley_fool/dashboard.py` (stdlib http.server, no new deps) lists every logged decision newest first; checked over HTTP against a fixture log (test_dashboard.py).
- S4: `/decision/<n>` shows signal, portfolio snapshot and full reasoning (HTML-escaped); test confirms text matches the log entry.
- S18: NOT TICKED. Server binds only to 127.0.0.1 and this Mac's Tailscale IP (100.117.75.111) and rejects unknown Host/Origin headers. localhost works; connecting to the Tailscale IP from this same machine accepted TCP but never answered for the uv-managed Python (a plain `http.server` on system python3 did answer), so it is unverified. Needs a look in the morning: open `http://100.117.75.111:8765/` from the phone and, if it hangs, allow the uv Python in macOS Firewall / Local Network settings. I did not bypass the sandbox or touch firewall settings.
- S5: dashboard Account section (equity, cash, buying power, today's P/L, per-position P/L) via Alpaca client; matches a fake account in tests. No Alpaca keys in this worktree, so not compared against the real paper account yet.
- S6: `metrics.ignored_performance` shows each ignored pick's % price change since decision day (yfinance); tested with stubbed prices.
- S7: dashboard shows avg return of our buys, the S&P 500 over the same dates, and "Stock Advisor recs seen". Choice: no official scorecard source is known, so the Stock Advisor figure is the equal-weight return of every Buy rec in state.json since its rec date.
- S16: `alerts.py` feed (alerts.jsonl) + notification center on the page + "Add test alert" button; test confirms the alert appears.
- S17: `settings.json` with defaults 10% stop-loss / 5% daily loss, editable on the dashboard (validated 0-100); tests cover defaults and changed limits.
- S8: `portfolio.check_stop_losses` sells holdings past the limit; runs at the start of every `ai_reconcile.py` run, even if scraping fails.
- S9: `daily_loss_tripped` (equity vs last close) blocks all buys/supplants in `reconcile_new_pick`; marks the pick `halted_kill_switch`.
- S10: both trips call `alerts.notify`, so they land in the notification center (kill switch deduped once per day).
- S11: `SessionExpiredError` raised by the scraper alerts once per day; `backoff.may_hit_site` enforces a 15 min minimum between site hits across runs (test: two quick runs, one hit).
- S12: `scrape_politely` retries failures 4 times with waits 60s, 120s, 240s... capped at 15 min; expired sessions are not retried. `test_backoff.py` passes.
- S13: `test_portfolio.py` covers sizing, supplanting, ties, buying power cap/skip, plus S8/S9/S17 cases.
- S14: `test_state.py` covers duplicate ingest and baseline seeding.
- S15: `docs/paper-to-live-checklist.md` with checkbox per requirement linking its bryans0nic/ai-trader issue, plus sign-off line; README documents the dashboard.
- Env note: `uv sync` on the lock pulls `types-urllib3`, which clobbers urllib3 and breaks imports; I removed it from my local .venv (not committed). Tests run with `uv run --no-sync pytest -o addopts="" scripts/motley_fool` (pytest-cov flags in pyproject; 30 tests pass).
- S18 follow-up: cause was the macOS firewall dropping incoming connections to uv's ad-hoc-signed Python 3.12; rebuilt `.venv` on the framework Python 3.14 (already allowed in the firewall) and the Tailscale IP now answers. Also fixed: page crashed without Alpaca keys (SystemExit), and the short MagicDNS name `cyberbook-pro` was rejected by the Host check.
- Follow-up (requested): mobile-first dashboard UI (cards, sticky section nav, light/dark, 44px+ touch targets) and an Alpaca paper-key form in Settings that writes `.env` (mode 600), validates input and never shows the keys again; test added (31 pass).
- Follow-up (requested): permanent deployment matching ClaudeOS/SocialOS. Dashboard now binds localhost only; `scripts/motley_fool/install-mac.sh` installs LaunchAgents `com.aitrader.dashboard` + `com.aitrader.autodeploy` (`deploy-mac.sh`, every 2 min from origin/main) and a Tailscale Serve entry on :10443. `uv.lock`: urllib3 1.24.3 -> 2.8.0 (the old pin could not import on Python 3.12+).
