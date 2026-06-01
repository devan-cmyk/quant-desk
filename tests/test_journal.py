"""Research journal: append-only, queryable, immutable audit ledger."""
from quant_desk.archive.journal import Journal


def test_record_recent_and_count(tmp_path):
    jr = Journal(path=str(tmp_path / "j.db"))
    jr.record("monitor", strategy="orb", symbols=["SPY", "QQQ"], summary="5 healthy, 1 retired")
    jr.record("retirement", strategy="orb", symbols=["AAPL"], summary="AAPL: healthy → retired",
              decision="edge decayed — retired")
    jr.record("paper_run", strategy="orb", symbols=["SPY"], summary="78 bars · equity 99564")
    assert jr.count() == 3
    rows = jr.recent(10)
    assert [r["kind"] for r in rows] == ["paper_run", "retirement", "monitor"]   # newest first
    assert rows[1]["decision"] == "edge decayed — retired"
    assert rows[0]["symbols"] == "SPY"


def test_kind_filter_and_persistence(tmp_path):
    p = str(tmp_path / "j.db")
    jr = Journal(path=p)
    jr.record("monitor", strategy="orb", summary="run 1")
    jr.record("retirement", strategy="orb", symbols=["AAPL"], summary="retired AAPL")
    jr.close()
    jr2 = Journal(path=p)                          # reopen → durable
    assert jr2.count() == 2
    rets = jr2.recent(10, kind="retirement")
    assert len(rets) == 1 and rets[0]["summary"] == "retired AAPL"


def test_journal_is_append_only():
    # the immutable-audit requirement: no update/delete API exists
    assert not hasattr(Journal, "update")
    assert not hasattr(Journal, "delete")
