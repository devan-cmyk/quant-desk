"""quant-desk — modular, paper-only-by-default quantitative trading research platform.

Spine: data provider abstraction → pluggable strategies → realistic backtest → risk
engine → simulated paper broker. Live execution is locked behind a hard triple-lock
(see execution.live_guard). Nothing here can place a live order by default.
"""
__version__ = "0.1.0"
