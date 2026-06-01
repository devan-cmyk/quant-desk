"""System health self-diagnostics: classify intact / stale / corrupt state, worst-severity wins."""
import json
import os
import sqlite3
import time

from quant_desk.health import system_health


def _healthy_state(state_dir, repo_dir):
    os.makedirs(state_dir, exist_ok=True); os.makedirs(repo_dir, exist_ok=True)
    with open(os.path.join(state_dir, "registry.json"), "w") as f:
        json.dump({"orb:SPY": {"verdict": "promote"}}, f)
    db = sqlite3.connect(os.path.join(state_dir, "journal.db"))
    db.execute("CREATE TABLE research_log (id INTEGER)"); db.execute("INSERT INTO research_log VALUES (1)")
    db.commit(); db.close()
    with open(os.path.join(state_dir, "paper_state.json"), "w") as f:
        json.dump({"cash": 100000.0, "positions": {}, "blotter": []}, f)


def test_healthy_system_scores_high(tmp_path):
    sd, rd = str(tmp_path / "state"), str(tmp_path / "repo")
    _healthy_state(sd, rd)
    h = system_health(repo_dir=rd, state_dir=sd)
    assert h["status"] in ("healthy", "degraded")    # no data cache → at worst degraded
    assert any(c["name"] == "paper_state" and c["ok"] for c in h["checks"])
    assert any(c["name"] == "journal" and c["ok"] for c in h["checks"])


def test_corrupt_paper_state_is_critical(tmp_path):
    sd, rd = str(tmp_path / "state"), str(tmp_path / "repo")
    _healthy_state(sd, rd)
    with open(os.path.join(sd, "paper_state.json"), "w") as f:
        f.write("{ truncated not valid json")          # simulate a torn/corrupt write
    h = system_health(repo_dir=rd, state_dir=sd)
    assert h["status"] == "critical"
    assert any(c["name"] == "paper_state" and not c["ok"] and c["severity"] == "critical" for c in h["checks"])


def test_stale_gate_flagged_degraded(tmp_path):
    sd, rd = str(tmp_path / "state"), str(tmp_path / "repo")
    _healthy_state(sd, rd)
    old = time.time() - 30 * 86400                     # registry 30 days old → stale gate
    os.utime(os.path.join(sd, "registry.json"), (old, old))
    h = system_health(repo_dir=rd, state_dir=sd)
    gate = next(c for c in h["checks"] if c["name"] == "gate_fresh")
    assert not gate["ok"] and "STALE" in gate["detail"]
    assert h["status"] in ("degraded", "critical")


def test_heartbeat_detects_a_stopped_agent(tmp_path):
    import json, time, datetime as dt
    from quant_desk.health import record_heartbeat, system_health
    sd, rd = str(tmp_path / "state"), str(tmp_path / "repo")
    _healthy_state(sd, rd)
    # a fresh heartbeat (paper_run just ran) and a stale one (review stopped 20 days ago)
    record_heartbeat("paper_run", interval="1d", state_dir=sd)
    hb_path = os.path.join(sd, "heartbeats.json")
    hb = json.load(open(hb_path))
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=20)).isoformat()
    hb["review:1d"] = {"ts": old, "command": "review"}
    json.dump(hb, open(hb_path, "w"))
    chk = next(c for c in system_health(repo_dir=rd, state_dir=sd)["checks"] if c["name"] == "agent_heartbeats")
    assert not chk["ok"] and "review:1d" in chk["detail"]      # the stopped agent is flagged
    assert "paper_run" not in chk["detail"]                    # the live one is not


def test_agent_stderr_flagged(tmp_path):
    sd, rd = str(tmp_path / "state"), str(tmp_path / "repo")
    _healthy_state(sd, rd)
    with open(os.path.join(rd, "review.err.log"), "w") as f:
        f.write("Traceback (most recent call last): ...")
    h = system_health(repo_dir=rd, state_dir=sd)
    ae = next(c for c in h["checks"] if c["name"] == "agent_errors")
    assert not ae["ok"] and "review.err.log" in ae["detail"]
