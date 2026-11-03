"""Resolve the live agent row into a hijack target."""

from __future__ import annotations

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
        is_monitor_turn=bool(getattr(row, "is_monitor", False))
        if row is not None
        else False,
        is_gate_turn=_meta_bool(meta, "gate_turn", "is_gate_turn"),
        agent_session=getattr(row, "agent_session", None),
        capabilities=capability_list,
        model_alias=_meta_str(meta, "model_alias"),
        model_alias_trail=[str(item) for item in trail]
        if isinstance(trail, list)
        else [],
        model_origin=_meta_str(meta, "prompt_origin", "model_origin"),
        provider=_meta_str(meta, "agent_llm_provider", "provider"),
        model=_meta_str(meta, "agent_model", "model"),
        effort=_meta_str(meta, "agent_effort", "effort"),
        run_started_at=_meta_float(meta, "booted_at", "started_at"),
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


def _meta_str(meta: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _meta_bool(meta: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, bool):
            return value
    return False


def _meta_float(meta: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


__all__ = [
    "resolve_target",
]
