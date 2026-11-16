"""Wire records for targeted agent-artifact identity lookups.

Mirrors ``sase_core::agent_scan``'s ``AgentArtifactLookup*Wire`` family
(artifact-index schema 38). Later named/session/clan cutover phases
translate these hits into the existing public dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sase.core.wire import known_field_kwargs

AgentArtifactLookupTargetKind = Literal["names", "session", "clan", "pointers"]
AgentArtifactLookupAvailability = Literal[
    "ready",
    "missing",
    "stale_schema",
    "newer_schema",
    "corrupt",
    "busy",
]
AGENT_ARTIFACT_LOOKUP_FALLBACK_BUDGET = 200


@dataclass(frozen=True)
class AgentArtifactLookupTargetWire:
    """Identity target for one lookup request."""

    kind: AgentArtifactLookupTargetKind
    names: tuple[str, ...] = ()
    artifact_dirs: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentArtifactLookupQueryWire:
    """Query knobs for a targeted artifact lookup."""

    target: AgentArtifactLookupTargetWire
    include_hidden: bool = True
    forced_unavailability: AgentArtifactLookupAvailability | None = None


@dataclass(frozen=True)
class AgentArtifactLookupHitWire:
    """Compact identity hit. Ranking and liveness stay with later callers."""

    artifact_dir: str
    project_name: str
    workflow_dir_name: str
    timestamp: str
    has_done_marker: bool
    has_running_marker: bool
    hidden: bool
    agent_name: str | None = None
    workflow_name: str | None = None
    agent_session: str | None = None
    lookup_session: str | None = None
    agent_clan: str | None = None
    agent_clan_generation: str | None = None
    parent_timestamp: str | None = None
    match_kind: str | None = None


@dataclass(frozen=True)
class AgentArtifactLookupResultWire:
    """Result of one targeted lookup, including availability/completeness."""

    schema_version: int
    index_path: str
    projects_root: str
    query: AgentArtifactLookupQueryWire
    availability: AgentArtifactLookupAvailability
    complete: bool
    source: str
    hits: tuple[AgentArtifactLookupHitWire, ...] = ()
    truncated: bool = False
    dirs_visited: int = 0
    records_decoded: int = 0
    diagnostic: str | None = None


def agent_artifact_lookup_query_to_dict(
    query: AgentArtifactLookupQueryWire,
) -> dict[str, Any]:
    """Project a lookup query to the Rust binding dict shape."""
    payload: dict[str, Any] = {
        "target": _target_to_dict(query.target),
        "include_hidden": bool(query.include_hidden),
    }
    if query.forced_unavailability is not None:
        payload["forced_unavailability"] = query.forced_unavailability
    return payload


def agent_artifact_lookup_result_from_dict(
    data: dict[str, Any],
) -> AgentArtifactLookupResultWire:
    """Rehydrate a lookup result from the Rust binding dict."""
    raw_query = data.get("query")
    query = (
        _query_from_dict(raw_query)
        if isinstance(raw_query, dict)
        else AgentArtifactLookupQueryWire(
            target=AgentArtifactLookupTargetWire(kind="names")
        )
    )
    hits = tuple(
        _hit_from_dict(item)
        for item in data.get("hits") or []
        if isinstance(item, dict)
    )
    availability = str(data.get("availability") or "missing")
    if availability not in {
        "ready",
        "missing",
        "stale_schema",
        "newer_schema",
        "corrupt",
        "busy",
    }:
        availability = "missing"
    return AgentArtifactLookupResultWire(
        schema_version=int(data.get("schema_version") or 0),
        index_path=str(data.get("index_path") or ""),
        projects_root=str(data.get("projects_root") or ""),
        query=query,
        availability=availability,  # type: ignore[arg-type]
        complete=bool(data.get("complete")),
        source=str(data.get("source") or "none"),
        hits=hits,
        truncated=bool(data.get("truncated")),
        dirs_visited=int(data.get("dirs_visited") or 0),
        records_decoded=int(data.get("records_decoded") or 0),
        diagnostic=(
            str(data["diagnostic"]) if data.get("diagnostic") is not None else None
        ),
    )


def _target_to_dict(target: AgentArtifactLookupTargetWire) -> dict[str, Any]:
    if target.kind == "pointers":
        return {
            "kind": "pointers",
            "artifact_dirs": list(target.artifact_dirs),
        }
    return {"kind": target.kind, "names": list(target.names)}


def _query_from_dict(data: dict[str, Any]) -> AgentArtifactLookupQueryWire:
    raw_target = data.get("target")
    target = (
        _target_from_dict(raw_target)
        if isinstance(raw_target, dict)
        else AgentArtifactLookupTargetWire(kind="names")
    )
    forced = data.get("forced_unavailability")
    return AgentArtifactLookupQueryWire(
        target=target,
        include_hidden=bool(data.get("include_hidden", True)),
        forced_unavailability=str(forced) if forced is not None else None,  # type: ignore[arg-type]
    )


def _target_from_dict(data: dict[str, Any]) -> AgentArtifactLookupTargetWire:
    kind = str(data.get("kind") or "names")
    if kind not in {"names", "session", "clan", "pointers"}:
        kind = "names"
    names = tuple(str(item) for item in data.get("names") or [])
    artifact_dirs = tuple(str(item) for item in data.get("artifact_dirs") or [])
    return AgentArtifactLookupTargetWire(
        kind=kind,  # type: ignore[arg-type]
        names=names,
        artifact_dirs=artifact_dirs,
    )


def _hit_from_dict(data: dict[str, Any]) -> AgentArtifactLookupHitWire:
    kwargs = known_field_kwargs(AgentArtifactLookupHitWire, data)
    kwargs.setdefault("artifact_dir", "")
    kwargs.setdefault("project_name", "")
    kwargs.setdefault("workflow_dir_name", "")
    kwargs.setdefault("timestamp", "")
    kwargs.setdefault("has_done_marker", False)
    kwargs.setdefault("has_running_marker", False)
    kwargs.setdefault("hidden", False)
    kwargs["artifact_dir"] = str(kwargs["artifact_dir"] or "")
    kwargs["project_name"] = str(kwargs["project_name"] or "")
    kwargs["workflow_dir_name"] = str(kwargs["workflow_dir_name"] or "")
    kwargs["timestamp"] = str(kwargs["timestamp"] or "")
    kwargs["has_done_marker"] = bool(kwargs["has_done_marker"])
    kwargs["has_running_marker"] = bool(kwargs["has_running_marker"])
    kwargs["hidden"] = bool(kwargs["hidden"])
    for optional in (
        "agent_name",
        "workflow_name",
        "agent_session",
        "lookup_session",
        "agent_clan",
        "agent_clan_generation",
        "parent_timestamp",
        "match_kind",
    ):
        value = kwargs.get(optional)
        kwargs[optional] = str(value) if value is not None else None
    return AgentArtifactLookupHitWire(**kwargs)


__all__ = [
    "AGENT_ARTIFACT_LOOKUP_FALLBACK_BUDGET",
    "AgentArtifactLookupAvailability",
    "AgentArtifactLookupHitWire",
    "AgentArtifactLookupQueryWire",
    "AgentArtifactLookupResultWire",
    "AgentArtifactLookupTargetKind",
    "AgentArtifactLookupTargetWire",
    "agent_artifact_lookup_query_to_dict",
    "agent_artifact_lookup_result_from_dict",
]
