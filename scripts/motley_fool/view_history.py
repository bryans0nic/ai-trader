"""
Browse the AI decision / trade-history log.

Usage:
    uv run python scripts/motley_fool/view_history.py            # last 20 decisions
    uv run python scripts/motley_fool/view_history.py CSCO        # just CSCO
    uv run python scripts/motley_fool/view_history.py --full      # include full model reasoning
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_decide import load_decision_history  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol", nargs="?", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--full", action="store_true", help="Show full model reasoning, not just the summary")
    args = parser.parse_args()

    records = load_decision_history(symbol=args.symbol, limit=args.limit)
    if not records:
        print("No decisions logged yet.")
        return

    for r in records:
        d = r["decision"]
        print(f"{r['timestamp']}  {r['symbol']:<8} {d['action']:<6} confidence={d.get('confidence')}")
        print(f"  signal: {r['signal'].get('action')} rec'd {r['signal'].get('rec_date')} "
              f"({r['signal'].get('type', '?')}, mkt cap {r['signal'].get('market_cap', '?')})")
        print(f"  reasoning: {d['reasoning']}")
        if args.full:
            print(f"  full model chain-of-thought:\n{r['model_reasoning']}")
        print()


if __name__ == "__main__":
    main()
