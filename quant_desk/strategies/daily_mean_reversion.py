"""Daily Mean Reversion (swing) — the lower-frequency cousin of MeanReversion.

Same Bollinger z-score signal, but on DAILY bars and held for several days (swing), so a single
round-trip cost is amortized over a multi-percent reversion instead of paying friction on
hundreds of intraday scalps. An offline probe showed this is net-positive across a 5-year
split-sample where the 5-minute version bled — this class lets the committee validate that
claim out-of-sample, through the same walk-forward + cost-stress + decay gauntlet.

intraday=False makes the engine hold across days; max_hold_bars caps the hold; the stop (k·σ
below entry, wide by default so reversion has room) bounds downside; target = the rolling mean.
"""
from __future__ import annotations

from .base import Signal
from .mean_reversion import MeanReversion
from ..regime.volatility import vol_spike


class DailyMeanReversion(MeanReversion):
    name = "dmr"
    intraday = False                      # swing: hold across days (engine won't EOD-flatten)

    def __init__(self, lookback: int = 20, entry_z: float = 1.5, stop_k: float = 2.5,
                 min_strength: float = 0.0, max_hold_bars: int = 5,
                 max_vol_ratio: float | None = 1.8):
        super().__init__(lookback=lookback, entry_z=entry_z, stop_k=stop_k, min_strength=min_strength)
        self.max_hold_bars = max_hold_bars
        # Volatility circuit-breaker is MANDATORY (default on), NOT a committee-tuned param. A
        # walk-forward over a benign window can't value tail protection — it sees the cost (fewer
        # trades) but not the benefit (the crash isn't in-window), so it always disables it. Its
        # justification is the 33-year out-of-sample evidence (it turned 2020 from −2.1% to +1.0%
        # while slightly improving the overall edge), so it lives with the other non-negotiable
        # risk gates rather than the optimizer. Set to None only to study its effect.
        self.max_vol_ratio = max_vol_ratio

    def compute_signal(self, window):
        # in a volatility blow-up, don't fade — reversion gets steamrolled (the 2020 failure mode)
        if self.max_vol_ratio is not None and vol_spike(window, max_ratio=self.max_vol_ratio):
            return Signal()
        return super().compute_signal(window)
