"""VWAP pullback fires a long on a pullback-to-VWAP-and-bounce."""
from quant_desk.strategies.vwap_pullback import VWAPPullback


def test_vwap_pullback_long(vwap_session):
    strat = VWAPPullback(target_r=1.5, min_bars=6)
    sig = None
    for i in range(1, len(vwap_session) + 1):
        s = strat.generate_signal(vwap_session.iloc[:i])
        if s.side != "flat":
            sig = s
            break
    assert sig is not None and sig.side == "long"
    assert sig.stop < sig.target            # long geometry
    assert sig.reason == "vwap pullback long"


def test_vwap_quiet_before_min_bars(vwap_session):
    strat = VWAPPullback(min_bars=6)
    for i in range(1, 6):                    # before min_bars → never signals
        assert strat.generate_signal(vwap_session.iloc[:i]).side == "flat"
