# Factory lessons

## Trading safety, alerts and tests (2026-10-23)

- Test commands in the plan (like `pytest -k daily_loss`) can match nothing because the existing tests use other names (they were called `kill_switch`). Run the check command first. If it selects zero tests, add or rename tests so the plan's check really runs.
- The repo venv has no pytest, and `python-dotenv` is not a declared dependency. A bare `pytest` fails. Use `uv run --no-project --with pytest --with pytest-cov --with python-dotenv --with alpaca-py --with playwright --with-editable ../..` and add `--no-cov` when needed.
- Several steps (S7, S8, S9, S10, S11, S13) were already built in PR #13 or earlier. Read the code and existing tests before writing anything. Then add only the missing test or fix, and say in the log that no feature code was needed.
- The plan's guesses did not match the repo: it said LM Studio, but the pipeline uses the Claude CLI (`claude -p`). It said a 3% daily loss limit, but the existing default is 5%. Trust the code, keep the existing value, and write the difference in the log and the PR.
- S3 first shipped with a bug: a zero-length dedupe window. It needed a follow-up fix commit (84c38fa). Test the edge value (0) of any new window or limit setting, not only the normal case.
- A real Chrome, the live Motley Fool site, GitHub (gh certificate error) and the Alpaca market-hours cycle are not reachable from the overnight sandbox. Check with stand-in browsers, fake clients, sample logs and throwaway ntfy topics, and write down plainly what was not checked for real.
- The real decisions.jsonl is empty, so tracker and summary checks ran on a sample file with made-up prices (the NVDA +112% is fake). Label sample-based checks as such so nobody reads those numbers as real results.
- A step that needs Bryan (the S1 phone check needs the ntfy app and `NTFY_TOPIC` in `.env`) is boxed `[-]` and left for him. Don't tick it, even though the code and tests are done.

Decisions:
- Phone alerts go through ntfy.sh with a secret topic name read from NTFY_TOPIC in .env. If the topic is unset, the push is skipped with a note on stderr, and a failed push never stops a run. Push never fires under pytest.
- Repeat 'model unreachable' alerts are suppressed for 6 hours using the dedupe key `model_unreachable`. One outage sends one alert, not one per pick.
- Stop-loss stays at the existing 10% and the daily loss limit at the existing 5%, not the 3% the plan guessed. Both are editable in settings.json or the dashboard Settings form. A daily loss trip only halts new buys and does not sell positions.
- The Alpaca client is hardcoded to paper=True with no live switch. A test guards this, and the paper-to-live checklist requires a signed approval before that changes.
- Scraping waits at least 15 minutes between site visits, including when scrape_new_recs.py is run by hand. After repeated failed runs the gap doubles (15m, 15m, 30m, 1h ...) up to 6 hours, and a success resets it. The first failure keeps the normal 15m gap.
- An expired or corrupt Motley Fool login raises SessionExpiredError and sends one session_expired alert. The bad-login redirect to /premium/api/auth/signin is now recognised.
- In the AI-vs-S&P 500 summary, an ignored pick counts as right if the stock fell or stayed flat. Picks with no price yet are left out of the totals. The S&P 500 start is that day's close.
- The paper-to-live checklist names Bryan as the approver. It lists what they review (ticked boxes, dashboard history, alert log, limits and amount). paper=True stays until it is signed. This is documentation only, and no code enforces it.
- Guessed live-gate thresholds in the checklist: sector limit 30%, at least 60 paper days and 10 buys beating the S&P 500, and no unexplained alerts in 30 days.
- Issues #3 and #8 are handled together and both get 'Closes' lines. #5 (sector and correlation limits) is skipped because it needs a sector data source chosen first. The Stock Advisor scorecard comparison is not built.
