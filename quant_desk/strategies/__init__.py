from .base import Signal, Strategy  # noqa: F401
from .opening_range_breakout import OpeningRangeBreakout  # noqa: F401

REGISTRY = {"orb": OpeningRangeBreakout}
