"""Reclaim pending gate shells whose gates have already terminalized or expired."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.config import get_gate_shell_reclaim_grace_seconds
from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.store import list_gate_shells
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.paths import CANCELLATION_FILENAME, RESPONSE_FILENAME


@dataclass(frozen=True)
class _GateShellReclaimSummary:
    """Summary of one reclaim pass."""

    scanned: int = 0
    answered: int = 0
    stopped: int = 0
    timed_out: int = 0
    lost: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "answered": self.answered,
            "stopped": self.stopped,
            "timed_out": self.timed_out,
            "lost": self.lost,
            "errors": self.errors,
        }


def reclaim_pending_gate_shells(
    *,
    now: float | None = None,
    grace_seconds: int | None = None,
    project: str | None = None,
) -> _GateShellReclaimSummary:
    """Settle pending gate shells that no longer have a live pending gate."""
    current = time.time() if now is None else now
    grace = (
        get_gate_shell_reclaim_grace_seconds()
        if grace_seconds is None
        else grace_seconds
    )
    counts = {
        "scanned": 0,
        "answered": 0,
        "stopped": 0,
        "timed_out": 0,
        "lost": 0,
        "errors": 0,
    }
    for record in list_gate_shells(project=project):
        if record.is_terminal:
            continue
        counts["scanned"] += 1
        try:
            state = _reclaim_one(record, now=current, grace_seconds=grace)
        except Exception:
            counts["errors"] += 1
            continue
        if state == "answered":
            counts["answered"] += 1
        elif state == "stopped":
            counts["stopped"] += 1
        elif state == "timeout":
            counts["timed_out"] += 1
        elif state == "lost":
            counts["lost"] += 1
    return _GateShellReclaimSummary(**counts)


def _reclaim_one(
    record: GateShellRecord,
    *,
    now: float,
    grace_seconds: int,
) -> str | None:
    bundle = Path(record.bundle_path) if record.bundle_path else None
    if bundle is None or not bundle.is_dir():
        settle_gate_shell(record, gate_state="lost", reason="gate bundle unreachable")
        return "lost"
    try:
        envelope, _adapter = load_and_verify_bundle(bundle)
    except Exception:
        settle_gate_shell(record, gate_state="lost", reason="gate bundle unreadable")
        return "lost"

    response_path = bundle / RESPONSE_FILENAME
    if response_path.exists():
        settle_gate_shell(record, gate_state="answered", reason="gate answered")
        return "answered"
    cancellation_path = bundle / CANCELLATION_FILENAME
    if cancellation_path.exists():
        cancellation = _read_json(cancellation_path)
        reason = str(cancellation.get("reason") or "")
        if reason == "timeout":
            settle_gate_shell(record, gate_state="timeout", reason="gate timed out")
            return "timeout"
        settle_gate_shell(record, gate_state="stopped", reason=reason or "gate stopped")
        return "stopped"

    deadline = _deadline(envelope)
    if deadline is None:
        return None
    if now >= deadline + grace_seconds:
        settle_gate_shell(
            record, gate_state="lost", reason="gate deadline grace passed"
        )
        return "lost"
    if now >= deadline:
        cancel_gate(bundle, reason="timeout", source="gate_shell_reclaim")
        settle_gate_shell(record, gate_state="timeout", reason="gate timed out")
        return "timeout"
    return None


def _deadline(envelope: dict[str, Any]) -> float | None:
    created = envelope.get("created_at_unix")
    timeout_seconds = envelope.get("gate_timeout_seconds")
    if isinstance(created, (int, float)) and isinstance(timeout_seconds, (int, float)):
        return float(created) + float(timeout_seconds)
    return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path)
    except Exception:
        return {}


__all__ = ["reclaim_pending_gate_shells"]
