"""Detect gate transitions and emit alerts.

State per pair is just {blocked, reason}. Diffing the current gate against the last-alerted
snapshot yields events: a pair that flipped TRADING→BLOCKED (high severity), BLOCKED→TRADING
(cleared), or a newly-approved pair (info). The snapshot makes it idempotent — re-running
raises no duplicate alerts. Channels: a JSON feed (always), macOS notification (default on,
QD_ALERT_MACOS=0 to mute), webhook (off unless QD_ALERT_WEBHOOK is set).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import platform
import subprocess

FEED_MAX = 200


def _path(env: str, default: str) -> str:
    return os.environ.get(env) or os.path.expanduser(default)


def _reason(e: dict) -> str:
    if e.get("verdict") in ("reject", "retire"):
        return e.get("verdict_rationale") or e["verdict"]
    if e.get("forward") == "drift":
        return e.get("forward_detail") or "forward drift"
    if e.get("status") == "retired":
        return "decay monitor retired"
    return ""


def gate_state(reg) -> dict:
    """{pair: {blocked, verdict, reason}} for every strategy:symbol in the registry."""
    out = {}
    for key, e in reg.data.items():
        strat, _, sym = key.partition(":")
        out[key] = {"blocked": reg.is_blocked(strat, sym),
                    "verdict": e.get("verdict"), "reason": _reason(e)}
    return out


def diff_gate(prev: dict, curr: dict) -> list[dict]:
    """Transitions worth an alert, newest-relevant first by severity."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    events = []
    for pair, c in curr.items():
        p = prev.get(pair)
        if p is None:
            # a pair we've never alerted on: only announce it once it's actively tradeable
            if not c["blocked"] and c["verdict"] in ("promote", "paper_watch"):
                events.append({"ts": now, "pair": pair, "kind": "approved", "severity": "info",
                               "message": f"{pair} approved & trading ({c['verdict']})"})
            continue
        if not p["blocked"] and c["blocked"]:
            events.append({"ts": now, "pair": pair, "kind": "blocked", "severity": "high",
                           "message": f"{pair} BLOCKED — {c['reason'] or 'gate'}"})
        elif p["blocked"] and not c["blocked"]:
            events.append({"ts": now, "pair": pair, "kind": "cleared", "severity": "info",
                           "message": f"{pair} cleared — trading again ({c['verdict']})"})
    events.sort(key=lambda e: e["severity"] != "high")     # high severity first
    return events


class AlertFeed:
    """Append-only-ish JSON feed (capped) the dashboard reads."""
    def __init__(self, path: str | None = None):
        self.path = path or _path("QD_ALERTS", "~/.quant-desk/alerts.json")
        self.items = json.load(open(self.path)) if os.path.exists(self.path) else []

    def append(self, events: list[dict]) -> None:
        self.items = (self.items + events)[-FEED_MAX:]

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        json.dump(self.items, open(self.path, "w"), indent=2)

    def recent(self, n: int = 30) -> list[dict]:
        return list(reversed(self.items))[:n]


def _ascii(s: str) -> str:
    """osascript -e is unreliable with non-ASCII; keep the desktop popup plain (the feed
    retains the full unicode message)."""
    return (s.replace("—", "-").replace("–", "-").replace("≤", "<=").replace("≥", ">=")
            .encode("ascii", "ignore").decode().strip())


def _notify_macos(events: list[dict]) -> None:
    if platform.system() != "Darwin" or os.environ.get("QD_ALERT_MACOS") == "0":
        return
    highs = [e for e in events if e["severity"] == "high"] or events
    title = "quant-desk gate"
    body = _ascii(highs[0]["message"] if len(highs) == 1
                  else f"{len(events)} gate changes - {highs[0]['message']}")
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification {json.dumps(body)} with title {json.dumps(title)}'],
                       check=False, timeout=10)
    except Exception:
        pass


def _notify_webhook(events: list[dict]) -> None:
    url = os.environ.get("QD_ALERT_WEBHOOK")
    if not url:
        return
    import urllib.request
    payload = json.dumps({"text": "quant-desk gate changes:\n" +
                          "\n".join(f"• {e['message']}" for e in events)}).encode()
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def run_alerts(reg, *, snapshot_path: str | None = None, notify: bool = True) -> list[dict]:
    """Diff the gate vs the last-alerted snapshot, record + emit any changes, advance the
    snapshot. Returns the events raised (empty if the gate is unchanged)."""
    snap_path = snapshot_path or _path("QD_GATE_SNAPSHOT", "~/.quant-desk/gate_snapshot.json")
    prev = json.load(open(snap_path)) if os.path.exists(snap_path) else {}
    curr = gate_state(reg)
    events = diff_gate(prev, curr)
    if events:
        feed = AlertFeed(); feed.append(events); feed.save()
        if notify:
            _notify_macos(events)
            _notify_webhook(events)
    os.makedirs(os.path.dirname(snap_path), exist_ok=True)
    json.dump(curr, open(snap_path, "w"), indent=2)
    return events
