from .base import Signal, Strategy  # noqa: F401
from .opening_range_breakout import OpeningRangeBreakout  # noqa: F401
from .vwap_pullback import VWAPPullback  # noqa: F401
from .mean_reversion import MeanReversion  # noqa: F401

REGISTRY = {"orb": OpeningRangeBreakout, "vwap": VWAPPullback, "meanrev": MeanReversion}
