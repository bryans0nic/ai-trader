"""
Print what each ignored pick did after the decision, and each buy next to the S&P 500.

Usage: uv run python scripts/motley_fool/track_ignored.py [decisions.jsonl]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_decide  # noqa: E402
from metrics import buys_vs_sp500, ignored_performance  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ai_decide.DECISIONS_LOG
    if not path.exists():
        sys.exit(f"No decisions log at {path}")
    decisions = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    pct = lambda v: "n/a" if v is None else f"{v:+.1f}%"  # noqa: E731
    rows = ignored_performance(decisions)
    if not rows:
        print("No ignored picks yet.")
    for r in rows:
        got = pct(r["change_pct"])
        was = f"${r['price']:.2f}" if r["price"] else "no logged price"
        print(f"{r['symbol']:<8} ignored {r['day']} at {was}: {got} since")
    print()
    buys = buys_vs_sp500(decisions)
    if not buys:
        print("No buys yet.")
    for b in buys:
        print(
            f"{b['symbol']:<8} bought {b['day']}: {pct(b['change_pct'])} vs S&P 500 "
            f"{pct(b['sp500_pct'])} (difference {pct(b['diff_pct'])})"
        )


if __name__ == "__main__":
    main()
