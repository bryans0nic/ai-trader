import sleeves
from conftest import FakeClient, position
from spy_baseline import spy_baseline


def test_equal_split_and_sleeves_are_separate():
    c = FakeClient(equity=100_000, positions=[position("AAA", value=5_000)])  # held by motley_fool
    assert sleeves.book(c, "motley_fool")["cash"] == 15_000
    assert sleeves.book(c, "momentum")["cash"] == 20_000  # untouched
    assert sleeves.sell_all(c, "momentum", "AAA") is False  # can't sell another sleeve's shares
    assert sleeves.equity(c, "motley_fool") == 20_000


def test_spy_baseline_buys_whole_share_once():
    c = FakeClient(equity=100_000)
    assert spy_baseline(c) is True
    assert c.orders[0].symbol == "SPY" and c.orders[0].notional == 20_000
    c.history.append(  # the order is now waiting at the broker: no second buy
        type("O", (), dict(client_order_id=c.orders[0].client_order_id, symbol="SPY", side="buy",
                           status="accepted", filled_qty="0", filled_avg_price=None,
                           notional=20_000, submitted_at="2000-01-01"))()
    )
    assert spy_baseline(c) is False and len(c.orders) == 1
