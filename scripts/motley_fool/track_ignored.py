"""
Print what each ignored pick did after the decision.

Usage: uv run python scripts/motley_fool/track_ignored.py [decisions.jsonl]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_decide  # noqa: E402
from metrics import ignored_performance  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ai_decide.DECISIONS_LOG
    if not path.exists():
        sys.exit(f"No decisions log at {path}")
    decisions = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows = ignored_performance(decisions)
    if not rows:
        print("No ignored picks yet.")
    for r in rows:
        got = "n/a" if r["change_pct"] is None else f"{r['change_pct']:+.1f}%"
        was = f"${r['price']:.2f}" if r["price"] else "no logged price"
        print(f"{r['symbol']:<8} ignored {r['day']} at {was}: {got} since")


if __name__ == "__main__":
    main()
