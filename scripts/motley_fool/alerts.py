"""Shared notification feed + adjustable risk settings for the Motley Fool pipeline.

Alerts are appended to alerts.jsonl and shown newest-first in the dashboard's
notification center, and pushed to your phone via ntfy.sh when NTFY_TOPIC is set
in .env. Settings live in settings.json; missing keys use DEFAULTS.
"""

import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
NTFY_URL = "https://ntfy.sh/"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "motley_fool"
ALERTS_PATH = DATA_DIR / "alerts.jsonl"
SETTINGS_PATH = DATA_DIR / "settings.json"

ALERTS_READ_PATH = DATA_DIR / "alerts_read.json"
RUN_STATUS_PATH = DATA_DIR / "run_status.json"

LIMITS = ("stop_loss_pct", "daily_loss_pct")  # percent, positive numbers
DEFAULTS = {
    "stop_loss_pct": 10.0,
    "daily_loss_pct": 5.0,
    "trading_paused": False,
    "stop_loss_exempt": [],
}


def get_settings() -> dict:
    saved = {}
    if SETTINGS_PATH.exists():
        saved = json.loads(SETTINGS_PATH.read_text())
    settings = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    for key in LIMITS:
        settings[key] = float(settings[key])
    settings["trading_paused"] = bool(settings["trading_paused"])
    settings["stop_loss_exempt"] = sorted({str(s) for s in settings["stop_loss_exempt"]})
    return settings


def save_settings(**changes) -> dict:
    """Validate and persist settings; limits must be in (0, 100]. Returns the effective settings."""
    settings = get_settings()
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise KeyError(f"Unknown setting {key!r}")
        if key in LIMITS:
            value = float(value)
            if not 0 < value <= 100:
                raise ValueError(f"{key} must be > 0 and <= 100, got {value}")
        settings[key] = value
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))
    return get_settings()


def set_stop_loss_exempt(symbol: str, exempt: bool) -> None:
    current = set(get_settings()["stop_loss_exempt"])
    save_settings(stop_loss_exempt=sorted(current | {symbol} if exempt else current - {symbol}))


def write_run_status(status: dict) -> None:
    """Record the outcome of a pipeline run for the dashboard's status strip."""
    RUN_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_STATUS_PATH.write_text(json.dumps(status, indent=2))


def read_run_status() -> dict | None:
    return json.loads(RUN_STATUS_PATH.read_text()) if RUN_STATUS_PATH.exists() else None


def unread_alerts() -> list[dict]:
    """Alerts newer than the last "mark as read", newest first."""
    read_at = json.loads(ALERTS_READ_PATH.read_text())["at"] if ALERTS_READ_PATH.exists() else ""
    return [a for a in load_alerts() if a["timestamp"] > read_at]


def mark_alerts_read() -> None:
    ALERTS_READ_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_READ_PATH.write_text(json.dumps({"at": datetime.now(UTC).isoformat()}))


def load_alerts() -> list[dict]:
    """All alerts, newest first."""
    if not ALERTS_PATH.exists():
        return []
    with open(ALERTS_PATH) as f:
        return [json.loads(line) for line in reversed(f.read().splitlines()) if line.strip()]


def notify(kind: str, message: str, dedupe_key: str | None = None) -> bool:
    """Append an alert. With dedupe_key, an alert with the same key is only recorded once.
    Returns True if recorded."""
    if dedupe_key and any(a.get("dedupe_key") == dedupe_key for a in load_alerts()):
        return False
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "kind": kind,
        "message": message,
        "dedupe_key": dedupe_key,
    }
    with open(ALERTS_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"ALERT [{kind}] {message}", file=sys.stderr)
    push(f"AI trader: {kind}", message)
    return True


def push(title: str, message: str) -> bool:
    """Send a phone push to the ntfy.sh topic in NTFY_TOPIC (.env). Never raises; True if sent."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False  # tests must never reach a real phone
    load_dotenv(ENV_PATH)
    topic = os.getenv("NTFY_TOPIC", "").strip()
    if not topic:
        print("PUSH skipped: NTFY_TOPIC is not set in .env", file=sys.stderr)
        return False
    req = urllib.request.Request(NTFY_URL + topic, data=message.encode(), headers={"Title": title})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except (OSError, ValueError) as e:  # a failed push must not stop a trading run
        print(f"PUSH failed: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    # uv run python scripts/motley_fool/alerts.py ["message"]  -> adds a test alert and pushes it
    notify("test", sys.argv[1] if len(sys.argv) > 1 else "Test alert from alerts.py")
