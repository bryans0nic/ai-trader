import momentum
import pandas as pd
from conftest import FakeClient, position


def _closes(slopes):
    """Flat-start price series; each symbol drifts up by its own daily slope."""
    return pd.DataFrame({s: [100 + k * i for i in range(130)] for s, k in slopes.items()})


def test_rank_orders_by_return():
    assert momentum.rank(_closes({"SLOW": 0.1, "FAST": 1.0, "MID": 0.5})) == ["FAST", "MID", "SLOW"]


def test_buys_top_vetted_names_once_a_day_and_sells_laggards():
    slopes = {f"S{i:02d}": 1.0 - i * 0.01 for i in range(20)}  # S00 best ... S19 worst
    slopes["OLD"] = -0.5  # held, now ranked last
    c = FakeClient(equity=100_000, positions=[position("OLD", value=1000)])
    c.history[0].client_order_id = "momentum:OLD:buy:test"
    asked = []

    def vet(pick, ctx, prompt):
        asked.append(pick["symbol"])
        return {"action": "buy" if pick["symbol"] != "S01" else "ignore", "reasoning": "x"}

    notes = momentum.run(c, closes=_closes(slopes), vet=vet)
    assert "sold OLD" in notes and c.closed == ["OLD"]
    assert asked == ["S00", "S01", "S02", "S03", "S04"]  # top 5 considered, all 5 slots empty
    assert [o.symbol for o in c.orders if "BUY" in str(o.side).upper()] == ["S00", "S02", "S03", "S04"]
    assert momentum.run(c, closes=_closes(slopes), vet=vet) == []  # second run the same day does nothing
