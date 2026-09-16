"""Explicit cancellation for a pending gate shell."""

from __future__ import annotations

from pathlib import Path

from sase.gate_shell.lifecycle import (
    DISPOSITION_ANSWERED,
    resolve_already_answered_race,
)
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

    An accepted decision whose execution has not published a response yet
    also blocks cancellation (``cancel_gate`` raises the same
    ``already_answered`` code for a receipt as for a real response), but
    that is not "answered": the receipt is reread and, unless a response
    won the race in the meantime, this returns the record unchanged rather
    than settling it out from under still-running execution.
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
        if exc.code != "already_answered":
            raise
        disposition = resolve_already_answered_race(bundle, record.gate_id)
        if disposition == DISPOSITION_ANSWERED:
            return settle_gate_shell(
                record, gate_state="answered", reason="gate answered"
            )
        return record
    return settle_gate_shell(record, gate_state="stopped", reason=reason)


__all__ = ["DEFAULT_CANCEL_REASON", "cancel_gate_shell"]
