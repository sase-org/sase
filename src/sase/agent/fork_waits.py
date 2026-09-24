"""Typed dependency metadata for waits implied by ``#fork`` references."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.agent.names._lookup_artifacts import read_json_dict
from sase.monitor_state import is_real_monitor_member
from sase.plan_chain import agent_session_role_value


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
            dependency.update(_artifact_identity(agent_session.root.artifacts_dir))
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
        return {
            "kind": "agent",
            "name": agent.name,
            **_artifact_identity(Path(agent.artifacts_dir)),
        }

    proc_id = _resolved_proc_id(name)
    if proc_id is not None:
        return {
            "kind": "proc",
            "name": name,
            "proc_id": proc_id,
        }

    return {"kind": "name", "name": name}


def _artifact_identity(artifact_dir: Path) -> dict[str, str]:
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


def _resolved_proc_id(name: str) -> str | None:
    try:
        from sase.procs import ProcRefError, read_procs, resolve_proc_ref

        return resolve_proc_ref(name, read_procs()).proc_id
    except ProcRefError as exc:
        if "ambiguous" in str(exc):
            raise RuntimeError(str(exc)) from exc
        return None
    except Exception:
        return None


__all__ = ["fork_wait_dependency"]
