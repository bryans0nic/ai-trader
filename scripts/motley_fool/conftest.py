import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alerts  # noqa: E402
import backoff  # noqa: E402
import state  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Point every data file at tmp_path so tests never touch real pipeline state."""
    monkeypatch.setattr(state, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(alerts, "ALERTS_PATH", tmp_path / "alerts.jsonl")
    monkeypatch.setattr(alerts, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(alerts, "ALERTS_READ_PATH", tmp_path / "alerts_read.json")
    monkeypatch.setattr(alerts, "RUN_STATUS_PATH", tmp_path / "run_status.json")
    monkeypatch.setattr(backoff, "LAST_HIT_PATH", tmp_path / "last_hit.json")


class FakeClient:
    """Minimal stand-in for alpaca TradingClient."""

    def __init__(self, equity=100_000, last_equity=100_000, buying_power=None, positions=()):
        self.account = SimpleNamespace(
            equity=str(equity),
            last_equity=str(last_equity),
            portfolio_value=str(equity),
            cash=str(equity),
            buying_power=str(equity if buying_power is None else buying_power),
        )
        self.positions = list(positions)
        self.orders, self.closed, self.open_orders = [], [], []

    def get_account(self):
        return self.account

    def get_orders(self, filter=None):
        return self.open_orders

    def get_all_positions(self):
        return self.positions

    def submit_order(self, order):
        self.orders.append(order)

    def close_position(self, symbol):
        self.closed.append(symbol)
        self.positions = [p for p in self.positions if p.symbol != symbol]


def position(symbol, value=1000.0, plpc=0.0):
    return SimpleNamespace(
        symbol=symbol,
        qty="1",
        market_value=str(value),
        unrealized_pl=str(value * plpc),
        unrealized_plpc=str(plpc),
    )
