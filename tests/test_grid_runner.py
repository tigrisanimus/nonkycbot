from engine.ladder_runner import normalize_ladder_config


def test_normalize_ladder_config_maps_mmx_grid_fields():
    config = {
        "trading_pair": "MMX/USDT",
        "grid_levels": 10,
        "grid_spread": "0.02",
        "order_amount_mmx": "25",
        "min_notional_usd": "1.1",
    }

    normalized = normalize_ladder_config(config)

    assert normalized["symbol"] == "MMX/USDT"
    assert normalized["step_mode"] == "pct"
    assert normalized["step_pct"] == "0.02"
    assert normalized["base_order_size"] == "25"
    assert normalized["n_buy_levels"] == 10
    assert normalized["n_sell_levels"] == 10
    assert normalized["min_notional_quote"] == "1.1"
