"""
One-page summary of the AI's decisions against the S&P 500.

Usage: uv run python scripts/motley_fool/summary.py [decisions.jsonl]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_decide  # noqa: E402
from metrics import summarize  # noqa: E402


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.1f}%"


def render(s: dict) -> str:
    return "\n".join(
        [
            "AI decisions vs the S&P 500 (returns since each decision)",
            "",
            f"Ignores: {s['ignores']}   average move since {_pct(s['ignores_avg'])}   "
            f"right (stock fell or flat): {s['ignores_won']} of {s['ignores']}",
            f"Buys:    {s['buys']}   average return {_pct(s['buys_avg'])}   "
            f"beat the S&P 500: {s['buys_won']} of {s['buys']}",
            f"S&P 500 over the same dates: {_pct(s['sp500_avg'])}",
            f"Buys minus S&P 500: {_pct(s['diff_avg'])}",
        ]
    )


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ai_decide.DECISIONS_LOG
    if not path.exists():
        sys.exit(f"No decisions log at {path}")
    lines = path.read_text().splitlines()
    print(render(summarize([json.loads(line) for line in lines if line.strip()])))


if __name__ == "__main__":
    main()
