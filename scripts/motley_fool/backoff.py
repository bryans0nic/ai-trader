"""Politeness + retry helpers for hitting fool.com."""

import json
import time
from pathlib import Path

from alerts import DATA_DIR

LAST_HIT_PATH = DATA_DIR / "last_scrape_hit.json"
MIN_INTERVAL_S = 15 * 60  # never hit the site more often than this
RETRY_BASE_S = 60
RETRY_CAP_S = 15 * 60


def retry_wait(failures: int, base: float = RETRY_BASE_S, cap: float = RETRY_CAP_S) -> float:
    """Seconds to wait after the Nth consecutive failure (1-based): base, 2*base, 4*base ... capped."""
    return min(cap, base * 2 ** (max(failures, 1) - 1))


def may_hit_site(
    now: float | None = None, path: Path | None = None, min_interval: float | None = None
) -> bool:
    path = path or LAST_HIT_PATH
    min_interval = MIN_INTERVAL_S if min_interval is None else min_interval
    now = time.time() if now is None else now
    if not path.exists():
        return True
    return now - json.loads(path.read_text())["at"] >= min_interval


def record_hit(now: float | None = None, path: Path | None = None) -> None:
    path = path or LAST_HIT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": time.time() if now is None else now}))
