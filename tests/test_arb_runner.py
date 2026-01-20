"""Tests for the arbitrage runner."""

from decimal import Decimal

import run_arb_bot


def test_evaluate_profitability_executes_without_prompt(monkeypatch) -> None:
    config = {
        "asset_a": "USDT",
        "asset_b": "ETH",
        "asset_c": "BTC",
        "pair_ab": "ETH/USDT",
        "pair_bc": "ETH/BTC",
        "pair_ac": "BTC/USDT",
        "trade_amount_a": "100",
        "min_profitability": "0.05",
        "fee_rate": "0",
        "min_notional_usd": "0.01",
    }
    prices = {
        "ETH/USDT": Decimal("100"),
        "ETH/BTC": Decimal("0.1"),
        "BTC/USDT": Decimal("1200"),
    }
    called = {"value": False}
    current_balance = Decimal("100")

    def fake_execute_arbitrage(client, config_arg, prices_arg, start_amount, mode="live"):
        called["value"] = True
        assert config_arg is config
        assert prices_arg == prices
        assert start_amount == current_balance
        # Return a profitable amount
        return Decimal("120")

    def fail_input(*args, **kwargs):
        raise AssertionError("input() should not be called when profitable")

    monkeypatch.setattr(run_arb_bot, "execute_arbitrage", fake_execute_arbitrage)
    monkeypatch.setattr("builtins.input", fail_input)

    result = run_arb_bot.evaluate_profitability_and_execute(
        client=object(),
        config=config,
        prices=prices,
        current_balance=current_balance,
    )

    assert result == Decimal("120")
    assert called["value"] is True
