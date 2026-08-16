"""
Assign a confidence score (0-100) to a pending Motley Fool pick and let the
portfolio reconciler decide whether to trade it.

Usage:
    uv run python scripts/motley_fool/set_confidence.py CSCO 85
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from portfolio import reconcile_new_pick  # noqa: E402
from state import set_confidence  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    parser.add_argument("confidence", type=float, help="0-100")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    set_confidence(symbol, args.confidence)
    print(f"Set {symbol} confidence to {args.confidence}")

    reconcile_new_pick(symbol)


if __name__ == "__main__":
    main()
