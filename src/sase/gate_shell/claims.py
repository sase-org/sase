"""The gate-shell workspace-claim label, and when such a claim is really stale.

Kept import-light on purpose: the ACE agent loader consults this on every
refresh that sees a dead-PID claim, so the artifact-path and marker-store
helpers are imported inside the function that needs them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

GATE_WORKSPACE_CLAIM_WORKFLOW = "ace-gate"


class _GateWorkspaceClaim(Protocol):
    """The part of a RUNNING-field claim the releasability rule reads."""

    @property
    def artifacts_timestamp(self) -> str | None: ...


def gate_claim_is_releasable(project_file: str, claim: _GateWorkspaceClaim) -> bool:
    """Return whether a dead-PID gate-shell claim is safe to release.

    Pending gate shells intentionally keep the creator's old PID in the
    RUNNING row after the creator is killed, so a dead PID is never on its
    own evidence that the workspace is free. Only release once the owning
    gate-shell member's own markers say it is terminal; read failures fail
    closed. Every sweep that reaps claims by PID liveness must ask here
    first, or the gate's own settlement finds its workspace gone.
    """
    if not claim.artifacts_timestamp:
        return False
    try:
        from sase.core.agent_artifact_paths import (
            ACE_RUN_WORKFLOW_DIR,
            resolve_agent_artifact_timestamp_path,
        )
        from sase.gate_shell.store import read_gate_shell_marker

        project_name = Path(project_file).parent.name
        artifacts_dir = resolve_agent_artifact_timestamp_path(
            project_name, ACE_RUN_WORKFLOW_DIR, claim.artifacts_timestamp
        )
        record = read_gate_shell_marker(project_name, str(artifacts_dir))
    except Exception:
        return False
    return record is not None and record.is_terminal


__all__ = ["GATE_WORKSPACE_CLAIM_WORKFLOW", "gate_claim_is_releasable"]
