"""Integrity-verified state backup + restore.

The autonomous platform's entire memory lives in ~/.quant-desk — the committee gate (registry),
the append-only audit journal, the paper account, the alert feed/snapshot. Corruption or loss
there loses everything. This snapshots that state to a timestamped, checksummed tar.gz, but only
after VERIFYING integrity (every JSON parses; the journal passes SQLite integrity_check), so a
backup is always known-restorable. Restore re-verifies the archive against its manifest before
overwriting, and backs up the current state first. Old backups rotate, but a corrupt source
never rotates out a good one.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import tarfile
import tempfile

STATE_DIR = os.path.expanduser("~/.quant-desk")
BACKUP_DIR = os.environ.get("QD_BACKUP_DIR") or os.path.expanduser("~/.quant-desk-backups")
STATE_FILES = ["registry.json", "journal.db", "paper_state.json", "alerts.json", "gate_snapshot.json"]
KEEP = 14


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_file(path: str) -> dict:
    """sha256 + a content-integrity check appropriate to the file type."""
    info = {"sha256": _sha256(path), "bytes": os.path.getsize(path)}
    try:
        if path.endswith(".json"):
            with open(path) as f:
                json.load(f)
            info["ok"], info["detail"] = True, "valid json"
        elif path.endswith(".db"):
            db = sqlite3.connect(path)
            res = db.execute("PRAGMA integrity_check").fetchone()[0]
            db.close()
            info["ok"] = res == "ok"
            info["detail"] = f"integrity_check: {res}"
        else:
            info["ok"], info["detail"] = True, "opaque (checksum only)"
    except Exception as e:
        info["ok"], info["detail"] = False, f"CORRUPT: {str(e)[:60]}"
    return info


def verify_state(state_dir: str = STATE_DIR) -> dict:
    """Integrity of each present state file. all_ok=False ⇒ live state is corrupt."""
    files = {f: _verify_file(os.path.join(state_dir, f))
             for f in STATE_FILES if os.path.exists(os.path.join(state_dir, f))}
    return {"files": files, "all_ok": all(v["ok"] for v in files.values()), "n": len(files)}


def create_backup(state_dir: str = STATE_DIR, backup_dir: str = BACKUP_DIR, keep: int = KEEP) -> dict:
    os.makedirs(backup_dir, exist_ok=True)
    ver = verify_state(state_dir)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")   # μs ⇒ no same-second collision
    archive = os.path.join(backup_dir, f"qd-state-{ts}.tar.gz")
    manifest = {"ts": ts, "state_dir": state_dir, "all_ok": ver["all_ok"], "files": ver["files"]}

    # write atomically: build under .tmp then rename, so a half-written archive is never seen
    tmp = archive + ".tmp"
    with tarfile.open(tmp, "w:gz") as tar:
        for fname in ver["files"]:
            tar.add(os.path.join(state_dir, fname), arcname=fname)
        mbytes = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo("manifest.json"); info.size = len(mbytes)
        import io
        tar.addfile(info, io.BytesIO(mbytes))
    os.replace(tmp, archive)

    rotated = []
    if ver["all_ok"]:                              # never let a CORRUPT source rotate out good backups
        backups = sorted(p for p in os.listdir(backup_dir) if p.startswith("qd-state-") and p.endswith(".tar.gz"))
        for old in backups[:-keep] if len(backups) > keep else []:
            os.remove(os.path.join(backup_dir, old)); rotated.append(old)
    return {"archive": archive, "all_ok": ver["all_ok"], "n_files": ver["n"],
            "rotated_out": rotated, "manifest": manifest}


def verify_backup(archive: str) -> dict:
    """Re-verify an archive is restorable: each member's sha256 matches the manifest AND the
    extracted content passes its integrity check."""
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(tmp, filter="data")
        with open(os.path.join(tmp, "manifest.json")) as f:
            manifest = json.load(f)
        results = {}
        for fname, expect in manifest["files"].items():
            p = os.path.join(tmp, fname)
            if not os.path.exists(p):
                results[fname] = {"ok": False, "detail": "missing from archive"}; continue
            v = _verify_file(p)
            results[fname] = {"ok": v["ok"] and v["sha256"] == expect["sha256"],
                              "detail": v["detail"] + ("" if v["sha256"] == expect["sha256"] else " · SHA MISMATCH")}
        return {"archive": archive, "restorable": all(r["ok"] for r in results.values()), "files": results}


def restore_backup(archive: str, state_dir: str = STATE_DIR) -> dict:
    """Verify the archive, snapshot the current (possibly corrupt) state aside, then restore."""
    v = verify_backup(archive)
    if not v["restorable"]:
        raise RuntimeError(f"refusing to restore — archive failed verification: {v['files']}")
    os.makedirs(state_dir, exist_ok=True)
    pre = os.path.join(state_dir, f"_pre_restore_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
    os.makedirs(pre, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(tmp, filter="data")
        restored = []
        for fname in [f for f in os.listdir(tmp) if f != "manifest.json"]:
            cur = os.path.join(state_dir, fname)
            if os.path.exists(cur):
                os.replace(cur, os.path.join(pre, fname))      # stash current first
            os.replace(os.path.join(tmp, fname), cur)
            restored.append(fname)
    return {"archive": archive, "restored": restored, "previous_state_saved_to": pre}


def list_backups(backup_dir: str = BACKUP_DIR) -> list[str]:
    if not os.path.isdir(backup_dir):
        return []
    return sorted(os.path.join(backup_dir, p) for p in os.listdir(backup_dir)
                  if p.startswith("qd-state-") and p.endswith(".tar.gz"))
