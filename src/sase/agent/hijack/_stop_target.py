"""Resolve the live agent row into a hijack target."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sase.agent.hijack._stop_models import (
    HijackTarget,
    StopDeps,
    read_done_marker,
    read_json_dict,
)


def resolve_target(name: str, *, deps: StopDeps) -> HijackTarget | None:
    find_agent = deps.find_agent or _default_find_agent
    found = find_agent(name)
    if found is None:
        return None
    artifacts_dir = str(
        getattr(found, "artifacts_dir", "") or "",
    )
    if not artifacts_dir:
        return None
    from sase.agent.running import (
        named_agent_project_fields as _project_fields,
    )

    _, project_name, project_file, timestamp, is_home = _project_fields(found)
    meta = read_json_dict(Path(artifacts_dir) / "agent_meta.json") or {}
    row = _find_live_row(name, deps=deps)
    claim = _find_claim(project_file, timestamp) if not is_home else None
    claim_pid = int(claim.pid) if claim is not None else None
    meta_pid = _valid_pid(meta.get("pid"))
    pid = claim_pid or meta_pid
    if pid is None and row is not None:
        pid = _valid_pid(getattr(row, "pid", None))
    workspace_num = (
        int(claim.workspace_num) if claim is not None else _valid_workspace(row)
    )
    workspace_dir = _row_workspace_dir(row) or _meta_workspace_dir(meta)
    if workspace_dir is None and claim is not None:
        workspace_dir = _claim_workspace_dir(project_name, claim)
    status = _row_status(row, artifacts_dir, pid)
    capabilities = meta.get("runner_capabilities")
    capability_list = (
        [str(item) for item in capabilities] if isinstance(capabilities, list) else []
    )
    finalizer = meta.get("finalizer_status")
    phase = None
    if isinstance(finalizer, dict):
        raw_phase = finalizer.get("phase")
        if isinstance(raw_phase, str) and raw_phase:
            phase = raw_phase
    done_outcome, done_recovery = read_done_marker(artifacts_dir)
    trail = meta.get("model_alias_trail")
    is_monitor_turn, is_gate_turn, gate_state = _classify_turn(meta)
    return HijackTarget(
        name=str(getattr(found, "name", name) or name),
        artifacts_dir=artifacts_dir,
        project_name=project_name,
        project_file=project_file,
        artifacts_timestamp=timestamp,
        is_home=is_home,
        pid=pid,
        claim_pid=claim_pid,
        claim_pinned=bool(getattr(claim, "pinned", False)),
        cl_name=(claim.cl_name if claim is not None else None)
        or _meta_str(meta, "patch_name", "cl_name", "changespec_name"),
        workflow=claim.workflow if claim is not None else None,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        status=status,
        lifecycle_phase=phase,
        is_monitor_turn=is_monitor_turn,
        is_gate_turn=is_gate_turn,
        gate_state=gate_state,
        agent_session=getattr(row, "agent_session", None)
        or _meta_str(meta, "agent_session"),
        capabilities=capability_list,
        model_alias=_meta_str(meta, "model_alias"),
        model_alias_trail=[str(item) for item in trail]
        if isinstance(trail, list)
        else [],
        model_origin=_meta_str(meta, "prompt_origin", "model_origin"),
        provider=_meta_str(
            meta,
            "llm_provider",
            "exec_llm_provider",
            "agent_llm_provider",
            "provider",
        ),
        model=_meta_str(meta, "model", "agent_model"),
        effort=_meta_str(meta, "reasoning_effort", "agent_effort", "effort"),
        run_started_at=_meta_epoch(meta, "booted_at", "started_at"),
        done_outcome=done_outcome,
        done_recovery=done_recovery,
    )


def _default_find_agent(name: str) -> Any | None:
    from sase.agent.names import find_named_agent

    return find_named_agent(name)


def _find_live_row(name: str, *, deps: StopDeps) -> Any | None:
    list_running = deps.list_running
    if list_running is None:
        try:
            from sase.agent.running_listing import list_running_agents

            list_running = list_running_agents
        except Exception:
            return None
    try:
        rows = list_running()
    except Exception:
        return None
    for row in rows or ():
        if getattr(row, "name", None) == name and getattr(row, "artifacts_dir", None):
            return row
    return None


def _find_claim(project_file: str, timestamp: str) -> Any | None:
    try:
        from sase.running_field import get_claimed_workspaces

        for claim in get_claimed_workspaces(project_file):
            if claim.artifacts_timestamp == timestamp:
                return claim
    except Exception:
        return None
    return None


def _valid_pid(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 1 else None


def _valid_workspace(row: Any | None) -> int | None:
    if row is None:
        return None
    value = getattr(row, "workspace_num", None)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _row_workspace_dir(row: Any | None) -> str | None:
    if row is None:
        return None
    value = getattr(row, "workspace_dir", None)
    return value if isinstance(value, str) and value else None


def _meta_workspace_dir(meta: dict[str, Any]) -> str | None:
    for key in ("workspace_dir", "workspace_root", "cwd"):
        value = meta.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _claim_workspace_dir(project_name: str, claim: Any) -> str | None:
    try:
        from sase.running_field._workspace import get_workspace_directory_for_num

        directory, _ = get_workspace_directory_for_num(
            int(claim.workspace_num), project_name, clean=False
        )
        return directory
    except Exception:
        return None


def _row_status(row: Any | None, artifacts_dir: str, pid: int | None) -> str:
    if row is not None:
        status = str(getattr(row, "status", "") or "").upper()
        if status:
            return status
    if pid is not None:
        try:
            from sase.agent.process_tree import process_is_running

            if process_is_running(pid):
                return "RUNNING"
        except Exception:
            pass
    return "DONE"


def _classify_turn(meta: dict[str, Any]) -> tuple[bool, bool, str | None]:
    """Classify monitor/gate turns from durable records, never live rows."""
    from sase.core.agent_scan_wire import AgentArtifactRecordWire, AgentMetaWire
    from sase.core.agent_scan_wire_agent_session_turn import (
        agent_session_turn_from_mapping,
    )
    from sase.gate_turn.state import is_real_gate_member
    from sase.monitor.models import is_monitor_member_record
    from sase.plan_chain import agent_session_role_value, turn_kind_value

    role_raw = agent_session_role_value(meta)
    role = role_raw if isinstance(role_raw, str) and role_raw else None
    turn = agent_session_turn_from_mapping(meta)
    gate_id = None
    if (
        turn is not None
        and turn.kind == "gate"
        and isinstance(turn.id, str)
        and turn.id
    ):
        gate_id = turn.id
    elif isinstance(meta.get("gate_id"), str) and meta["gate_id"]:
        gate_id = str(meta["gate_id"])
    is_gate = is_real_gate_member(role, gate_id)
    gate_state: str | None = None
    if is_gate:
        if turn is not None and isinstance(turn.state, str) and turn.state:
            gate_state = turn.state
        else:
            gate_state = _meta_str(meta, "gate_state")
    record = AgentArtifactRecordWire(
        project_name="",
        project_dir="",
        project_file="",
        workflow_dir_name="",
        artifact_dir="",
        timestamp="",
        agent_meta=AgentMetaWire(
            agent_session_role=role,
            agent_session_turn=turn,
        ),
    )
    is_monitor = is_monitor_member_record(record) or (
        turn_kind_value(meta) == "monitor" and turn is not None and bool(turn.id)
    )
    return is_monitor, is_gate, gate_state


def _meta_str(meta: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _meta_epoch(meta: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        parsed = _parse_timestamp(meta.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_timestamp(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


__all__ = [
    "resolve_target",
]
