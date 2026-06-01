"""Walk-forward param refresh — keep DEPLOYED params current between committee reviews.

The committee's walk-forward VALIDATES that an edge is robust and stores the last in-sample
fold's best params (fit on a window that ends before the data's most recent sessions). This
layer re-fits the production params of already-promoted pairs on the MOST RECENT window, but
only adopts the refresh if it holds up on a fresh holdout AND is no worse than the params in
use — a strictly improvement-seeking, capital-preserving update that never re-litigates the
promotion decision (review owns that) and never overfits to recent noise (the holdout guards).
"""
from .refresh import refresh_params

__all__ = ["refresh_params"]
