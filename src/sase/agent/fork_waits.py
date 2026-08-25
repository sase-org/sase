"""Typed dependency metadata for waits implied by ``#fork`` references."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_artifact_paths import parse_agent_artifact_path


def fork_wait_dependency(name: str) -> dict[str, str]:
    """Return a stable wait identity for one explicit ``#fork`` target."""
    from sase.agent.names import find_agent_clan, find_agent_family, find_named_agent

    clan = find_agent_clan(name)
    if clan is not None:
        return {
            "kind": "clan",
            "name": clan.name,
            "generation": clan.generation,
        }

    family = find_agent_family(name)
    if family is not None:
        dependency = {
            "kind": "family",
            "name": family.base_name,
        }
        if family.root is not None:
            dependency.update(_artifact_identity(family.root.artifacts_dir))
        elif family.timestamp:
            dependency["timestamp"] = family.timestamp
        return dependency

    agent = find_named_agent(name)
    if agent is not None:
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
