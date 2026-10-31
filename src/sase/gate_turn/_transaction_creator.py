"""Creator identity for gate-turn publication.

The publisher needs to know which agent is creating a gate: its project,
durable lane, workspace claim, and runner. The immediate path resolves that
from the live environment (:func:`resolve_creator`); staged adoption rebuilds
it from the persisted creator block (:func:`creator_context_from_persisted`).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.gate_turn.models import GateTurnLaneError
from sase.plan_chain import (
    agent_session_base,
    agent_session_value,
)
from sase.workflows.utils import get_project_file_path


@dataclass(frozen=True)
class CreatorContext:
    """Resolved identity of the agent creating a gate turn."""

    project_name: str
    project_file: str
    artifacts_dir: str
    timestamp: str
    target_name: str
    durable_lane: str
    meta: dict[str, Any]
    workspace_num: int | None
    runner_pid: int | None
    cl_name: str | None


def resolve_project_name() -> str:
    """Return the project the live environment is creating a gate for."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if artifacts_dir:
        from sase.turns.settlement import project_name_from_artifacts_dir

        project_name = project_name_from_artifacts_dir(artifacts_dir)
        if project_name:
            return project_name
    try:
        from sase.workspace_provider import get_workspace_name

        project_name = get_workspace_name(os.getcwd())
        if project_name:
            return project_name
    except Exception as exc:
        raise GateTurnLaneError(
            "could not resolve project for gate turn creation"
        ) from exc
    raise GateTurnLaneError("could not resolve project for gate turn creation")


def resolve_creator(project_name: str) -> CreatorContext:
    """Resolve the calling agent from the live environment."""
    from sase.agent._agent_session_promotion import promote_agent_to_agent_session
    import sase.monitor.store_lane as monitor_store

    caller = monitor_store.default_caller() or os.environ.get("SASE_AGENT_NAME")
    artifacts_dir = monitor_store.caller_artifacts_dir()
    if not caller and artifacts_dir:
        caller = _read_meta(artifacts_dir).get("name")
    if not isinstance(caller, str) or not caller:
        raise GateTurnLaneError(
            "no calling agent found; SASE_AGENT_NAME or SASE_ARTIFACTS_DIR is required"
        )
    try:
        ctx = monitor_store.resolve_caller_agent(
            project_name,
            caller,
            artifacts_dir=artifacts_dir,
        )
    except Exception as exc:
        raise GateTurnLaneError(str(exc)) from exc

    raw_meta = _read_meta(ctx.record.artifact_dir)
    durable_lane = str(agent_session_value(raw_meta) or "").strip()
    target_name = str(raw_meta.get("name") or caller)
    if not durable_lane:
        promoted_name = promote_agent_to_agent_session(
            ctx.record.artifact_dir, target_name
        )
        durable_lane = agent_session_base(promoted_name) or target_name
        raw_meta = _read_meta(ctx.record.artifact_dir)
    workspace_num = _optional_int(raw_meta.get("workspace_num"))
    runner_pid = _optional_int(raw_meta.get("pid"))
    cl_name = raw_meta.get("cl_name")
    return CreatorContext(
        project_name=project_name,
        project_file=ctx.record.project_file or get_project_file_path(project_name),
        artifacts_dir=ctx.record.artifact_dir,
        timestamp=ctx.record.timestamp,
        target_name=target_name,
        durable_lane=durable_lane,
        meta=raw_meta,
        workspace_num=workspace_num,
        runner_pid=runner_pid,
        cl_name=cl_name if isinstance(cl_name, str) else None,
    )


def creator_context_from_persisted(
    creator: Mapping[str, Any],
) -> CreatorContext:
    """Rebuild publication identity from a staged payload's creator block.

    Re-reads the persisted run's ``agent_meta.json`` and applies session
    promotion there. The adopter's environment is never consulted, so a
    later re-adopt cannot publish as the re-adopter.
    """
    from sase.agent._agent_session_promotion import promote_agent_to_agent_session

    project_name = creator.get("project")
    artifacts_dir = creator.get("artifacts_dir")
    if not isinstance(project_name, str) or not project_name.strip():
        raise GateTurnLaneError("staged gate creator is missing project")
    if not isinstance(artifacts_dir, str) or not artifacts_dir.strip():
        raise GateTurnLaneError("staged gate creator is missing artifacts_dir")
    project_name = project_name.strip()
    artifacts_dir = artifacts_dir.strip()
    raw_meta = _read_meta(artifacts_dir)
    durable_lane = str(
        agent_session_value(raw_meta) or creator.get("agent_session") or ""
    ).strip()
    recorded_target = creator.get("target") or creator.get("agent")
    target_name = str(
        raw_meta.get("name")
        if isinstance(raw_meta.get("name"), str) and raw_meta.get("name")
        else recorded_target or ""
    ).strip()
    if not target_name:
        raise GateTurnLaneError("staged gate creator is missing agent identity")
    if not durable_lane:
        promoted_name = promote_agent_to_agent_session(artifacts_dir, target_name)
        durable_lane = agent_session_base(promoted_name) or target_name
        raw_meta = _read_meta(artifacts_dir)
        if isinstance(raw_meta.get("name"), str) and raw_meta.get("name"):
            target_name = str(raw_meta["name"])
    workspace_num = _optional_int(raw_meta.get("workspace_num"))
    if workspace_num is None:
        workspace_num = _optional_int(creator.get("workspace_num"))
    runner_pid = _optional_int(raw_meta.get("pid"))
    if runner_pid is None:
        runner_pid = _optional_int(creator.get("runner_pid"))
    cl_name = raw_meta.get("cl_name")
    if not isinstance(cl_name, str) or not cl_name:
        recorded_cl = creator.get("cl_name")
        cl_name = recorded_cl if isinstance(recorded_cl, str) else None
    project_file = creator.get("project_file")
    if not isinstance(project_file, str) or not project_file.strip():
        project_file = get_project_file_path(project_name)
    timestamp = creator.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.strip():
        timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    return CreatorContext(
        project_name=project_name,
        project_file=project_file.strip(),
        artifacts_dir=artifacts_dir,
        timestamp=timestamp.strip(),
        target_name=target_name,
        durable_lane=durable_lane,
        meta=raw_meta,
        workspace_num=workspace_num,
        runner_pid=runner_pid,
        cl_name=cl_name if isinstance(cl_name, str) else None,
    )


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    path = Path(artifacts_dir) / "agent_meta.json"
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise GateTurnLaneError(f"agent_meta.json at {artifacts_dir!r} is invalid")
    return data


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int | str):
        return None
    try:
        return int(value)
    except ValueError:
        return None
