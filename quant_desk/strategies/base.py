"""Pluggable strategy framework. New strategies subclass Strategy and implement
generate_signal(). The backtest/live engine drives the lifecycle; the risk engine sizes
and vetoes — strategies never size or place orders themselves."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

SIDES = ("long", "short", "flat")


@dataclass
class Signal:
    side: str = "flat"            # long | short | flat
    stop: float | None = None     # absolute price for protective stop
    target: float | None = None   # absolute price for profit target
    strength: float = 1.0         # 0..1 conviction (feeds the signal score later)
    reason: str = ""

    def __post_init__(self):
        if self.side not in SIDES:
            raise ValueError(f"invalid side {self.side!r}")


class Strategy(ABC):
    name: str = "base"
    min_strength: float = 0.0      # conviction filter: drop signals weaker than this (0 = off)

    def initialize(self, ctx: dict | None = None) -> None:
        """Reset per-run state."""

    def generate_signal(self, window: pd.DataFrame) -> Signal:
        """Public entry: compute the raw signal, then apply the conviction filter — a research
        knob (committee-tunable) that makes a strategy SELECTIVE, taking only its higher-conviction
        setups. Fewer, better trades survive costs better than many marginal ones."""
        sig = self.compute_signal(window)
        if sig.side in ("long", "short") and sig.strength < self.min_strength:
            return Signal()
        return sig

    @abstractmethod
    def compute_signal(self, window: pd.DataFrame) -> Signal:
        """Given OHLCV history up to and including the current bar, emit a raw Signal.
        Return Signal(side='flat') to do nothing."""

    def exit_logic(self, window: pd.DataFrame, entry: dict) -> bool:
        """Optional discretionary exit (beyond stop/target/EOD the engine enforces)."""
        return False
