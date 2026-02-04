"""Strategy implementations for nonkyc bot."""

from .adaptive_capped_martingale import describe as adaptive_capped_martingale_describe
from .grid import describe as grid_describe
from .infinity_ladder_grid import describe as infinity_grid_describe
from .market_maker import describe as market_maker_describe
from .rebalance import describe as rebalance_describe
from .triangular_arb import describe as triangular_arb_describe

__all__ = [
    "adaptive_capped_martingale_describe",
    "grid_describe",
    "infinity_grid_describe",
    "market_maker_describe",
    "rebalance_describe",
    "triangular_arb_describe",
]
