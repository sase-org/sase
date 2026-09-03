"""JSON-safe cleanup persistence payloads for durable agent operations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_bundle import agent_state_to_bundle_dict


def _json_identity(identity: tuple[Any, ...]) -> list[Any]:
    """Serialize one dismissed/kill identity without enum objects."""
    agent_type, cl_name, suffix = identity[0], identity[1], identity[2]
    return [getattr(agent_type, "value", str(agent_type)), str(cl_name), suffix]


def json_identities(identities: Iterable[tuple[Any, ...]]) -> list[list[Any]]:
    """Serialize a set or sequence of agent identities."""
    return [_json_identity(item) for item in identities]


def _identity_from_json(item: object) -> tuple[AgentType, str, str | None]:
    """Rehydrate one identity from a JSON list."""
    if not isinstance(item, list) or len(item) < 2:
        raise ValueError(f"invalid cleanup identity: {item!r}")
    suffix = item[2] if len(item) > 2 else None
    return (
        AgentType(str(item[0])),
        str(item[1]),
        None if suffix is None else str(suffix),
    )


def identities_from_json(raw: object) -> set[tuple[AgentType, str, str | None]]:
    """Rehydrate a dismissed-identity snapshot from JSON."""
    if not isinstance(raw, list):
        return set()
    return {_identity_from_json(item) for item in raw if isinstance(item, list)}


CLEANUP_AGENT_ARCHIVE_VERSION = 1
CLEANUP_AGENT_ARCHIVE_VERSION_KEY = "archive_version"
LEGACY_CLEANUP_AGENT_ARCHIVE_VERSION = 0
SUPPORTED_CLEANUP_AGENT_ARCHIVE_VERSIONS = frozenset(
    {LEGACY_CLEANUP_AGENT_ARCHIVE_VERSION, CLEANUP_AGENT_ARCHIVE_VERSION}
)


def _effective_artifacts_dir(agent: Agent) -> str | None:
    """Resolve the artifacts dir that revival needs, not the in-memory field.

    List-shaped index projections often leave ``artifacts_dir`` null even when
    the index record (or an on-disk timestamp dir) knows the path. Resolve
    before the cleanup subprocess boundary so the dismissed bundle cannot
    persist a null path.
    """
    resolved = agent.get_artifacts_dir()
    if isinstance(resolved, str) and resolved:
        return resolved
    index_dir = agent.index_record_dir
    if isinstance(index_dir, str) and index_dir:
        return index_dir
    artifacts_dir = agent.artifacts_dir
    if isinstance(artifacts_dir, str) and artifacts_dir:
        return artifacts_dir
    return None


def serialize_agent(agent: Agent) -> dict[str, Any]:
    """Project persist-relevant Agent fields into a versioned archive DTO.

    The DTO carries every field the dismissed-bundle writer consumes, plus
    the resolved effective artifacts dir. Future Agent bundle fields fail
    the archive-vs-writer field regression rather than silently nulling.
    """
    archive = agent_state_to_bundle_dict(agent)
    effective_dir = _effective_artifacts_dir(agent)
    if effective_dir:
        archive["artifacts_dir"] = effective_dir
    archive[CLEANUP_AGENT_ARCHIVE_VERSION_KEY] = CLEANUP_AGENT_ARCHIVE_VERSION
    return archive


def serialize_agents(agents: Iterable[Agent] | None) -> list[dict[str, Any]]:
    """Serialize a sequence of agents for a cleanup request."""
    if not agents:
        return []
    return [serialize_agent(agent) for agent in agents]


def agent_from_json(data: Mapping[str, Any]) -> Agent:
    """Rehydrate a persist-capable Agent from a cleanup archive DTO."""
    payload = dict(data)
    raw_version = payload.pop(CLEANUP_AGENT_ARCHIVE_VERSION_KEY, None)
    if raw_version is None:
        version = LEGACY_CLEANUP_AGENT_ARCHIVE_VERSION
    elif isinstance(raw_version, int):
        version = raw_version
    else:
        raise ValueError(f"unsupported cleanup agent archive version: {raw_version!r}")
    if version not in SUPPORTED_CLEANUP_AGENT_ARCHIVE_VERSIONS:
        raise ValueError(f"unsupported cleanup agent archive version: {version!r}")
    if "from_patch" in payload and "_from_patch" not in payload:
        payload["_from_patch"] = bool(payload.pop("from_patch"))
    else:
        payload.pop("from_patch", None)
    payload.setdefault("agent_type", AgentType.RUNNING.value)
    payload.setdefault("cl_name", "")
    payload.setdefault("project_file", "")
    payload.setdefault("status", "DONE")
    return Agent.from_bundle_dict(payload, synthesize_missing_name=False)


def agents_from_json(raw: object) -> list[Agent]:
    """Rehydrate a list of agents from JSON."""
    if not isinstance(raw, list):
        return []
    return [agent_from_json(item) for item in raw if isinstance(item, dict)]


__all__ = [
    "CLEANUP_AGENT_ARCHIVE_VERSION",
    "CLEANUP_AGENT_ARCHIVE_VERSION_KEY",
    "LEGACY_CLEANUP_AGENT_ARCHIVE_VERSION",
    "SUPPORTED_CLEANUP_AGENT_ARCHIVE_VERSIONS",
    "agent_from_json",
    "agents_from_json",
    "identities_from_json",
    "json_identities",
    "serialize_agent",
    "serialize_agents",
]
