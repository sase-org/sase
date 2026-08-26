"""Handing a creator agent to the gate shell it just created."""

from __future__ import annotations

import os
from pathlib import Path

from sase.agent.pending_handoff import GATE_PENDING_MARKER
from sase.gate_shell.models import GateShellError, GateShellRecord
from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.transaction import GateShellCreation, restore_creation_claim
from sase.notification_gates.executor import cancel_gate
from sase.shells.handoff import (
    ShellHandoffError,
    maybe_handoff_shell_from_agent,
    will_handoff_shell_to_agent_runner,
    write_shell_pending_marker,
)


def will_handoff_gate_to_agent_runner() -> bool:
    """Return whether ``maybe_handoff_gate_from_agent`` will kill this runner.

    ``kill_agent_runner_group()`` is ``NoReturn``, so any output a caller
    wants to show (a creation descriptor, JSON envelope, or summary) must be
    emitted *before* calling ``maybe_handoff_gate_from_agent`` -- not after,
    and not conditioned on its return value, which the process never lives to
    observe when this is true.
    """
    return will_handoff_shell_to_agent_runner(os.environ)


def maybe_handoff_gate_from_agent(
    creation: GateShellCreation | GateShellRecord,
    *,
    artifacts_dir: str | None = None,
) -> bool:
    """Write the in-agent gate handoff marker and kill this runner."""
    record = creation.record if isinstance(creation, GateShellCreation) else creation
    if record.is_terminal:
        return False
    try:
        return maybe_handoff_shell_from_agent(
            marker_name=GATE_PENDING_MARKER,
            marker_data=_gate_pending_payload(record),
            artifacts_dir=artifacts_dir,
            env=os.environ,
        )
    except ShellHandoffError as exc:
        if isinstance(creation, GateShellCreation):
            _compensate_failed_handoff(creation, str(exc))
        raise GateShellError(str(exc).replace("shell", "gate shell")) from exc


def _compensate_failed_handoff(creation: GateShellCreation, error: str) -> None:
    try:
        cancel_gate(
            creation.gate.bundle_path,
            reason="handoff_failed",
            source="gate_shell",
        )
    except Exception:
        pass
    restore_creation_claim(creation)
    settle_gate_shell(
        creation.record,
        gate_state="stopped",
        reason=f"handoff marker failed: {error}",
    )


def _gate_pending_payload(record: GateShellRecord) -> dict[str, str]:
    return {
        "gate_id": record.gate_id,
        "member_artifacts_dir": record.artifacts_dir,
        "member_agent_name": record.member_agent_name,
        "kind": record.kind,
    }


__all__ = [
    "GATE_PENDING_MARKER",
    "maybe_handoff_gate_from_agent",
    "will_handoff_gate_to_agent_runner",
]
