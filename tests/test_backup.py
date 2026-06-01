"""Integrity-verified state backup: verify intact/corrupt source, detect a tampered archive,
restore round-trip, and never rotate out good backups when the source is corrupt."""
import json
import os
import sqlite3
import tarfile

from quant_desk import backup as bk


def _state(d):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "registry.json"), "w") as f:
        json.dump({"orb:SPY": {"verdict": "promote"}}, f)
    with open(os.path.join(d, "paper_state.json"), "w") as f:
        json.dump({"cash": 100000.0, "positions": {}, "blotter": []}, f)
    db = sqlite3.connect(os.path.join(d, "journal.db"))
    db.execute("CREATE TABLE research_log (id INTEGER)"); db.execute("INSERT INTO research_log VALUES (1)")
    db.commit(); db.close()


def test_verify_state_flags_corruption(tmp_path):
    s = str(tmp_path / "state"); _state(s)
    assert bk.verify_state(s)["all_ok"] is True
    with open(os.path.join(s, "registry.json"), "w") as f:
        f.write("{ not valid")
    v = bk.verify_state(s)
    assert v["all_ok"] is False and v["files"]["registry.json"]["ok"] is False


def test_create_and_verify_backup(tmp_path):
    s, b = str(tmp_path / "state"), str(tmp_path / "bk"); _state(s)
    res = bk.create_backup(s, b)
    assert res["all_ok"] and os.path.exists(res["archive"])
    assert bk.verify_backup(res["archive"])["restorable"] is True


def test_tampered_archive_is_detected(tmp_path):
    s, b = str(tmp_path / "state"), str(tmp_path / "bk"); _state(s)
    arch = bk.create_backup(s, b)["archive"]
    # rewrite the archive with a registry whose bytes don't match the manifest sha256
    import io, gzip, shutil
    with tarfile.open(arch, "r:gz") as t:
        t.extractall(str(tmp_path / "x"))
    with open(str(tmp_path / "x" / "registry.json"), "w") as f:
        json.dump({"orb:SPY": {"verdict": "TAMPERED"}}, f)
    with tarfile.open(arch, "w:gz") as t:
        for fn in os.listdir(str(tmp_path / "x")):
            t.add(str(tmp_path / "x" / fn), arcname=fn)
    v = bk.verify_backup(arch)
    assert v["restorable"] is False
    assert "SHA MISMATCH" in v["files"]["registry.json"]["detail"]


def test_restore_roundtrip_and_stashes_current(tmp_path):
    s, b = str(tmp_path / "state"), str(tmp_path / "bk"); _state(s)
    arch = bk.create_backup(s, b)["archive"]
    # mutate live state, then restore the backup
    with open(os.path.join(s, "registry.json"), "w") as f:
        json.dump({"orb:SPY": {"verdict": "CHANGED"}}, f)
    r = bk.restore_backup(arch, s)
    assert json.load(open(os.path.join(s, "registry.json")))["orb:SPY"]["verdict"] == "promote"
    assert os.path.isdir(r["previous_state_saved_to"])    # current state was stashed, not lost


def test_corrupt_source_does_not_rotate_out_good_backups(tmp_path):
    s, b = str(tmp_path / "state"), str(tmp_path / "bk"); _state(s)
    bk.create_backup(s, b, keep=1)                         # one good backup
    with open(os.path.join(s, "registry.json"), "w") as f:
        f.write("{ corrupt")                              # now source is corrupt
    res = bk.create_backup(s, b, keep=1)
    assert res["all_ok"] is False and res["rotated_out"] == []   # good backup preserved
    assert len(bk.list_backups(b)) == 2
