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

    def initialize(self, ctx: dict | None = None) -> None:
        """Reset per-run state."""

    @abstractmethod
    def generate_signal(self, window: pd.DataFrame) -> Signal:
        """Given OHLCV history up to and including the current bar, emit a Signal.
        Return Signal(side='flat') to do nothing."""

    def exit_logic(self, window: pd.DataFrame, entry: dict) -> bool:
        """Optional discretionary exit (beyond stop/target/EOD the engine enforces)."""
        return False
