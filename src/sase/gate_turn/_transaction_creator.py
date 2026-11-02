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
    claim_artifacts_dir: str | None = None
    claim_artifacts_timestamp: str | None = None


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
    claim_origin = _claim_origin_fields(
        ctx.record.artifact_dir,
        raw_meta,
        project_name=project_name,
        root_timestamp=os.environ.get("SASE_AGENT_ROOT_TIMESTAMP"),
        cl_name_hint=os.environ.get("SASE_AGENT_CL_NAME"),
    )
    return CreatorContext(
        project_name=project_name,
        project_file=ctx.record.project_file or get_project_file_path(project_name),
        artifacts_dir=ctx.record.artifact_dir,
        timestamp=ctx.record.timestamp,
        target_name=target_name,
        durable_lane=durable_lane,
        meta=raw_meta,
        workspace_num=claim_origin["workspace_num"],
        runner_pid=claim_origin["runner_pid"],
        cl_name=claim_origin["cl_name"],
        claim_artifacts_dir=claim_origin["artifacts_dir"],
        claim_artifacts_timestamp=claim_origin["timestamp"],
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
    timestamp = creator.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.strip():
        timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    raw_claim_origin = creator.get("meta")
    claim_origin = (
        raw_claim_origin.get("claim_origin")
        if isinstance(raw_claim_origin, Mapping)
        else None
    )
    claim_origin = claim_origin if isinstance(claim_origin, Mapping) else {}
    claim_timestamp = _clean_optional_str(
        claim_origin.get("artifacts_timestamp")
    ) or _clean_optional_str(creator.get("claim_artifacts_timestamp"))
    if claim_timestamp is None:
        claim_timestamp = timestamp.strip()
    claim_artifacts_dir = _clean_optional_str(claim_origin.get("artifacts_dir"))
    if claim_artifacts_dir is None and claim_timestamp:
        claim_artifacts_dir = _resolve_claim_artifacts_dir(
            artifacts_dir, project_name, claim_timestamp
        )
    claim_meta = _read_claim_origin_meta(
        artifacts_dir,
        raw_meta,
        claim_artifacts_dir or artifacts_dir,
    )
    workspace_num = _optional_int(creator.get("workspace_num"))
    if workspace_num is None:
        workspace_num = _optional_int(claim_origin.get("workspace_num"))
    if workspace_num is None:
        workspace_num = _optional_int(claim_meta.get("workspace_num"))
    runner_pid = _optional_int(creator.get("runner_pid"))
    if runner_pid is None:
        runner_pid = _optional_int(claim_origin.get("runner_pid"))
    if runner_pid is None:
        runner_pid = _optional_int(claim_meta.get("pid"))
    cl_name = _clean_optional_str(creator.get("cl_name"))
    if cl_name is None:
        cl_name = _clean_optional_str(claim_origin.get("cl_name"))
    if cl_name is None:
        cl_name = _claim_cl_name(claim_meta, fallback=raw_meta)
    project_file = creator.get("project_file")
    if not isinstance(project_file, str) or not project_file.strip():
        project_file = get_project_file_path(project_name)
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
        cl_name=cl_name,
        claim_artifacts_dir=claim_artifacts_dir,
        claim_artifacts_timestamp=claim_timestamp or timestamp.strip(),
    )


def claim_origin_for_artifacts(
    artifacts_dir: str,
    meta: Mapping[str, Any],
    *,
    project_name: str,
    root_timestamp: str | None = None,
    cl_name_hint: str | None = None,
) -> dict[str, Any]:
    """Return the RUNNING-claim identity for this agent session member.

    Workflow steps can publish their own ``SASE_ARTIFACTS_DIR`` while the
    runner keeps the claim created for its root turn. The root timestamp and
    root agent metadata identify that exact claim; the current member path
    remains the source of gate content and repository evidence.
    """
    return _claim_origin_fields(
        artifacts_dir,
        dict(meta),
        project_name=project_name,
        root_timestamp=root_timestamp,
        cl_name_hint=cl_name_hint,
    )


def _claim_origin_fields(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    project_name: str,
    root_timestamp: str | None,
    cl_name_hint: str | None,
) -> dict[str, Any]:
    current_timestamp = Path(artifacts_dir.rstrip("/")).name
    timestamp = _clean_optional_str(root_timestamp) or current_timestamp
    if Path(timestamp).name != timestamp:
        timestamp = current_timestamp
    claim_artifacts_dir = _resolve_claim_artifacts_dir(
        artifacts_dir, project_name, timestamp
    )
    claim_meta = _read_claim_origin_meta(
        artifacts_dir,
        meta,
        claim_artifacts_dir,
    )
    return {
        "artifacts_dir": claim_artifacts_dir,
        "timestamp": timestamp,
        "workspace_num": _optional_int(claim_meta.get("workspace_num"))
        if _optional_int(claim_meta.get("workspace_num")) is not None
        else _optional_int(meta.get("workspace_num")),
        "runner_pid": _optional_int(claim_meta.get("pid"))
        if _optional_int(claim_meta.get("pid")) is not None
        else _optional_int(meta.get("pid")),
        "cl_name": _claim_cl_name(
            claim_meta,
            fallback=meta,
            hint=cl_name_hint,
        ),
    }


def _read_claim_origin_meta(
    artifacts_dir: str,
    current_meta: dict[str, Any],
    claim_artifacts_dir: str,
) -> dict[str, Any]:
    claim_dir = Path(claim_artifacts_dir)
    if (
        claim_dir == Path(artifacts_dir)
        or not (claim_dir / "agent_meta.json").is_file()
    ):
        return current_meta
    return _read_meta(str(claim_dir))


def _resolve_claim_artifacts_dir(
    artifacts_dir: str,
    project_name: str,
    claim_timestamp: str,
) -> str:
    """Resolve the root artifact path across legacy and day-sharded layouts."""
    from sase.core.agent_artifact_paths import (
        ACE_RUN_WORKFLOW_DIR,
        resolve_agent_artifact_timestamp_path,
    )

    try:
        canonical = resolve_agent_artifact_timestamp_path(
            project_name,
            ACE_RUN_WORKFLOW_DIR,
            claim_timestamp,
        )
    except Exception:
        canonical = Path(artifacts_dir).parent / claim_timestamp
    if (canonical / "agent_meta.json").is_file():
        return str(canonical)
    same_parent = Path(artifacts_dir).parent / claim_timestamp
    if (same_parent / "agent_meta.json").is_file():
        return str(same_parent)
    return str(canonical)


def _claim_cl_name(
    claim_meta: Mapping[str, Any],
    *,
    fallback: Mapping[str, Any],
    hint: str | None = None,
) -> str | None:
    for candidate in (claim_meta,):
        for key in ("cl_name", "patch_name", "changespec_name"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    hinted = _clean_optional_str(hint)
    if hinted is not None:
        return hinted
    for key in ("cl_name", "patch_name", "changespec_name"):
        value = fallback.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _clean_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


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
