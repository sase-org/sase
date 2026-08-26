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
        if meta is None or not meta.gate_id:
            raise ValueError(
                f"artifact record at {record.artifact_dir!r} is not a gate member"
            )
        pair = gate_status_pair(meta.gate_start_status, meta.gate_stop_status)
        state = meta.gate_state or "pending"
        return cls(
            gate_id=meta.gate_id,
            member_agent_name=meta.name or "",
            lane=meta.agent_family or "",
            project_name=record.project_name,
            artifacts_dir=record.artifact_dir,
            timestamp=record.timestamp,
            kind=meta.gate_kind or "",
            gate_state=state,  # type: ignore[arg-type]
            start_status=pair.start,
            stop_status=pair.stop,
            accent=meta.gate_accent or "#0BCDEC",
            label=meta.gate_label or meta.gate_kind or meta.gate_id,
            reason=meta.gate_reason or "",
            creator_agent=meta.gate_creator_agent,
            bundle_path=meta.gate_bundle_path,
            notification_id=meta.gate_notification_id,
            timeout_seconds=meta.gate_timeout_seconds or 0.0,
            request_fingerprint=meta.gate_request_fingerprint,
            workspace_policy=meta.gate_workspace_policy or "inherit",
            next_action=meta.gate_next_action,
            next_fork=meta.gate_next_fork,
            next_output=meta.gate_next_output,
            next_model=meta.gate_next_model,
            followup_agent=meta.gate_followup_agent,
            followup_outcome=meta.gate_followup_outcome,
            followup_error=meta.gate_followup_error,
            followup_degraded_reason=meta.gate_followup_degraded_reason,
            followup_prompt_path=meta.gate_followup_prompt_path,
        )


def is_gate_shell_member_record(record: AgentArtifactRecordWire) -> bool:
    """Return whether ``record`` is a real gate-shell family member."""
    meta = record.agent_meta
    return meta is not None and is_real_gate_member(
        meta.agent_family_role, meta.gate_id
    )


__all__ = [
    "GateShellError",
    "GateShellLaneError",
    "GateShellRecord",
    "GateShellState",
    "is_gate_shell_member_record",
]
