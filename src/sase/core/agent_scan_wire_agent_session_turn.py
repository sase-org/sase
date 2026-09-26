"""One nested ``agent_session_turn`` wire record folding the flat monitor/gate blocks.

Split out of :mod:`sase.core.agent_scan_wire_markers` to keep each module
under the 500-line cap. Before wire schema v7, ``AgentMetaWire`` and
``DoneMarkerWire`` each carried two flat, mutually exclusive field blocks —
``monitor_*`` and ``gate_*`` — mirroring the two agent-session-turn kinds a
durable agent-session member can be. This module folds both blocks into one
``AgentSessionTurnWire`` record: a ``kind`` discriminator, the fields both turn
kinds share, and a kind-specific sub-block (``monitor`` or ``gate``, never
both).

:func:`agent_session_turn_from_mapping` is the compatibility projection: it reads
either shape and always returns the current, nested representation. On-disk
marker files (``agent_meta.json`` / ``done.json``) still carry the flat
``monitor_*`` / ``gate_*`` keys — many writers depend on that shape and this
module does not change it — so the two direct on-disk readers
(``sase.gate_turn.store`` and ``sase.monitor.store``) and the wire's own
JSON conversion helpers all route through this one function instead of each
re-deriving the flat-to-nested projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.plan_chain import agent_session_role_value, agent_session_turn_value

#: Role recorded in ``agent_meta.json::agent_session_role`` for a monitor
#: agent-session member. Mirrors ``sase.monitor_state.MONITOR_AGENT_SESSION_ROLE``; not
#: imported directly to avoid a dependency cycle with this low-level module.
_MONITOR_AGENT_SESSION_ROLE = "monitor"

#: Mirrors ``sase.gate_turn.state.GATE_AGENT_SESSION_ROLE`` (see above).
_GATE_AGENT_SESSION_ROLE = "gate"


@dataclass(frozen=True)
class AgentSessionTurnMonitorWire:
    """Monitor-only fields of a ``agent_session_turn`` record."""

    command: str | None = None
    cwd: str | None = None
    exit_code: int | None = None
    starter_agent: str | None = None
    tail_lines: int | None = None
    pgid: int | None = None
    supervisor_identity: str | None = None
    settled: bool = False
    idle_timeout_seconds: float | None = None
    tool_run_id: str | None = None


@dataclass(frozen=True)
class AgentSessionTurnGateWire:
    """Gate-only fields of a ``agent_session_turn`` record.

    ``kind`` here is the gate's own flavor (e.g. ``"approval"``), not the
    ``AgentSessionTurnWire.kind`` discriminator.
    """

    kind: str | None = None
    accent: str | None = None
    creator_agent: str | None = None
    next_fork: str | None = None
    next_suffix: str | None = None
    next_role: str | None = None
    next_raw_prompt: bool = False
    workspace_policy: str | None = None
    bundle_path: str | None = None
    notification_id: str | None = None
    decision_path: str | None = None
    claim_holder_pid: int | None = None


@dataclass(frozen=True)
class AgentSessionTurnWire:
    """One durable agent-session-turn member: a monitor or a gate, never both.

    ``kind`` discriminates ``"monitor"`` / ``"gate"``. The fields below
    ``kind`` are the ones both turns carry (mirroring the two flat
    ``monitor_*`` / ``gate_*`` prefixes they replace); ``monitor`` / ``gate``
    hold whichever kind's own fields, with the other left ``None``.
    """

    kind: str
    id: str | None = None
    state: str | None = None
    label: str | None = None
    reason: str | None = None
    start_status: str | None = None
    stop_status: str | None = None
    timeout_seconds: float | None = None
    elapsed_seconds: float | None = None
    output_path: str | None = None
    output_truncated: bool = False
    request_fingerprint: str | None = None
    next_action: str | None = None
    next_output: str | None = None
    next_model: str | None = None
    completion_ref: str | None = None
    profile: str | None = None
    policy_digest: str | None = None
    followup_agent: str | None = None
    followup_outcome: str | None = None
    followup_error: str | None = None
    followup_degraded_reason: str | None = None
    followup_prompt_path: str | None = None
    followup_attempt_id: str | None = None
    followup_attempt_fingerprint: str | None = None
    followup_attempt_stage: str | None = None
    followup_error_stage: str | None = None
    followup_error_type: str | None = None
    host_completion_status: str | None = None
    host_completion_message: str | None = None
    host_completion_reason: str | None = None
    monitor: AgentSessionTurnMonitorWire | None = None
    gate: AgentSessionTurnGateWire | None = None


# Old flat key -> new nested field name, for the fields both turn kinds
# share.
_MONITOR_SHARED_KEYS: dict[str, str] = {
    "monitor_id": "id",
    "monitor_state": "state",
    "monitor_label": "label",
    "monitor_reason": "reason",
    "monitor_start_status": "start_status",
    "monitor_stop_status": "stop_status",
    "monitor_timeout_seconds": "timeout_seconds",
    "monitor_elapsed_seconds": "elapsed_seconds",
    "monitor_output_path": "output_path",
    "monitor_output_truncated": "output_truncated",
    "monitor_request_fingerprint": "request_fingerprint",
    "monitor_next_action": "next_action",
    "monitor_next_output": "next_output",
    "monitor_next_model": "next_model",
    "monitor_completion_ref": "completion_ref",
    "monitor_profile": "profile",
    "monitor_policy_digest": "policy_digest",
    "monitor_followup_agent": "followup_agent",
    "monitor_followup_outcome": "followup_outcome",
    "monitor_followup_error": "followup_error",
    "monitor_followup_degraded_reason": "followup_degraded_reason",
    "monitor_followup_prompt_path": "followup_prompt_path",
    "monitor_followup_attempt_id": "followup_attempt_id",
    "monitor_followup_attempt_fingerprint": "followup_attempt_fingerprint",
    "monitor_followup_attempt_stage": "followup_attempt_stage",
    "monitor_followup_error_stage": "followup_error_stage",
    "monitor_followup_error_type": "followup_error_type",
    "monitor_host_completion_status": "host_completion_status",
    "monitor_host_completion_message": "host_completion_message",
    "monitor_host_completion_reason": "host_completion_reason",
}

_MONITOR_SPECIFIC_KEYS: dict[str, str] = {
    "monitor_command": "command",
    "monitor_cwd": "cwd",
    "monitor_exit_code": "exit_code",
    "monitor_starter_agent": "starter_agent",
    "monitor_tail_lines": "tail_lines",
    "monitor_pgid": "pgid",
    "monitor_supervisor_identity": "supervisor_identity",
    "monitor_settled": "settled",
    "monitor_idle_timeout_seconds": "idle_timeout_seconds",
    "monitor_tool_run_id": "tool_run_id",
}

_GATE_SHARED_KEYS: dict[str, str] = {
    "gate_id": "id",
    "gate_state": "state",
    "gate_label": "label",
    "gate_reason": "reason",
    "gate_start_status": "start_status",
    "gate_stop_status": "stop_status",
    "gate_timeout_seconds": "timeout_seconds",
    "gate_elapsed_seconds": "elapsed_seconds",
    "gate_output_path": "output_path",
    "gate_output_truncated": "output_truncated",
    "gate_request_fingerprint": "request_fingerprint",
    "gate_next_action": "next_action",
    "gate_next_output": "next_output",
    "gate_next_model": "next_model",
    "gate_followup_agent": "followup_agent",
    "gate_followup_outcome": "followup_outcome",
    "gate_followup_error": "followup_error",
    "gate_followup_degraded_reason": "followup_degraded_reason",
    "gate_followup_prompt_path": "followup_prompt_path",
    "gate_followup_attempt_id": "followup_attempt_id",
    "gate_followup_attempt_fingerprint": "followup_attempt_fingerprint",
    "gate_followup_attempt_stage": "followup_attempt_stage",
    "gate_followup_error_stage": "followup_error_stage",
    "gate_followup_error_type": "followup_error_type",
}

_GATE_SPECIFIC_KEYS: dict[str, str] = {
    "gate_kind": "kind",
    "gate_accent": "accent",
    "gate_creator_agent": "creator_agent",
    "gate_next_fork": "next_fork",
    "gate_next_suffix": "next_suffix",
    "gate_next_role": "next_role",
    "gate_next_raw_prompt": "next_raw_prompt",
    "gate_workspace_policy": "workspace_policy",
    "gate_bundle_path": "bundle_path",
    "gate_notification_id": "notification_id",
    "gate_decision_path": "decision_path",
    "gate_claim_holder_pid": "claim_holder_pid",
}

_MONITOR_FLAT_KEYS = frozenset(_MONITOR_SHARED_KEYS) | frozenset(_MONITOR_SPECIFIC_KEYS)
_GATE_FLAT_KEYS = frozenset(_GATE_SHARED_KEYS) | frozenset(_GATE_SPECIFIC_KEYS)


def _project(data: Mapping[str, Any], key_map: dict[str, str]) -> dict[str, Any]:
    return {new: data[old] for old, new in key_map.items() if old in data}


def _has_any_key(data: Mapping[str, Any], keys: frozenset[str]) -> bool:
    if isinstance(data, dict):
        return not data.keys().isdisjoint(keys)
    return any(key in data for key in keys)


def _agent_session_turn_from_flat_keys(
    data: Mapping[str, Any],
) -> AgentSessionTurnWire | None:
    """Build an ``AgentSessionTurnWire`` from flat legacy ``monitor_*`` / ``gate_*`` keys."""
    has_monitor = _has_any_key(data, _MONITOR_FLAT_KEYS)
    has_gate = _has_any_key(data, _GATE_FLAT_KEYS)
    if has_monitor and has_gate:
        # An agent session turn is either a monitor or a gate, never both,
        # because the two are independent inheritance chains keyed off
        # different launch mechanisms; this branch should be unreachable
        # in practice. Fall back to the recorded role rather than silently
        # dropping one side.
        has_monitor = agent_session_role_value(data) != _GATE_AGENT_SESSION_ROLE
        has_gate = not has_monitor
    if has_monitor:
        return AgentSessionTurnWire(
            kind=_MONITOR_AGENT_SESSION_ROLE,
            monitor=AgentSessionTurnMonitorWire(
                **_project(data, _MONITOR_SPECIFIC_KEYS)
            ),
            **_project(data, _MONITOR_SHARED_KEYS),
        )
    if has_gate:
        return AgentSessionTurnWire(
            kind=_GATE_AGENT_SESSION_ROLE,
            gate=AgentSessionTurnGateWire(**_project(data, _GATE_SPECIFIC_KEYS)),
            **_project(data, _GATE_SHARED_KEYS),
        )
    return None


def _agent_session_turn_from_nested_dict(
    data: Mapping[str, Any],
) -> AgentSessionTurnWire | None:
    kind = data.get("kind")
    if kind not in (_MONITOR_AGENT_SESSION_ROLE, _GATE_AGENT_SESSION_ROLE):
        return None
    shared = {
        key: data[key]
        for key in AgentSessionTurnWire.__dataclass_fields__
        if key in data and key not in ("kind", "monitor", "gate")
    }
    monitor_data = data.get("monitor")
    gate_data = data.get("gate")
    monitor = (
        AgentSessionTurnMonitorWire(
            **{
                key: monitor_data[key]
                for key in AgentSessionTurnMonitorWire.__dataclass_fields__
                if key in monitor_data
            }
        )
        if isinstance(monitor_data, dict)
        else None
    )
    gate = (
        AgentSessionTurnGateWire(
            **{
                key: gate_data[key]
                for key in AgentSessionTurnGateWire.__dataclass_fields__
                if key in gate_data
            }
        )
        if isinstance(gate_data, dict)
        else None
    )
    return AgentSessionTurnWire(kind=kind, monitor=monitor, gate=gate, **shared)


def agent_session_turn_from_mapping(
    data: Mapping[str, Any],
) -> AgentSessionTurnWire | None:
    """Return the ``AgentSessionTurnWire`` *data* describes, or ``None``.

    Reads either shape: the current nested wire shape (an ``agent_session_turn``
    key holding a dict, as produced by ``agent_scan_wire_to_json_dict`` and
    by the Rust scanner), the legacy pre-rename shell keys, or the flat
    legacy ``monitor_*`` / ``gate_*`` keys still written to
    ``agent_meta.json`` / ``done.json`` on disk. Core still emits legacy
    spellings until the contract flip, so both are hydrated here.
    """
    nested = agent_session_turn_value(data)
    if isinstance(nested, dict):
        return _agent_session_turn_from_nested_dict(nested)
    return _agent_session_turn_from_flat_keys(data)


__all__ = [
    "AgentSessionTurnGateWire",
    "AgentSessionTurnMonitorWire",
    "AgentSessionTurnWire",
    "agent_session_turn_from_mapping",
]
