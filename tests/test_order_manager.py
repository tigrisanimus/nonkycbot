"""Tests for order manager lifecycle handling."""

from __future__ import annotations

import pytest

from engine.order_manager import Order, OrderManager


def test_order_lifecycle_track_replace_cancel() -> None:
    manager = OrderManager()
    order = Order(
        order_id="1", trading_pair="BTC/USD", side="buy", price=100.0, amount=0.5
    )

    manager.track(order)
    assert manager.get_open_order("1") == order

    replacement = Order(
        order_id="1", trading_pair="BTC/USD", side="buy", price=101.0, amount=0.4
    )
    assert manager.replace("1", replacement)
    assert manager.get_open_order("1") == replacement

    assert manager.cancel("1")
    assert manager.get_open_order("1") is None
    assert list(manager.list_open_orders()) == []


def test_order_manager_rejects_duplicate_and_handles_missing() -> None:
    manager = OrderManager()
    order = Order(
        order_id="2", trading_pair="ETH/USD", side="sell", price=200.0, amount=1.0
    )
    manager.submit(order)

    with pytest.raises(ValueError):
        manager.submit(order)

    assert manager.replace("missing", order) is False
    assert manager.cancel("missing") is False
