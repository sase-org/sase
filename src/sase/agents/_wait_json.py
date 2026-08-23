"""The JSON envelope for ``sase agent wait -j``."""

from __future__ import annotations

import json
from collections.abc import Mapping

from sase.agent.wait_watch import (
    WaitMemberState,
    WaitSettlement,
    WaitState,
    WaitTargetKind,
    WaitTargetState,
    is_blocked_state,
)

from ._wait_render_plain import WaitTargetKey, wait_state_label

_FAILED_MEMBER_STATES = frozenset({WaitState.FAILED, WaitState.TERMINAL_OTHER})


def wait_settlement_envelope(
    settlement: WaitSettlement,
    *,
    durations: Mapping[WaitTargetKey, float],
    exit_code: int,
) -> dict[str, object]:
    """Return the stable JSON envelope shape for a settled wait."""
    return {
        "settled": settlement.outcome.value,
        "exit_code": exit_code,
        "waited_seconds": round(settlement.elapsed_seconds, 1),
        "timed_out": settlement.outcome.value == "timeout",
        "targets": [
            _target_row(
                state,
                durations.get(state.target.key, settlement.elapsed_seconds),
            )
            for state in settlement.target_states
        ],
    }


def _target_row(state: WaitTargetState, duration_seconds: float) -> dict[str, object]:
    target = state.target
    row: dict[str, object] = {
        "name": target.name,
        "kind": target.kind.value,
        "project": target.project_name,
        "state": state.state.value,
        "status": wait_state_label(state.state),
        "duration_seconds": round(duration_seconds, 1),
        "artifacts_dir": target.artifact_dir,
    }
    if target.kind is WaitTargetKind.AGENT and state.members:
        member = state.members[0]
        row["outcome"] = member.outcome
        row["error"] = member.reason if state.failed else None
        row["blocked_reason"] = member.reason if state.blocked else None
    else:
        row["outcome"] = None
        row["error"] = state.reason if state.failed else None
        row["blocked_reason"] = state.reason if state.blocked else None
        row["members"] = [
            _member_row(member, duration_seconds) for member in state.members
        ]
    return row


def _member_row(member: WaitMemberState, duration_seconds: float) -> dict[str, object]:
    failed = member.state in _FAILED_MEMBER_STATES
    blocked = is_blocked_state(member.state)
    return {
        "name": member.name,
        "project": member.project_name,
        "state": member.state.value,
        "status": wait_state_label(member.state),
        "outcome": member.outcome,
        "duration_seconds": round(duration_seconds, 1),
        "artifacts_dir": member.artifact_dir,
        "error": member.reason if failed else None,
        "blocked_reason": member.reason if blocked else None,
    }


def print_wait_json(payload: dict[str, object]) -> None:
    """Write one JSON envelope to stdout."""
    print(json.dumps(payload, indent=2, sort_keys=True))


__all__ = [
    "print_wait_json",
    "wait_settlement_envelope",
]
