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

from .mean_reversion import MeanReversion


class DailyMeanReversion(MeanReversion):
    name = "dmr"
    intraday = False                      # swing: hold across days (engine won't EOD-flatten)

    def __init__(self, lookback: int = 20, entry_z: float = 1.5, stop_k: float = 2.5,
                 min_strength: float = 0.0, max_hold_bars: int = 5):
        super().__init__(lookback=lookback, entry_z=entry_z, stop_k=stop_k, min_strength=min_strength)
        self.max_hold_bars = max_hold_bars
    # compute_signal is inherited unchanged — the z-score edge is frequency-agnostic.
