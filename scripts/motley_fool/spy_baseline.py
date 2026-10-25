"""The benchmark sleeve: put its whole share into SPY once and hold. Anything that can't beat this isn't worth running."""

import sleeves

SLEEVE = "spy"


def spy_baseline(client) -> bool:
    """Buy SPY with the sleeve's cash if it hasn't bought yet. True if an order was placed."""
    b = sleeves.book(client, SLEEVE)
    if b["positions"] or b["cash"] < sleeves.allocation(client) - 1:  # already bought, or an order is waiting
        return False
    return sleeves.buy(client, SLEEVE, "SPY", b["cash"]) > 0
