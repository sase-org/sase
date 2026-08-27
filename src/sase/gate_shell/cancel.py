"""Explicit cancellation for a pending gate shell."""

from __future__ import annotations

from pathlib import Path

from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.settlement import settle_gate_shell
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import RESPONSE_FILENAME

DEFAULT_CANCEL_REASON = "cancelled via sase gate cancel"


def cancel_gate_shell(
    record: GateShellRecord,
    *,
    reason: str = DEFAULT_CANCEL_REASON,
) -> GateShellRecord:
    """Cancel one pending gate shell, settling it into a terminal state.

    Mirrors the reclaim chop's terminal checks (:mod:`sase.gate_shell.reclaim`):
    an already-terminal shell is returned unchanged, an already-answered gate
    settles as answered rather than being cancelled out from under its
    reviewer, and an unreachable bundle settles as lost.
    """
    if record.is_terminal:
        return record
    bundle = Path(record.bundle_path) if record.bundle_path else None
    if bundle is None or not bundle.is_dir():
        return settle_gate_shell(
            record, gate_state="lost", reason="gate bundle unreachable"
        )
    if (bundle / RESPONSE_FILENAME).exists():
        return settle_gate_shell(record, gate_state="answered", reason="gate answered")
    try:
        cancel_gate(bundle, reason=reason, source="gate_shell_cancel")
    except GateError as exc:
        if exc.code == "already_answered":
            return settle_gate_shell(
                record, gate_state="answered", reason="gate answered"
            )
        raise
    return settle_gate_shell(record, gate_state="stopped", reason=reason)


__all__ = ["DEFAULT_CANCEL_REASON", "cancel_gate_shell"]
