# Paper-to-live graduation checklist

The Motley Fool -> Claude -> Alpaca pipeline stays on the paper account until every box below is ticked.
Issue links are in [bryans0nic/ai-trader](https://github.com/bryans0nic/ai-trader/issues) ([#7](https://github.com/bryans0nic/ai-trader/issues/7) is this checklist).

A ticked box means the work is built and its proof passes. The issues close when the PR that finishes them merges;
until then the linked proof is what counts. Re-run every proof with:

```bash
uv run pytest scripts/motley_fool -o addopts=""
```

An unticked box has a measure: tick it only when the measure is met.

## Safety
- [x] Per-position stop-loss and daily-loss kill switch, adjustable on the dashboard (defaults 10% / 5%) — [#1](https://github.com/bryans0nic/ai-trader/issues/1)
  Proof: [`portfolio.py`](../scripts/motley_fool/portfolio.py) `check_stop_losses`, `daily_loss_tripped`; tests `test_stop_loss_sells_and_notifies`, `test_kill_switch_blocks_buys_and_alerts_once`, `test_limits_default_then_adjustable` in [`test_portfolio.py`](../scripts/motley_fool/test_portfolio.py)
- [ ] Sector / correlation concentration limits beyond the 10-position cap — [#5](https://github.com/bryans0nic/ai-trader/issues/5) *(not built yet: needs a sector data source)*
  Measure: a buy that would put any one sector above 30% of the portfolio is blocked, with a passing test that shows it.

## Reliability and alerting
- [x] Expired Motley Fool session raises an alert in the dashboard notification center — [#3](https://github.com/bryans0nic/ai-trader/issues/3)
  Proof: `SessionExpiredError` in [`scrape_new_recs.py`](../scripts/motley_fool/scrape_new_recs.py), alert in [`ai_reconcile.py`](../scripts/motley_fool/ai_reconcile.py); tests `test_expired_session_alerts_once_and_is_not_retried` in [`test_backoff.py`](../scripts/motley_fool/test_backoff.py), `test_alert_appears_in_notification_center` in [`test_dashboard.py`](../scripts/motley_fool/test_dashboard.py)
- [x] Scraper waits a minimum time between site hits and retries failures with growing waits — [#8](https://github.com/bryans0nic/ai-trader/issues/8)
  Proof: [`backoff.py`](../scripts/motley_fool/backoff.py); tests `test_waits_double_then_cap`, `test_min_interval`, `test_two_quick_runs_hit_site_once`, `test_failures_retry_with_growing_waits` in [`test_backoff.py`](../scripts/motley_fool/test_backoff.py)
- [x] Decisions come from Claude via the logged-in Claude Code CLI; a failed or garbled reply never trades — [#2](https://github.com/bryans0nic/ai-trader/issues/2) *(the local-model outage this issue covered no longer applies)*
  Proof: [`ai_decide.py`](../scripts/motley_fool/ai_decide.py) `decide`; tests `test_claude_failure_is_ignore`, `test_garbled_reply_is_ignore` in [`test_ai_decide.py`](../scripts/motley_fool/test_ai_decide.py)

## Evidence
- [x] Tests cover sizing, supplanting, buying power, duplicate handling and baseline seeding — [#4](https://github.com/bryans0nic/ai-trader/issues/4)
  Proof: [`test_portfolio.py`](../scripts/motley_fool/test_portfolio.py), [`test_state.py`](../scripts/motley_fool/test_state.py), [`test_ai_decide.py`](../scripts/motley_fool/test_ai_decide.py) all pass
- [x] Dashboard compares our buys against the S&P 500 and Stock Advisor recs and tracks ignored picks — [#6](https://github.com/bryans0nic/ai-trader/issues/6)
  Proof: [`metrics.py`](../scripts/motley_fool/metrics.py) `benchmarks`, `ignored_performance`; tests `test_account_and_performance_numbers`, `test_chart_position_detail_and_outcomes` in [`test_dashboard.py`](../scripts/motley_fool/test_dashboard.py)
- [ ] Paper run long enough that the dashboard comparison means something, and it beats the S&P 500 — [#6](https://github.com/bryans0nic/ai-trader/issues/6)
  Measure: at least 60 trading days on paper and at least 10 buys, and the dashboard's average return on our buys is higher than the S&P 500 over the same dates.
- [ ] No unexplained alerts — [#1](https://github.com/bryans0nic/ai-trader/issues/1), [#3](https://github.com/bryans0nic/ai-trader/issues/3)
  Measure: every stop-loss, kill-switch and session-expired alert in the last 30 days of the dashboard alert log has a known cause.

## Sign-off (required)
Nobody, human or AI, changes `paper=True` in [`portfolio.py`](../scripts/motley_fool/portfolio.py) or swaps in live Alpaca keys until this section is signed.

- [ ] **Approver: Bryan (repo owner, bryans0nic).** Bryan has personally reviewed all of the following and approves moving to live trading — [#7](https://github.com/bryans0nic/ai-trader/issues/7)
  - every box above is ticked, or any unticked box has a written reason below
  - the dashboard history: decisions, buys against the S&P 500, ignored picks
  - the alert log: stop-loss, kill-switch and session-expired alerts, each with a known cause
  - the stop-loss and daily-loss limits, and the amount of real money going in

Signed off by (Bryan, full name): ______________  Date: ____________
Reasons for any unticked box: ______________
