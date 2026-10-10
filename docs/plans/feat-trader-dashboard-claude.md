# Trader dashboard and Claude switch

Started 2026-10-10 on `feat/trader-dashboard-claude`.

## Goal
See trading history, the AI's reasoning and live metrics in a web page, with decisions made by your Claude subscription (the Claude Code command line you're logged into, done the same way as in the ClaudeOS and SocialOS repos) instead of the local model. The page runs on this MacBook and is reachable from your other devices over Tailscale, and alerts show up in a notification center on it. Along the way, add the basic safety, alerting and politeness fixes the pipeline lacks.

## Steps
### Claude replaces local model
- [ ] S1 Switch the buy/ignore decision call from the local model to Claude, using the logged-in Claude Code command line and copying the approach from the ClaudeOS and SocialOS repos
  Check: Run one decision on a saved recommendation and confirm a reply from Claude is logged with reasoning.
- [ ] S2 Keep the fallback for malformed Claude replies so a bad answer never trades (#4)
  Check: Run `pytest scripts/motley_fool/test_ai_decide.py`; a garbled reply must produce an 'ignore' result.

### History and reasoning page
- [ ] S3 Add a web page listing every past decision, newest first
  Check: Open the page in a browser and see the entries from the decision log.
- [ ] S4 Show the full AI reasoning when a decision is opened
  Check: Click a decision and confirm its reasoning text matches the log entry.
- [ ] S18 Serve the web page from this MacBook so it can be opened locally and from your other devices over Tailscale, but not the public internet
  Check: Open the page on this MacBook, then from another device on your Tailscale network; both load it.

### Live metrics and performance
- [ ] S5 Show current positions, buying power and profit/loss on the page
  Check: Compare the numbers on the page against the paper account; they must match.
- [ ] S6 Track how ignored picks later performed and show it on the page (#6)
  Check: Open the page and see each ignored pick with its price change since the decision.
- [ ] S7 Compare bought picks against the S&P 500 and Stock Advisor's return (#6)
  Check: Page shows one return figure for each of: our buys, S&P 500, Stock Advisor scorecard.

### Loss protection and alerts
- [ ] S16 Add a notification center to the web page that lists alerts, newest first
  Check: Add a test alert and see it appear in the notification center on the page.
- [ ] S17 Add adjustable settings for the per-position stop-loss and daily-loss limits, with defaults of 10% per position and 5% per day
  Check: Change a limit in the settings, rerun the S8/S9 checks, and confirm the new limit is used; with nothing set, the defaults apply.
- [ ] S8 Add a per-position stop-loss that sells when a holding falls too far (#1)
  Check: Run the portfolio check against a fake position down past the limit; it must sell.
- [ ] S9 Add a daily-loss kill switch that halts new buys when tripped (#1)
  Check: Simulate a day's loss over the limit; the next run must place no buys.
- [ ] S10 Send one shared notification whenever a stop-loss or kill switch trips (#1)
  Check: Trigger a fake stop-loss and confirm a notification appears in the web page's notification center, not only in the log file.

### Scraper reliability
- [ ] S11 Alert on expired Motley Fool session and add polite backoff between site hits (#3, #8)
  Check: Force an expired session and see the alert; re-run twice quickly and see only one site hit.
- [ ] S12 Retry failed scrapes with growing waits instead of the same schedule (#8)
  Check: Run `pytest scripts/motley_fool/test_backoff.py`; waits must double after each failure up to a cap.

### Tests and graduation checklist
- [ ] S13 Test position sizing, supplanting at max holdings, and insufficient buying power (#4)
  Check: Run `pytest scripts/motley_fool/test_portfolio.py`; all cases pass.
- [ ] S14 Test duplicate handling and baseline seeding when new recommendations arrive (#4)
  Check: Run `pytest scripts/motley_fool/test_state.py`; ingesting the same pick twice adds one.
- [ ] S15 Write the paper-to-live checklist document with the sign-off item (#7)
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
