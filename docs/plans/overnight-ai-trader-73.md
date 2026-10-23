# Trading safety, alerts and tests

Started 2026-10-22 on `overnight/ai-trader-73`.

## Goal
The Motley Fool trading pipeline tells you when it fails or trips a loss limit, stops runaway losses, scrapes politely, and has tests and a written gate before real money.

## Context (read first)
- This is an unattended overnight run on Bryan's MacBook. Nobody will answer questions: decide, write the assumption in the PR description, keep going.
- Opening the pull request is explicitly asked for in this run, even if the repo's own CLAUDE.md says not to open PRs unless asked.
- HHS Enterprise ChatGPT (gpt-tools, Chrome CDP on port 9222, `/think`, `gpt_search`) is not reachable from this Mac. Don't try it; do the review and planning yourself.
- Never commit secrets or print them in logs. Credentials stay where they are and are read at runtime only.
- Something that truly needs Bryan (lab hardware, a purchase, a new sign-in): box the step `[-]` with the reason and move on.
- The Alpaca keys in `.env` are for paper trading only (see README). Paper API calls are fine for checks. Never switch to a live trading endpoint, never place real-money orders, never print the keys.

## Steps
### Failure alerts
- [ ] S1 Add one shared way to send a phone push alert (#2)
  Check: Run the alert on its own with a test message and see it arrive on your phone.
- [ ] S2 Send an alert when a scheduled run can't reach the local model (#2)
  Check: Stop LM Studio, trigger a run, and confirm an alert arrives and the run still logs the failure.
- [ ] S3 Skip the alert when the same failure was already reported recently (#2)
  Check: Trigger two failed runs back to back and confirm only one alert arrives.

### Polite scraping
- [ ] S4 Send an alert when the saved Motley Fool login has expired (#3, #8)
  Check: Point the scraper at an invalid saved login and confirm an alert arrives naming the expiry.
- [ ] S5 Enforce a minimum wait between real site visits, however often the script runs (#3, #8)
  Check: Run the scraper twice in a row and confirm the second run skips the site and says why.
- [ ] S6 Add growing waits after repeated scrape failures, reset on success (#3, #8)
  Check: Run `pytest -k backoff`: wait times grow per failure, hit a cap, and reset after success.

### Loss limits
- [ ] S7 Add a per-position stop-loss that sells a holding once it falls past a set percent (#1)
  Check: Run `pytest -k stop_loss`: a position down past the limit is sold, one inside it is kept.
- [ ] S8 Add a daily portfolio loss limit that halts new buys when hit (#1)
  Check: Run `pytest -k daily_loss`: buys are blocked after the limit trips and allowed before it.
- [ ] S9 Send an alert whenever the stop-loss or daily loss limit trips (#1)
  Check: Run a paper cycle with a lowered limit and confirm an alert arrives for the trip.
- [ ] S10 Keep the limits paper-account only and make them easy to change (#1)
  Check: Change a limit value, rerun the loss-limit tests, and see the new value take effect.

### Pipeline tests
- [ ] S11 Test the saving of new picks: duplicates ignored and first-run baseline (#4)
  Check: Run `pytest -k state`: duplicate picks are ingested once and baseline seeding passes.
- [ ] S12 Test position sizing, swapping at the 10-position cap, and low buying power (#4)
  Check: Run `pytest -k portfolio`: sizing, swap, already-held and low-cash cases pass.
- [ ] S13 Test reading the AI's answer, including the broken-answer fallback (#4)
  Check: Run `pytest -k decide`: good, malformed and empty answers each give the expected decision.
- [ ] S14 Test the scraper's loading-placeholder handling without opening the real site (#4)
  Check: Run `pytest -k scrape`: placeholder pages are retried and real pages are read.

### Performance tracking
- [ ] S15 Record what each ignored pick did afterward, using logged prices (#6)
  Check: Run the tracker on the saved decisions and see a return figure for each ignore.
- [ ] S16 Compare each buy's return to the S&P 500 (#6)
  Check: Run the tracker and see each buy listed next to the S&P 500 over the same dates.
- [ ] S17 Add a one-page summary of AI wins versus benchmark (#6)
  Check: Run the summary and see totals for ignores, buys, and difference from the S&P 500.

### Live trading gate
- [x] S18 Write the paper-to-live checklist with a link to each finished item (#7)
  Check: Open the checklist and confirm every item points to a finished issue or a clear measure.
- [x] S19 Add a required human sign-off line before switching off paper mode (#7)
  Check: Read the checklist and confirm the sign-off line names who approves and what they review.

## Done when
- Closing the model server or letting the login expire sends a phone alert, not just a log line.
- Repeated script runs don't hit the site more often than the minimum wait, and failures back off.
- A losing position is sold and a bad day halts buys, with an alert each time.
- Tests for the saving, sizing, answer-reading and scraper rules pass.
- A summary shows AI decisions against the S&P 500.
- The graduation checklist exists with a human sign-off line.
- The PR description lists every assumption, has 'Closes #N' for each finished issue, and says why any skipped issue was skipped.

## Out of scope
- #5 Sector/correlation limits: needs a sector data source chosen first. Skip and say so in the PR.
- Tracking how long logins last to re-login ahead of time (bonus in #3).
- Motley Fool's Stock Advisor scorecard comparison in #6; only the S&P 500 comparison is built.
- Exiting every position on a daily loss trip; only halting new buys is built.
- Any switch to real-money trading.

## Open questions
- Assumption for the PR: alerts go out as a phone push through a free push service, since it's the easiest to set up. Change if you prefer email.
- Assumption: stop-loss starts at 10% below buy price and daily loss limit at 3% of the account. These are guesses.
- Assumption: #3 and #8 are handled together as asked, though they are different problems (expiry alert versus polite scraping). Both get 'Closes' lines.
- Assumption: if the push service needs an account or key you haven't set up, alert steps are built but marked untested in the PR.

## Log
- S18: Rewrote docs/paper-to-live-checklist.md so each item links its issue plus proof (file, function, test names) or a measure. Added measures to the 3 open items (sector limit 30%, 60 paper days and 10 buys beating the S&P 500, no unexplained alerts in 30 days). Left the existing sign-off line for S19. Assumption: the checklist already existed from an earlier PR, so I edited it; the thresholds are my guesses. Check run: all linked files, functions and tests exist, and `pytest scripts/motley_fool` passes (41). Note: the issues are still open on GitHub (they close when the PR merges), and gh could not reach GitHub from here (certificate error).
- S19: Replaced the vague "Owner" sign-off in docs/paper-to-live-checklist.md with a required section: approver is Bryan (repo owner), a list of what they review (ticked boxes, dashboard history, alert log, limits and amount), and a rule that `paper=True` stays until it is signed. Assumption: "owner" means Bryan since they own the repo; the checklist is documentation only, no code enforces it. Check: read the section and it names the approver and the review items.
