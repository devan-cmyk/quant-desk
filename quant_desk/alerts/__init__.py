"""Gate alerting — notify when the promotion gate CHANGES (a pair newly blocked or newly
approved), by diffing the current gate against the last-alerted snapshot. Local-first: every
alert is appended to a persistent feed the dashboard reads, and (on macOS) raised as a desktop
notification. An external webhook is strictly opt-in via QD_ALERT_WEBHOOK and off by default —
nothing leaves the machine unless the owner configures it. Read-only; paper-only system.
"""
from .gate_alerts import gate_state, diff_gate, run_alerts, AlertFeed

__all__ = ["gate_state", "diff_gate", "run_alerts", "AlertFeed"]
