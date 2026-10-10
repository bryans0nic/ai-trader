# Paper-to-live graduation checklist

The Motley Fool -> Claude -> Alpaca pipeline stays on the paper account until every box below is ticked.
Issue links are in [bryans0nic/ai-trader](https://github.com/bryans0nic/ai-trader/issues).

## Safety
- [x] Per-position stop-loss and daily-loss kill switch, adjustable on the dashboard (defaults 10% / 5%) — [#1](https://github.com/bryans0nic/ai-trader/issues/1)
- [ ] Sector / correlation concentration limits beyond the 10-position cap — [#5](https://github.com/bryans0nic/ai-trader/issues/5) *(not built yet)*

## Reliability and alerting
- [x] Expired Motley Fool session raises an alert in the dashboard notification center — [#3](https://github.com/bryans0nic/ai-trader/issues/3)
- [x] Scraper backs off between site hits and retries failures with growing waits — [#8](https://github.com/bryans0nic/ai-trader/issues/8)
- [x] Decisions come from Claude via the logged-in Claude Code CLI; a failed or garbled reply never trades — [#2](https://github.com/bryans0nic/ai-trader/issues/2) *(the local-model outage this issue covered no longer applies)*

## Evidence
- [x] Tests cover sizing, supplanting, buying power, duplicate handling and baseline seeding — [#4](https://github.com/bryans0nic/ai-trader/issues/4)
- [x] Dashboard compares our buys against the S&P 500 and Stock Advisor recs and tracks ignored picks — [#6](https://github.com/bryans0nic/ai-trader/issues/6)
- [ ] Paper run long enough that the dashboard comparison is meaningful, and it beats the S&P 500 — [#6](https://github.com/bryans0nic/ai-trader/issues/6)

## Sign-off
- [ ] Owner has reviewed this list, the dashboard history and the alert log, and approves moving to live trading — [#7](https://github.com/bryans0nic/ai-trader/issues/7)

Signed off by: ______________  Date: ____________
