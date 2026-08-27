"""Typed gate-shell records projected from agent artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sase.gate_shell.state import (
    gate_state_bucket,
    gate_state_is_terminal,
    is_real_gate_member,
)
from sase.gate_shell.status import gate_status_pair

if TYPE_CHECKING:
    from sase.core.agent_scan_wire import AgentArtifactRecordWire

GateShellState = Literal[
    "pending",
    "settling",
    "answered",
    "completed",
    "failed",
    "timeout",
    "stopped",
    "lost",
]


class GateShellError(RuntimeError):
    """Base class for gate-shell lifecycle failures."""


class GateShellLaneError(GateShellError):
    """A gate shell's lane could not be resolved."""


class GateShellRefError(ValueError):
    """A gate-shell reference was empty, unknown, or ambiguous."""


@dataclass(frozen=True)
class GateShellRecord:
    """Projection of one gate-shell family member."""

    gate_id: str
    member_agent_name: str
    lane: str
    project_name: str
    artifacts_dir: str
    timestamp: str
    kind: str
    gate_state: GateShellState
    start_status: str
    stop_status: str
    accent: str
    label: str
    reason: str
    creator_agent: str | None
    bundle_path: str | None
    notification_id: str | None
    timeout_seconds: float
    request_fingerprint: str | None
    workspace_policy: str
    next_action: str | None = None
    next_fork: str | None = None
    next_output: str | None = None
    next_model: str | None = None
    next_suffix: str | None = None
    next_role: str | None = None
    next_raw_prompt: bool = False
    followup_agent: str | None = None
    followup_outcome: str | None = None
    followup_error: str | None = None
    followup_degraded_reason: str | None = None
    followup_prompt_path: str | None = None

    @property
    def status_bucket(self) -> str:
        """Return this gate shell's display status bucket."""
        return gate_state_bucket(self.gate_state)

    @property
    def is_terminal(self) -> bool:
        """Return whether this gate shell has settled terminally."""
        return gate_state_is_terminal(self.gate_state)

    @classmethod
    def from_record(cls, record: AgentArtifactRecordWire) -> GateShellRecord:
        """Build a gate-shell record from an agent-artifact scan row."""
        meta = record.agent_meta
        shell = meta.family_shell if meta is not None else None
        if meta is None or shell is None or shell.kind != "gate" or not shell.id:
            raise ValueError(
                f"artifact record at {record.artifact_dir!r} is not a gate member"
            )
        gate = shell.gate
        pair = gate_status_pair(shell.start_status, shell.stop_status)
        state = shell.state or "pending"
        gate_kind = gate.kind if gate is not None else None
        return cls(
            gate_id=shell.id,
            member_agent_name=meta.name or "",
            lane=meta.agent_family or "",
            project_name=record.project_name,
            artifacts_dir=record.artifact_dir,
            timestamp=record.timestamp,
            kind=gate_kind or "",
            gate_state=state,  # type: ignore[arg-type]
            start_status=pair.start,
            stop_status=pair.stop,
            accent=(gate.accent if gate is not None else None) or "#0BCDEC",
            label=shell.label or gate_kind or shell.id,
            reason=shell.reason or "",
            creator_agent=gate.creator_agent if gate is not None else None,
            bundle_path=gate.bundle_path if gate is not None else None,
            notification_id=gate.notification_id if gate is not None else None,
            timeout_seconds=shell.timeout_seconds or 0.0,
            request_fingerprint=shell.request_fingerprint,
            workspace_policy=(
                (gate.workspace_policy if gate is not None else None) or "inherit"
            ),
            next_action=shell.next_action,
            next_fork=gate.next_fork if gate is not None else None,
            next_output=shell.next_output,
            next_model=shell.next_model,
            next_suffix=gate.next_suffix if gate is not None else None,
            next_role=gate.next_role if gate is not None else None,
            next_raw_prompt=bool(gate.next_raw_prompt) if gate is not None else False,
            followup_agent=shell.followup_agent,
            followup_outcome=shell.followup_outcome,
            followup_error=shell.followup_error,
            followup_degraded_reason=shell.followup_degraded_reason,
            followup_prompt_path=shell.followup_prompt_path,
        )


def is_gate_shell_member_record(record: AgentArtifactRecordWire) -> bool:
    """Return whether ``record`` is a real gate-shell family member."""
    meta = record.agent_meta
    if meta is None:
        return False
    shell = meta.family_shell
    gate_id = shell.id if shell is not None and shell.kind == "gate" else None
    return is_real_gate_member(meta.agent_family_role, gate_id)


__all__ = [
    "GateShellError",
    "GateShellLaneError",
    "GateShellRecord",
    "GateShellRefError",
    "GateShellState",
    "is_gate_shell_member_record",
]
