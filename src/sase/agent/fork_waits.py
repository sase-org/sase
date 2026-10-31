"""Typed dependency metadata for waits implied by ``#fork`` references."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.agent.names._lookup_artifacts import meta_parent_timestamp, read_json_dict
from sase.monitor_state import is_real_monitor_member
from sase.plan_chain import agent_session_role_value


def fork_source_follows_promotion(
    dependency: Mapping[str, Any],
    candidate: object | None,
    *,
    session_name: str | None = None,
) -> bool:
    """Return whether a legacy bare-name fork now follows its promoted session.

    Wait-index candidates expose ``agent_session_name``; history resolution can
    supply the same session name alongside the exact root member it found by
    artifact identity.
    """
    if candidate is None or dependency.get("kind") != "agent":
        return False
    if dependency.get("target") is not None:
        return False

    if isinstance(candidate, Mapping):
        parent_timestamp = candidate.get("parent_timestamp")
        candidate_session_name = candidate.get("agent_session_name")
    else:
        parent_timestamp = getattr(candidate, "parent_timestamp", None)
        candidate_session_name = getattr(candidate, "agent_session_name", None)
    if parent_timestamp is not None:
        return False

    effective_session_name = session_name or candidate_session_name
    name = dependency.get("name")
    return (
        isinstance(effective_session_name, str)
        and bool(effective_session_name)
        and isinstance(name, str)
        and bool(name)
        and name == effective_session_name
    )


def fork_wait_dependency(name: str) -> dict[str, str]:
    """Return a stable wait identity for one explicit ``#fork`` target."""
    from sase.agent.names import find_agent_clan, find_agent_session, find_named_agent

    clan = find_agent_clan(name)
    if clan is not None:
        return {
            "kind": "clan",
            "name": clan.name,
            "generation": clan.generation,
        }

    agent_session = find_agent_session(name)
    if agent_session is not None:
        dependency = {
            "kind": "session",
            "name": agent_session.base_name,
        }
        if agent_session.root is not None:
            dependency.update(artifact_identity(agent_session.root.artifacts_dir))
        elif agent_session.timestamp:
            dependency["timestamp"] = agent_session.timestamp
        return dependency

    agent = find_named_agent(name)
    if agent is not None:
        meta = read_json_dict(Path(agent.artifacts_dir) / "agent_meta.json") or {}
        monitor_id = _json_string(meta, "monitor_id")
        if monitor_id is not None and is_real_monitor_member(
            _json_session_role(meta),
            monitor_id,
        ):
            return {
                "kind": "proc",
                "name": agent.name,
                "proc_id": monitor_id,
            }
        if _is_plain_bare_root(name, agent, meta):
            return {
                "kind": "session",
                "name": agent.name,
                **artifact_identity(Path(agent.artifacts_dir)),
            }
        return {
            "kind": "agent",
            "name": agent.name,
            **artifact_identity(Path(agent.artifacts_dir)),
        }

    proc_id = resolved_proc_id(name)
    if proc_id is not None:
        return {
            "kind": "proc",
            "name": name,
            "proc_id": proc_id,
        }

    return {"kind": "name", "name": name}


def _is_plain_bare_root(
    name: str,
    agent: object,
    meta: dict[str, object],
) -> bool:
    """Return whether *name* is a bare name over a never-promoted plain agent.

    A bare name that resolves to a plain root agent is recorded as a session
    seed (``kind: "session"``) so a later promotion of that agent into a
    session keeps the fork waiting through review and coding. Exact members,
    monitors/procs, clans, and fallbacks keep their current records.
    """
    agent_name = getattr(agent, "name", None)
    if agent_name != name:
        return False
    # Monitor-associated starters keep their agent record: they are not plain
    # root agents even when they lack a session role.
    if _json_string(meta, "monitor_id") is not None:
        return False
    try:
        from sase.core.agent_identity_facade import (
            AgentSessionNameKind,
            parse_agent_session_name,
        )

        if parse_agent_session_name(name).kind is AgentSessionNameKind.MEMBER:
            return False
    except (RuntimeError, ValueError):
        return False
    if meta_parent_timestamp(meta) is not None:
        return False
    return not _json_session_role(meta)


def artifact_identity(artifact_dir: Path) -> dict[str, str]:
    """Return the durable identity fields for one artifact directory."""
    identity = {
        "artifact_dir": str(artifact_dir),
        "timestamp": artifact_dir.name,
    }
    project_name = _project_name_for_artifact_dir(artifact_dir)
    if project_name:
        identity["project_name"] = project_name
    return identity


def _project_name_for_artifact_dir(artifact_dir: Path) -> str:
    try:
        info = parse_agent_artifact_path(artifact_dir)
    except (OSError, RuntimeError, ValueError):
        return ""
    return info.project_name if info is not None else ""


def _json_string(data: dict[str, object], field: str) -> str | None:
    value = data.get(field)
    return value if isinstance(value, str) and value else None


def _json_session_role(data: dict[str, object]) -> str | None:
    """Return the agent-session role, reading the legacy key as fallback."""
    role = agent_session_role_value(data)
    return role if isinstance(role, str) and role else None


def resolved_proc_id(name: str) -> str | None:
    """Return the proc id for *name*, or None when it is not a proc ref."""
    try:
        from sase.procs import ProcRefError, read_procs, resolve_proc_ref

        return resolve_proc_ref(name, read_procs()).proc_id
    except ProcRefError as exc:
        if "ambiguous" in str(exc):
            raise RuntimeError(str(exc)) from exc
        return None
    except Exception:
        return None


__all__ = ["artifact_identity", "fork_wait_dependency", "resolved_proc_id"]
