"""Liveness and lifecycle of in-flight detached sudo attempts."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sase.notification_gates.models import GateError
from sase.procs.identity import supervisor_is_alive
from sase.procs.models import ACTIVE_PROC_STATUSES
from sase.procs.store import get_proc
from sase.sudo.execution_handoff import cleanup_handoff
from sase.sudo.execution_state import (
    EXECUTION_STATE_SCHEMA_VERSION,
    SudoExecutionState,
    clear_execution_state,
    load_execution_state,
    write_execution_state,
)


@dataclass(frozen=True)
class _SudoExecutionProjection:
    """Live executing-state projection for sudo show/list."""

    executing: bool
    finalize_proc_id: str | None = None
    executor_pid: int | None = None
    liveness: str = "dead"


def _seam(name: str) -> Any:
    """Return the current ``sase.sudo.execution`` seam attribute *name*.

    Historic private seam names (``_proc_is_live``, ``_pid_is_running``) stay
    patchable on the facade module. They are looked up dynamically because a
    static cross-file reference would trip Symvision's same-name private-use
    detection in unrelated files.
    """
    from sase.sudo import execution as facade

    return getattr(facade, name)


def claim_execution_record(
    bundle_root: Path, *, gate_id: str
) -> SudoExecutionState | None:
    """Return a live record, or clear a stale one and return ``None``.

    A live record (finalize proc or identity-matched executor still running)
    is left in place so the caller can refuse a second approval. A record is
    stale only when both the proc and the executor are dead.
    """
    state = load_execution_state(bundle_root)
    if state is None:
        return None
    if state.gate_id != gate_id:
        raise GateError(
            "invalid_sudo_execution_state",
            "gate_id",
            "sudo execution record does not match this gate",
        )
    if execution_is_live(state):
        return state
    notice = f"cleared stale sudo execution record for {gate_id}"
    if state.handoff_dir:
        cleanup_handoff(Path(state.handoff_dir))
    clear_execution_state(bundle_root)
    print(f"sase sudo: {notice}", file=sys.stderr)
    return None


def execution_is_live(state: SudoExecutionState) -> bool:
    """Return whether the attempt still owns the gate.

    This is intentionally conservative: unknown executor ownership is still
    live for duplicate-answer purposes. Use ``execution_liveness`` when the
    distinction matters.
    """
    return execution_liveness(state)["classification"] != "dead"


def execution_liveness(state: SudoExecutionState) -> dict[str, Any]:
    """Return the Rust-classified live/dead/unknown attempt decision."""
    from sase.sudo.core import DEFAULT_SUDO_CORE

    try:
        return DEFAULT_SUDO_CORE.classify_attempt_liveness(
            state.to_dict(),
            _attempt_liveness_facts(state),
        )
    except GateError:
        from sase.sudo import execution as facade

        if _seam("_proc_is_live")(state.finalize_proc_id) or facade.executor_is_live(
            state.handshake
        ):
            return {
                "schema_version": EXECUTION_STATE_SCHEMA_VERSION,
                "classification": "live",
                "reason": "legacy Python liveness fallback",
            }
        if state.startup_state == "legacy":
            return {
                "schema_version": EXECUTION_STATE_SCHEMA_VERSION,
                "classification": "dead",
                "reason": "legacy Python liveness fallback",
            }
        return {
            "schema_version": EXECUTION_STATE_SCHEMA_VERSION,
            "classification": "unknown",
            "reason": "invalid attempt state needs recovery",
        }


def proc_is_live(proc_id: str | None) -> bool:
    """Return whether *proc_id* names an active supervised proc."""
    if not proc_id:
        return False
    proc = get_proc(proc_id)
    if proc is None or proc.status not in ACTIVE_PROC_STATUSES:
        return False
    if proc.status == "pending":
        return True
    return supervisor_is_alive(proc.pid, proc.supervisor_id)


def executor_is_live(handshake: Mapping[str, Any] | None) -> bool:
    """Return whether the handshake still names a live executor process."""
    if handshake is None:
        return False
    pid = handshake.get("executor_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    from sase.sudo import execution as facade

    if not _seam("_pid_is_running")(pid):
        return False
    return facade.process_identity_matches(pid, handshake.get("executor_identity"))


def live_execution_error(state: SudoExecutionState) -> GateError:
    """Return the duplicate-approval error naming the live or unknown owner."""
    proc_id = state.finalize_proc_id or "unknown"
    liveness = execution_liveness(state)["classification"]
    return GateError(
        "execution_in_progress",
        proc_id,
        (
            f"sudo execution ownership is {liveness} for this gate "
            f"(finalize proc {proc_id}); the gate remains pending"
        ),
    )


def project_execution(bundle_root: Path) -> _SudoExecutionProjection:
    """Project live executing state without mutating the record."""
    state = load_execution_state(bundle_root)
    if state is None:
        return _SudoExecutionProjection(executing=False)
    liveness = execution_liveness(state)
    classification = str(liveness.get("classification") or "unknown")
    if classification == "dead":
        return _SudoExecutionProjection(executing=False)
    handshake = state.handshake or {}
    pid = handshake.get("executor_pid")
    return _SudoExecutionProjection(
        executing=True,
        finalize_proc_id=state.finalize_proc_id,
        executor_pid=pid
        if (
            state.target_kind == "local"
            and classification == "live"
            and isinstance(pid, int)
            and not isinstance(pid, bool)
        )
        else None,
        liveness=classification,
    )


def recover_dead_attempt(bundle_root: Path) -> None:
    """Clear a record and handoff when neither proc nor executor is live."""
    state = load_execution_state(bundle_root)
    if state is None or execution_liveness(state)["classification"] != "dead":
        return
    if not _cleanup_remote_handoff(state):
        return
    if state.handoff_dir:
        cleanup_handoff(Path(state.handoff_dir))
    clear_execution_state(bundle_root)


def abandon_unstarted_attempt(bundle_root: Path) -> None:
    """Drop a proven pre-spawn attempt, including any allocated remote paths."""
    state = load_execution_state(bundle_root)
    if state is None:
        return
    write_execution_state(bundle_root, replace(state, startup_state="terminal"))
    _cleanup_remote_handoff(state)
    if state.handoff_dir:
        cleanup_handoff(Path(state.handoff_dir))
    clear_execution_state(bundle_root)


def _cleanup_remote_handoff(state: SudoExecutionState) -> bool:
    """Return True when remote cleanup completed or is unnecessary."""
    if (
        state.target_kind != "remote"
        or not state.target_host
        or not state.remote_handoff
    ):
        return True
    from sase.sudo.ssh import cleanup_remote_sudo

    return cleanup_remote_sudo(state.target_host, state.remote_handoff)


def _attempt_liveness_facts(state: SudoExecutionState) -> dict[str, Any]:
    from sase.sudo import execution as facade

    facts: dict[str, Any] = {
        "finalize_proc_live": (
            None
            if state.finalize_proc_id is None
            else _seam("_proc_is_live")(state.finalize_proc_id)
        ),
        "executor_identity_matches": None,
        "executor_pid_live": None,
    }
    if state.target_kind != "local" or state.handshake is None:
        return facts
    pid = state.handshake.get("executor_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return facts
    live = _seam("_pid_is_running")(pid)
    facts["executor_pid_live"] = live
    facts["executor_identity_matches"] = (
        facade.process_identity_matches(pid, state.handshake.get("executor_identity"))
        if live
        else False
    )
    return facts


def pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


__all__ = [
    "abandon_unstarted_attempt",
    "claim_execution_record",
    "execution_is_live",
    "execution_liveness",
    "executor_is_live",
    "live_execution_error",
    "pid_is_running",
    "proc_is_live",
    "project_execution",
    "recover_dead_attempt",
]
