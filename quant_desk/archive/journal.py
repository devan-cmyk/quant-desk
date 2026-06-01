"""Research & decision journal — an APPEND-ONLY audit ledger (SQLite, stdlib). Every
validation run, edge-decay assessment, retirement, and paper-trading session is recorded
with its evidence, so the system remembers and every decision is accountable. There is no
update/delete API — records are immutable, per the institutional audit requirement.

kinds: backtest · walkforward · multisymbol · montecarlo · stress · monitor · retirement
       · recovery · paper_run
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3


def _default_path() -> str:
    return os.environ.get("QD_JOURNAL") or os.path.expanduser("~/.quant-desk/journal.db")


class Journal:
    def __init__(self, path: str | None = None):
        self.path = path or _default_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS research_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT NOT NULL,
                kind      TEXT NOT NULL,
                strategy  TEXT,
                symbols   TEXT,
                summary   TEXT,
                decision  TEXT,
                payload   TEXT
            )""")
        self.db.commit()

    def record(self, kind: str, *, strategy: str = "", symbols=None, summary: str = "",
               decision: str = "", payload: dict | None = None) -> int:
        ts = dt.datetime.now(dt.timezone.utc).isoformat()
        syms = ",".join(symbols) if isinstance(symbols, (list, tuple)) else (symbols or "")
        cur = self.db.execute(
            "INSERT INTO research_log (ts, kind, strategy, symbols, summary, decision, payload) "
            "VALUES (?,?,?,?,?,?,?)",
            (ts, kind, strategy, syms, summary[:500], decision[:500],
             json.dumps(payload or {})[:8000]))
        self.db.commit()
        return cur.lastrowid

    def recent(self, n: int = 50, kind: str | None = None) -> list[dict]:
        q = "SELECT id,ts,kind,strategy,symbols,summary,decision,payload FROM research_log"
        args: tuple = ()
        if kind:
            q += " WHERE kind=?"; args = (kind,)
        q += " ORDER BY id DESC LIMIT ?"
        rows = self.db.execute(q, args + (n,)).fetchall()
        cols = ["id", "ts", "kind", "strategy", "symbols", "summary", "decision", "payload"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            try:
                d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
            except Exception:
                d["payload"] = {}
            out.append(d)
        return out

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM research_log").fetchone()[0]

    def close(self) -> None:
        self.db.close()
