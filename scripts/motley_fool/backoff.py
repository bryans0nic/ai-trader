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


FAIL_CAP_S = 6 * 3600  # after repeated failed runs, wait grows 15m, 30m, 1h ... up to this


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}  # missing or unreadable record: allow the visit rather than block forever


def current_interval(path: Path | None = None, min_interval: float | None = None) -> float:
    """Wait required after the last visit: the minimum, doubled for each consecutive failed run."""
    min_interval = MIN_INTERVAL_S if min_interval is None else min_interval
    failures = _load(path or LAST_HIT_PATH).get("failures", 0)
    return retry_wait(failures, min_interval, FAIL_CAP_S) if failures else min_interval


def may_hit_site(
    now: float | None = None, path: Path | None = None, min_interval: float | None = None
) -> bool:
    at = _load(path or LAST_HIT_PATH).get("at")
    now = time.time() if now is None else now
    return at is None or now - at >= current_interval(path, min_interval)


def _save(path: Path, **changes) -> None:
    data = {**_load(path), **changes}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def record_hit(now: float | None = None, path: Path | None = None) -> None:
    _save(path or LAST_HIT_PATH, at=time.time() if now is None else now)


def record_failure(path: Path | None = None) -> None:
    path = path or LAST_HIT_PATH
    _save(path, failures=_load(path).get("failures", 0) + 1)


def record_success(path: Path | None = None) -> None:
    _save(path or LAST_HIT_PATH, failures=0)
