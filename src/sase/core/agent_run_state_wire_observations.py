"""Observation and discovery wire records for published agent-run state.

Mirrors the additive observation/discovery contracts in
``sase_core::agent_run_state::wire``. Import from
:mod:`sase.core.agent_run_state_wire`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.core.agent_run_state_wire import (
    AGENT_RUN_STATE_WIRE_SCHEMA_VERSION,
    AgentRunIdentityWire,
)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _check_schema(data: dict[str, Any], *, what: str) -> int:
    schema_version = int(data.get("schema_version", 0))
    if schema_version != AGENT_RUN_STATE_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs agent run state wire is stale: "
            f"expected schema {AGENT_RUN_STATE_WIRE_SCHEMA_VERSION}, "
            f"got {schema_version} for {what}"
        )
    return schema_version


def _identity_to_dict(identity: AgentRunIdentityWire) -> dict[str, Any]:
    return {
        "project": identity.project,
        "owner": identity.owner,
        "global_name": identity.global_name,
        "source_run_id": identity.source_run_id,
    }


@dataclass(frozen=True)
class AgentRunStateIdentityClaimsWire:
    """Optional identity fields copied from a filesystem observation."""

    project: str | None = None
    owner: str | None = None
    global_name: str | None = None
    local_name: str | None = None
    name: str | None = None
    source_run_id: str | None = None


@dataclass(frozen=True)
class AgentRunStateRawObservationWire:
    """One uncollapsed filesystem candidate for a selected immutable run."""

    source: str = ""
    read_status: str = ""
    identity_claims: AgentRunStateIdentityClaimsWire | None = None
    outcome: str | None = None
    state: str | None = None
    repeat_stopped: bool = False
    monitor_state: str | None = None
    gate_state: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    imported: bool = False


@dataclass(frozen=True)
class AgentRunStateObservationsResolveRequestWire:
    """Request to classify raw observations and resolve published state."""

    identity: AgentRunIdentityWire = field(default_factory=AgentRunIdentityWire)
    local_name: str | None = None
    published_state: str = ""
    published_started_at: str | None = None
    published_finished_at: str | None = None
    observations: tuple[AgentRunStateRawObservationWire, ...] = ()
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


@dataclass(frozen=True)
class AgentRunStateObservationClassificationWire:
    """Rust classification of one raw observation."""

    index: int = 0
    source: str = ""
    evidence_kind: str = ""
    evidence_state: str | None = None
    evidence_started_at: str | None = None
    evidence_finished_at: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class AgentRunStateObservationsResolveResponseWire:
    """Resolved state plus per-observation classifications."""

    selected_state: str = ""
    selected_started_at: str | None = None
    selected_finished_at: str | None = None
    changed: bool = False
    reason: str = ""
    observations: tuple[AgentRunStateObservationClassificationWire, ...] = ()
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


@dataclass(frozen=True)
class AgentRunStateHoodWindowRequestWire:
    """Request a bounded list of owner-manifest hoods before snapshot reads."""

    project: str = ""
    owner: str = ""
    manifest_status: str = ""
    after: str | None = None
    hoods: tuple[str, ...] = ()
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


@dataclass(frozen=True)
class AgentRunStateHoodWindowResponseWire:
    """At most five hood names plus whether more remain."""

    selected_hoods: tuple[str, ...] = ()
    has_more_hoods: bool = False
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


@dataclass(frozen=True)
class AgentRunStateDiscoveredHoodWire:
    """Run IDs read from one selected hood snapshot."""

    local_hood: str = ""
    status: str = ""
    source_run_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentRunStateDiscoveryWindowRequestWire:
    """Request a bounded discovery window over selected hood snapshots."""

    project: str = ""
    owner: str = ""
    manifest_status: str = ""
    scan_status: str = ""
    limit: int = 100
    after: str | None = None
    manifest_hoods: tuple[str, ...] = ()
    hoods: tuple[AgentRunStateDiscoveredHoodWire, ...] = ()
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


@dataclass(frozen=True)
class AgentRunStateDiscoveryDiagnosticWire:
    """Bounded diagnostic for one empty or corrupt discovered hood."""

    local_hood: str = ""
    kind: str = ""


@dataclass(frozen=True)
class AgentRunStateDiscoveryWindowResponseWire:
    """Selected discovery rows plus cursor and bounded diagnostics."""

    selected: tuple[Any, ...] = ()
    next_cursor: str | None = None
    pass_complete: bool = False
    diagnostics: tuple[AgentRunStateDiscoveryDiagnosticWire, ...] = ()
    schema_version: int = AGENT_RUN_STATE_WIRE_SCHEMA_VERSION


def _identity_claims_to_dict(
    claims: AgentRunStateIdentityClaimsWire | None,
) -> dict[str, Any] | None:
    if claims is None:
        return None
    return {
        "project": claims.project,
        "owner": claims.owner,
        "global_name": claims.global_name,
        "local_name": claims.local_name,
        "name": claims.name,
        "source_run_id": claims.source_run_id,
    }


def _observation_to_dict(
    observation: AgentRunStateRawObservationWire,
) -> dict[str, Any]:
    return {
        "source": observation.source,
        "read_status": observation.read_status,
        "identity_claims": _identity_claims_to_dict(observation.identity_claims),
        "outcome": observation.outcome,
        "state": observation.state,
        "repeat_stopped": observation.repeat_stopped,
        "monitor_state": observation.monitor_state,
        "gate_state": observation.gate_state,
        "started_at": observation.started_at,
        "finished_at": observation.finished_at,
        "imported": observation.imported,
    }


def agent_run_state_observations_resolve_request_to_dict(
    request: AgentRunStateObservationsResolveRequestWire,
) -> dict[str, Any]:
    """Serialize an observations resolve request to the Rust dict shape."""
    return {
        "schema_version": request.schema_version,
        "identity": _identity_to_dict(request.identity),
        "local_name": request.local_name,
        "published_state": request.published_state,
        "published_started_at": request.published_started_at,
        "published_finished_at": request.published_finished_at,
        "observations": [_observation_to_dict(item) for item in request.observations],
    }


def agent_run_state_observations_resolve_response_from_dict(
    data: dict[str, Any],
) -> AgentRunStateObservationsResolveResponseWire:
    """Rehydrate an observations resolve response from the PyO3 dict shape."""
    _check_schema(data, what="AgentRunStateObservationsResolveResponseWire")
    classified: list[AgentRunStateObservationClassificationWire] = []
    for entry in data.get("observations") or []:
        if not isinstance(entry, dict):
            continue
        classified.append(
            AgentRunStateObservationClassificationWire(
                index=int(entry.get("index", 0)),
                source=str(entry.get("source", "")),
                evidence_kind=str(entry.get("evidence_kind", "")),
                evidence_state=_opt_str(entry.get("evidence_state")),
                evidence_started_at=_opt_str(entry.get("evidence_started_at")),
                evidence_finished_at=_opt_str(entry.get("evidence_finished_at")),
                reason=str(entry.get("reason", "")),
            )
        )
    return AgentRunStateObservationsResolveResponseWire(
        schema_version=int(data["schema_version"]),
        selected_state=str(data.get("selected_state", "")),
        selected_started_at=_opt_str(data.get("selected_started_at")),
        selected_finished_at=_opt_str(data.get("selected_finished_at")),
        changed=bool(data.get("changed", False)),
        reason=str(data.get("reason", "")),
        observations=tuple(classified),
    )


def agent_run_state_hood_window_request_to_dict(
    request: AgentRunStateHoodWindowRequestWire,
) -> dict[str, Any]:
    """Serialize a hood-window request to the Rust dict shape."""
    return {
        "schema_version": request.schema_version,
        "project": request.project,
        "owner": request.owner,
        "manifest_status": request.manifest_status,
        "after": request.after,
        "hoods": list(request.hoods),
    }


def agent_run_state_hood_window_response_from_dict(
    data: dict[str, Any],
) -> AgentRunStateHoodWindowResponseWire:
    """Rehydrate a hood-window response from the PyO3 dict shape."""
    _check_schema(data, what="AgentRunStateHoodWindowResponseWire")
    hoods = tuple(
        str(item)
        for item in (data.get("selected_hoods") or [])
        if isinstance(item, str)
    )
    return AgentRunStateHoodWindowResponseWire(
        schema_version=int(data["schema_version"]),
        selected_hoods=hoods,
        has_more_hoods=bool(data.get("has_more_hoods", False)),
    )


def agent_run_state_discovery_window_request_to_dict(
    request: AgentRunStateDiscoveryWindowRequestWire,
) -> dict[str, Any]:
    """Serialize a discovery-window request to the Rust dict shape."""
    return {
        "schema_version": request.schema_version,
        "project": request.project,
        "owner": request.owner,
        "manifest_status": request.manifest_status,
        "scan_status": request.scan_status,
        "limit": request.limit,
        "after": request.after,
        "manifest_hoods": list(request.manifest_hoods),
        "hoods": [
            {
                "local_hood": hood.local_hood,
                "status": hood.status,
                "source_run_ids": list(hood.source_run_ids),
            }
            for hood in request.hoods
        ],
    }


def agent_run_state_discovery_window_response_from_dict(
    data: dict[str, Any],
) -> AgentRunStateDiscoveryWindowResponseWire:
    """Rehydrate a discovery-window response from the PyO3 dict shape."""
    from sase.core.agent_run_state_wire import AgentRunStateWindowRowWire

    _check_schema(data, what="AgentRunStateDiscoveryWindowResponseWire")
    selected: list[AgentRunStateWindowRowWire] = []
    for entry in data.get("selected") or []:
        if isinstance(entry, dict):
            selected.append(
                AgentRunStateWindowRowWire(
                    local_hood=str(entry.get("local_hood", "")),
                    source_run_id=str(entry.get("source_run_id", "")),
                )
            )
    diagnostics: list[AgentRunStateDiscoveryDiagnosticWire] = []
    for entry in data.get("diagnostics") or []:
        if isinstance(entry, dict):
            diagnostics.append(
                AgentRunStateDiscoveryDiagnosticWire(
                    local_hood=str(entry.get("local_hood", "")),
                    kind=str(entry.get("kind", "")),
                )
            )
    return AgentRunStateDiscoveryWindowResponseWire(
        schema_version=int(data["schema_version"]),
        selected=tuple(selected),
        next_cursor=_opt_str(data.get("next_cursor")),
        pass_complete=bool(data.get("pass_complete", False)),
        diagnostics=tuple(diagnostics),
    )
