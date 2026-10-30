"""Wire records for the Rust-backed published agent-run state policy.

Mirrors ``sase_core::agent_run_state::wire``. Every object carries
``schema_version``; :func:`agent_run_state_wire_schema_version` must match
``AGENT_RUN_STATE_WIRE_SCHEMA_VERSION`` in core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AGENT_RUN_STATE_WIRE_SCHEMA_VERSION = 1

AGENT_RUN_STATE_WINDOW_MIN_LIMIT = 1
AGENT_RUN_STATE_WINDOW_MAX_LIMIT = 500
AGENT_RUN_STATE_BACKOFF_BASE_MS = 60_000
AGENT_RUN_STATE_BACKOFF_MAX_MS = 3_600_000

AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER = "terminal_marker"
AGENT_RUN_STATE_EVIDENCE_DISMISSED = "dismissed"
AGENT_RUN_STATE_EVIDENCE_UNFINISHED = "unfinished"
AGENT_RUN_STATE_EVIDENCE_MISSING = "missing"
AGENT_RUN_STATE_EVIDENCE_IDENTITY_CONFLICT = "identity_conflict"
AGENT_RUN_STATE_EVIDENCE_MALFORMED = "malformed"

AGENT_RUN_STATE_REASON_UPDATED_TERMINAL_MARKER = "updated_from_terminal_marker"
AGENT_RUN_STATE_REASON_UPDATED_DISMISSED = "updated_from_dismissed"
AGENT_RUN_STATE_REASON_PRESERVED_TERMINAL = "preserved_terminal_state"
AGENT_RUN_STATE_REASON_UNCHANGED = "unchanged_current"
AGENT_RUN_STATE_REASON_LIVE_EVIDENCE = "live_evidence"
AGENT_RUN_STATE_REASON_MISSING_EVIDENCE = "missing_evidence"
AGENT_RUN_STATE_REASON_MALFORMED_EVIDENCE = "malformed_evidence"
AGENT_RUN_STATE_REASON_IDENTITY_CONFLICT = "identity_conflict"
AGENT_RUN_STATE_REASON_CONFLICTING_TERMINAL = "conflicting_terminal_evidence"
AGENT_RUN_STATE_REASON_LATER_DISMISSAL = "verified_later_dismissal"

AGENT_RUN_STATE_OUTCOME_SUCCESS = "success"
AGENT_RUN_STATE_OUTCOME_FAILURE = "failure"

ACTIVE_RUN_STATES = ("active", "waiting")
TERMINAL_RUN_STATES = ("completed", "failed", "stopped", "dismissed")


def _check_schema(data: dict[str, Any], *, what: str) -> int:
    schema_version = int(data.get("schema_version", 0))
    if schema_version != AGENT_RUN_STATE_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs agent run state wire is stale: "
            f"expected schema {AGENT_RUN_STATE_WIRE_SCHEMA_VERSION}, "
            f"got {schema_version} for {what}"
        )
    return schema_version


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True)
class AgentRunIdentityWire:
    """Canonical identity of one immutable agent run."""

    project: str = ""
    owner: str = ""
    global_name: str = ""
    source_run_id: str = ""


@dataclass(frozen=True)
class AgentRunStateResolveRequestWire:
    """Request to resolve published state against local evidence."""

    identity: AgentRunIdentityWire = field(default_factory=AgentRunIdentityWire)
    published_state: str = ""
    published_started_at: str | None = None
    published_finished_at: str | None = None
    evidence_kind: str = ""
    evidence_identity: AgentRunIdentityWire | None = None
    evidence_state: str | None = None
    evidence_started_at: str | None = None
    evidence_finished_at: str | None = None
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


@dataclass(frozen=True)
class AgentRunStateResolveResponseWire:
    """Resolved state selection for one published run."""

    selected_state: str = ""
    selected_started_at: str | None = None
    selected_finished_at: str | None = None
    changed: bool = False
    reason: str = ""
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


@dataclass(frozen=True)
class AgentRunStateWindowRowWire:
    """One candidate published run ordered by (local_hood, source_run_id)."""

    local_hood: str = ""
    source_run_id: str = ""


@dataclass(frozen=True)
class AgentRunStateWindowRequestWire:
    """Request to select a deterministic bounded window of published runs."""

    project: str = ""
    owner: str = ""
    limit: int = 100
    after: str | None = None
    rows: tuple[AgentRunStateWindowRowWire, ...] = ()
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


@dataclass(frozen=True)
class AgentRunStateWindowResponseWire:
    """Selected window plus the cursor resuming after the last examined row."""

    selected: tuple[AgentRunStateWindowRowWire, ...] = ()
    next_cursor: str | None = None
    pass_complete: bool = False
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


@dataclass(frozen=True)
class AgentRunStateProjectIdentityWire:
    """Project plus owner identity for scheduled convergence."""

    project: str = ""
    owner: str = ""


@dataclass(frozen=True)
class AgentRunStateProjectWire:
    """One schedulable project with its checkpoint and retry state."""

    identity: AgentRunStateProjectIdentityWire = field(
        default_factory=AgentRunStateProjectIdentityWire
    )
    enabled: bool = False
    configured: bool = False
    cursor: str | None = None
    failure_count: int = 0
    retry_after_ms: int = 0


@dataclass(frozen=True)
class AgentRunStateScheduleOutcomeWire:
    """Outcome of the window just processed for one project."""

    identity: AgentRunStateProjectIdentityWire = field(
        default_factory=AgentRunStateProjectIdentityWire
    )
    result: str = ""
    next_cursor: str | None = None
    pass_complete: bool = False


@dataclass(frozen=True)
class AgentRunStateScheduleRequestWire:
    """Request to choose the next eligible project and checkpoint transition."""

    now_ms: int = 0
    last_selected: AgentRunStateProjectIdentityWire | None = None
    projects: tuple[AgentRunStateProjectWire, ...] = ()
    outcome: AgentRunStateScheduleOutcomeWire | None = None
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


@dataclass(frozen=True)
class AgentRunStateProjectCheckpointWire:
    """Durable per-project cursor plus bounded retry backoff."""

    identity: AgentRunStateProjectIdentityWire = field(
        default_factory=AgentRunStateProjectIdentityWire
    )
    cursor: str | None = None
    failure_count: int = 0
    retry_after_ms: int = 0


@dataclass(frozen=True)
class AgentRunStateScheduleResponseWire:
    """Next eligible project plus the checkpoint to persist."""

    next_project: AgentRunStateProjectIdentityWire | None = None
    updated_checkpoint: AgentRunStateProjectCheckpointWire | None = None
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


def _agent_run_identity_to_dict(identity: AgentRunIdentityWire) -> dict[str, Any]:
    """Serialize an agent-run identity to its wire dict shape."""
    return {
        "project": identity.project,
        "owner": identity.owner,
        "global_name": identity.global_name,
        "source_run_id": identity.source_run_id,
    }


def agent_run_state_resolve_request_to_dict(
    request: AgentRunStateResolveRequestWire,
) -> dict[str, Any]:
    """Serialize a resolve request to the ``sase_core_rs`` dict shape."""
    return {
        "schema_version": request.schema_version,
        "identity": _agent_run_identity_to_dict(request.identity),
        "published_state": request.published_state,
        "published_started_at": request.published_started_at,
        "published_finished_at": request.published_finished_at,
        "evidence_kind": request.evidence_kind,
        "evidence_identity": (
            None
            if request.evidence_identity is None
            else _agent_run_identity_to_dict(request.evidence_identity)
        ),
        "evidence_state": request.evidence_state,
        "evidence_started_at": request.evidence_started_at,
        "evidence_finished_at": request.evidence_finished_at,
    }


def agent_run_state_resolve_response_from_dict(
    data: dict[str, Any],
) -> AgentRunStateResolveResponseWire:
    """Rehydrate a resolve response from the PyO3 dict shape."""
    _check_schema(data, what="AgentRunStateResolveResponseWire")
    return AgentRunStateResolveResponseWire(
        schema_version=int(data["schema_version"]),
        selected_state=str(data.get("selected_state", "")),
        selected_started_at=_opt_str(data.get("selected_started_at")),
        selected_finished_at=_opt_str(data.get("selected_finished_at")),
        changed=bool(data.get("changed", False)),
        reason=str(data.get("reason", "")),
    )


def agent_run_state_window_request_to_dict(
    request: AgentRunStateWindowRequestWire,
) -> dict[str, Any]:
    """Serialize a window request to the ``sase_core_rs`` dict shape."""
    return {
        "schema_version": request.schema_version,
        "project": request.project,
        "owner": request.owner,
        "limit": request.limit,
        "after": request.after,
        "rows": [
            {"local_hood": row.local_hood, "source_run_id": row.source_run_id}
            for row in request.rows
        ],
    }


def agent_run_state_window_response_from_dict(
    data: dict[str, Any],
) -> AgentRunStateWindowResponseWire:
    """Rehydrate a window response from the PyO3 dict shape."""
    _check_schema(data, what="AgentRunStateWindowResponseWire")
    selected: list[AgentRunStateWindowRowWire] = []
    for entry in data.get("selected") or []:
        if isinstance(entry, dict):
            selected.append(
                AgentRunStateWindowRowWire(
                    local_hood=str(entry.get("local_hood", "")),
                    source_run_id=str(entry.get("source_run_id", "")),
                )
            )
    return AgentRunStateWindowResponseWire(
        schema_version=int(data["schema_version"]),
        selected=tuple(selected),
        next_cursor=_opt_str(data.get("next_cursor")),
        pass_complete=bool(data.get("pass_complete", False)),
    )


def _project_identity_to_dict(
    identity: AgentRunStateProjectIdentityWire,
) -> dict[str, Any]:
    return {"project": identity.project, "owner": identity.owner}


def _project_identity_from_dict(
    data: dict[str, Any],
) -> AgentRunStateProjectIdentityWire:
    return AgentRunStateProjectIdentityWire(
        project=str(data.get("project", "")),
        owner=str(data.get("owner", "")),
    )


def agent_run_state_schedule_request_to_dict(
    request: AgentRunStateScheduleRequestWire,
) -> dict[str, Any]:
    """Serialize a schedule request to the ``sase_core_rs`` dict shape."""
    return {
        "schema_version": request.schema_version,
        "now_ms": request.now_ms,
        "last_selected": (
            None
            if request.last_selected is None
            else _project_identity_to_dict(request.last_selected)
        ),
        "projects": [
            {
                "identity": _project_identity_to_dict(item.identity),
                "enabled": item.enabled,
                "configured": item.configured,
                "cursor": item.cursor,
                "failure_count": item.failure_count,
                "retry_after_ms": item.retry_after_ms,
            }
            for item in request.projects
        ],
        "outcome": (
            None
            if request.outcome is None
            else {
                "identity": _project_identity_to_dict(request.outcome.identity),
                "result": request.outcome.result,
                "next_cursor": request.outcome.next_cursor,
                "pass_complete": request.outcome.pass_complete,
            }
        ),
    }


def agent_run_state_schedule_response_from_dict(
    data: dict[str, Any],
) -> AgentRunStateScheduleResponseWire:
    """Rehydrate a schedule response from the PyO3 dict shape."""
    _check_schema(data, what="AgentRunStateScheduleResponseWire")
    next_project = data.get("next_project")
    checkpoint = data.get("updated_checkpoint")
    return AgentRunStateScheduleResponseWire(
        schema_version=int(data["schema_version"]),
        next_project=(
            None if next_project is None else _project_identity_from_dict(next_project)
        ),
        updated_checkpoint=(
            None
            if checkpoint is None
            else AgentRunStateProjectCheckpointWire(
                identity=_project_identity_from_dict(checkpoint.get("identity", {})),
                cursor=_opt_str(checkpoint.get("cursor")),
                failure_count=int(checkpoint.get("failure_count", 0)),
                retry_after_ms=int(checkpoint.get("retry_after_ms", 0)),
            )
        ),
    )


__all__ = [
    "ACTIVE_RUN_STATES",
    "AGENT_RUN_STATE_BACKOFF_BASE_MS",
    "AGENT_RUN_STATE_BACKOFF_MAX_MS",
    "AGENT_RUN_STATE_EVIDENCE_DISMISSED",
    "AGENT_RUN_STATE_EVIDENCE_IDENTITY_CONFLICT",
    "AGENT_RUN_STATE_EVIDENCE_MALFORMED",
    "AGENT_RUN_STATE_EVIDENCE_MISSING",
    "AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER",
    "AGENT_RUN_STATE_EVIDENCE_UNFINISHED",
    "AGENT_RUN_STATE_OUTCOME_FAILURE",
    "AGENT_RUN_STATE_OUTCOME_SUCCESS",
    "AGENT_RUN_STATE_REASON_CONFLICTING_TERMINAL",
    "AGENT_RUN_STATE_REASON_IDENTITY_CONFLICT",
    "AGENT_RUN_STATE_REASON_LATER_DISMISSAL",
    "AGENT_RUN_STATE_REASON_LIVE_EVIDENCE",
    "AGENT_RUN_STATE_REASON_MALFORMED_EVIDENCE",
    "AGENT_RUN_STATE_REASON_MISSING_EVIDENCE",
    "AGENT_RUN_STATE_REASON_PRESERVED_TERMINAL",
    "AGENT_RUN_STATE_REASON_UNCHANGED",
    "AGENT_RUN_STATE_REASON_UPDATED_DISMISSED",
    "AGENT_RUN_STATE_REASON_UPDATED_TERMINAL_MARKER",
    "AGENT_RUN_STATE_WINDOW_MAX_LIMIT",
    "AGENT_RUN_STATE_WINDOW_MIN_LIMIT",
    "AGENT_RUN_STATE_WIRE_SCHEMA_VERSION",
    "TERMINAL_RUN_STATES",
    "AgentRunIdentityWire",
    "AgentRunStateProjectCheckpointWire",
    "AgentRunStateProjectIdentityWire",
    "AgentRunStateProjectWire",
    "AgentRunStateResolveRequestWire",
    "AgentRunStateResolveResponseWire",
    "AgentRunStateScheduleOutcomeWire",
    "AgentRunStateScheduleRequestWire",
    "AgentRunStateScheduleResponseWire",
    "AgentRunStateWindowRequestWire",
    "AgentRunStateWindowResponseWire",
    "AgentRunStateWindowRowWire",
    "agent_run_state_resolve_request_to_dict",
    "agent_run_state_resolve_response_from_dict",
    "agent_run_state_schedule_request_to_dict",
    "agent_run_state_schedule_response_from_dict",
    "agent_run_state_window_request_to_dict",
    "agent_run_state_window_response_from_dict",
]
