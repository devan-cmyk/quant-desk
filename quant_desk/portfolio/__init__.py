"""Portfolio layer — diversification-aware capital allocation across the promoted basket.

Once several strategy:symbol edges clear the committee gate, they should NOT all carry the
same risk: redundant (highly-correlated) edges add little diversification, and louder
(higher-vol) edges already consume more risk per unit size. This layer measures the
correlation of the edges' return streams and sets a per-pair risk weight — an overlay on the
risk engine's per-trade sizing, not a return optimizer (no mean-variance fitting, which
overfits on short samples; AQROS Section 19). Equal weights reproduce the prior behavior.
"""
from .allocate import session_returns, correlation_matrix, allocate

__all__ = ["session_returns", "correlation_matrix", "allocate"]
