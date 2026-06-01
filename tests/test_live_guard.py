"""The triple-lock must keep live trading impossible by default."""
import os

import pytest

from quant_desk.execution.live_guard import LiveTradingLocked, assert_live_allowed
from quant_desk.config import settings


def test_paper_mode_blocks_live():
    assert settings.trading_mode == "paper"
    with pytest.raises(LiveTradingLocked):
        assert_live_allowed("anything")


def test_all_locks_required(monkeypatch):
    # even with mode=live, missing env/config/token each independently blocks
    monkeypatch.setattr(settings, "trading_mode", "live")
    with pytest.raises(LiveTradingLocked):           # no env
        assert_live_allowed("t")
    monkeypatch.setenv("QD_ALLOW_LIVE_ENV", "1")
    with pytest.raises(LiveTradingLocked):           # no config consent
        assert_live_allowed("t")
    monkeypatch.setattr(settings, "allow_live", True)
    with pytest.raises(LiveTradingLocked):           # token unset/mismatch
        assert_live_allowed("wrong")
    monkeypatch.setattr(settings, "live_unlock_token", "secret")
    assert_live_allowed("secret")                    # all four → allowed (no raise)
