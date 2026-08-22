"""Native stand-alone `%proc` dispatch over the existing proc supervisor.

The admission coordinator calls :func:`dispatch_proc_unit` only after waits
and `%if` pass. This module reserves a `proc-shell` with origin
`xprompt-proc`, starts the detached supervisor, and lets that supervisor
acquire an operational lease, materialize a private 0600 script, and settle
the lease. It never allocates an agent, runner, family, or finalizer.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import (
    parse_proc_duration_seconds,
    prepare_proc_script,
    proc_dispatch_wire_schema_version,
    proc_script_argv,
    sanitized_proc_env,
    validate_proc_workspace_intent,
    validate_standalone_proc_shell_name,
    xprompt_proc_origin,
)
from sase.core.agent_launch_wire import (
    LaunchUnitWire,
    ProcUnitWire,
    agent_launch_wire_to_json_dict,
)
from sase.procs.ids import new_proc_id
from sase.procs.models import (
    PROC_LIFECYCLE_PROC_SHELL,
    Proc,
)
from sase.procs.request import ProcSubmitRequest
from sase.procs.runtime import (
    proc_request_sidecar_path,
    proc_runtime_dir,
    read_json_object,
    write_json_atomic,
)
from sase.procs.service import ProcSubmitError, submit_proc_request
from sase.procs.store import get_proc, update_proc

XPROMPT_PROC_ORIGIN = "xprompt-proc"
CANCEL_FILENAME = "cancel"
_PHASE_ACQUIRING = "acquiring-workspace"
_PHASE_PREPARING = "preparing-script"


def dispatch_proc_unit(
    unit: LaunchUnitWire,
    fingerprint: str,
    context: Mapping[str, Any] | None = None,
) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
    """Reserve and start one eligible `%proc` unit. Return its proc id."""

    ctx = dict(context or {})
    if not isinstance(unit.payload, ProcUnitWire):
        return False, None, "not_a_proc_unit", []
    try:
        proc = _submit_unit(unit, fingerprint, ctx)
    except ProcSubmitError as exc:
        return False, None, str(exc), []
    except Exception as exc:
        return False, None, _one_line(exc), []
    current = get_proc(proc.proc_id) or proc
    if current.lifecycle != PROC_LIFECYCLE_PROC_SHELL:
        return False, current.proc_id, "proc_lifecycle_is_not_proc_shell", []
    if current.origin != XPROMPT_PROC_ORIGIN:
        return False, current.proc_id, "proc_origin_is_not_xprompt_proc", []
    from sase.procs.models import TERMINAL_PROC_STATUSES

    if current.status in TERMINAL_PROC_STATUSES:
        prepared = bool((current.xprompt_proc or {}).get("code_digest"))
        if current.status == "success" or prepared:
            return True, current.proc_id, current.message, []
        return False, current.proc_id, current.message or current.status, []
    return True, current.proc_id, None, []


def prepare_xprompt_proc_supervisor(
    proc: Proc,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> str | None:
    """Acquire lease and materialize script before the supervisor acks.

    Returns an error message, or ``None`` when the proc is ready to run.
    Settlement policy is persisted on the request sidecar before return so a
    crash after acknowledgement can still release the lease.
    """

    if proc.origin != XPROMPT_PROC_ORIGIN:
        return None
    sidecar_path = proc_request_sidecar_path(proc.proc_id)
    sidecar = read_json_object(sidecar_path)
    meta = sidecar.get("xprompt_proc")
    if not isinstance(meta, dict):
        return "xprompt-proc request sidecar is missing"
    if _cancelled(cancelled) or proc.stop_requested_at:
        return "proc killed"
    work_dir = proc_runtime_dir(proc.proc_id)
    lease_root: str | None = None
    workspace_num = proc.workspace_num
    project_file = meta.get("project_file")
    if bool(meta.get("workspace")):
        update_proc(proc.proc_id, phase=_PHASE_ACQUIRING)
        if _cancelled(cancelled) or _cancel_requested(work_dir):
            return "proc killed"
        lease = _acquire_lease(proc, meta)
        sidecar["workspace_claim"] = lease.settlement_policy()
        write_json_atomic(sidecar_path, sidecar)
        lease_root = str(lease.checkout_dir)
        workspace_num = lease.workspace_num
        project_file = str(lease.project_file)
        update_proc(
            proc.proc_id,
            cwd=lease_root,
            workspace_num=workspace_num,
            project=proc.project or lease.project,
            cl_name=proc.cl_name or lease.cl_name,
        )
    update_proc(proc.proc_id, phase=_PHASE_PREPARING)
    if _cancelled(cancelled) or _cancel_requested(work_dir):
        return "proc killed"
    python_executable = str(meta.get("python_executable") or sys.executable)
    request = {
        "schema_version": proc_dispatch_wire_schema_version(),
        "logical_id": str(meta.get("logical_id") or proc.proc_id),
        "fingerprint": str(meta.get("fingerprint") or proc.request_fingerprint or ""),
        "code": meta.get("code"),
        "work_dir": str(work_dir),
        "python_executable": python_executable,
        "workspace": bool(meta.get("workspace")),
        "source_cwd": meta.get("source_cwd"),
        "lease_root": lease_root,
        "declared_cwd": meta.get("declared_cwd"),
        "selected_project": proc.project or meta.get("selected_project"),
        "project_file": project_file,
        "workspace_num": workspace_num,
        "proc_id": proc.proc_id,
        "timeout": meta.get("timeout"),
        "idle_timeout": meta.get("idle_timeout"),
        "shell_name": proc.shell_name,
    }
    try:
        prepared = prepare_proc_script(request)
    except Exception as exc:
        return _one_line(exc)
    if list(proc.argv or proc.command) != list(prepared.get("argv") or []):
        return "prepared proc argv does not match the reserved request"
    selected = proc.project or meta.get("selected_project")
    env = sanitized_proc_env(
        proc.proc_id,
        str(prepared.get("cwd") or proc.cwd),
        str(work_dir),
        python_executable,
        selected_project=None if selected is None else str(selected),
        project_file=None if project_file is None else str(project_file),
        workspace_num=workspace_num,
    )
    env["SASE_PROC_LOG_PATH"] = proc.log_path
    sidecar["env"] = env
    sidecar["cwd"] = prepared.get("cwd")
    sidecar["prepared"] = {
        "script_path": prepared.get("script_path"),
        "code_digest": prepared.get("code_digest"),
        "code_preview": prepared.get("code_preview"),
        "code_language": prepared.get("code_language"),
    }
    write_json_atomic(sidecar_path, sidecar)
    xprompt_meta = {
        "logical_id": str(meta.get("logical_id") or ""),
        "code_language": prepared.get("code_language"),
        "code_digest": prepared.get("code_digest"),
        "code_preview": prepared.get("code_preview"),
        "workspace_intent": bool(meta.get("workspace")),
        "cwd_intent": meta.get("declared_cwd"),
        "waits": meta.get("waits"),
        "condition_result": meta.get("condition_result"),
        "launch_receipt": {
            "fingerprint": meta.get("fingerprint"),
            "logical_id": meta.get("logical_id"),
        },
    }
    update_proc(
        proc.proc_id,
        cwd=str(prepared.get("cwd") or proc.cwd),
        phase="running",
        xprompt_proc=xprompt_meta,
    )
    return None


def cleanup_xprompt_proc_inputs(proc_id: str) -> None:
    """Drop private scripts after settlement while keeping digest metadata."""

    from sase.core.agent_launch_facade import cleanup_proc_private_inputs

    cleanup_proc_private_inputs(str(proc_runtime_dir(proc_id)))


def _submit_unit(
    unit: LaunchUnitWire,
    fingerprint: str,
    context: Mapping[str, Any],
) -> Proc:
    payload = unit.payload
    assert isinstance(payload, ProcUnitWire)
    source_cwd = _source_cwd(context)
    declared_cwd = payload.cwd
    workspace = bool(payload.workspace)
    selected_project = payload.selected_project or context.get("selected_project")
    if selected_project is not None:
        selected_project = str(selected_project)
    validate_proc_workspace_intent(workspace, selected_project, declared_cwd)
    validate_standalone_proc_shell_name(payload.shell_name)
    if not workspace:
        from sase.core.agent_launch_facade import resolve_proc_execution_cwd

        cwd = resolve_proc_execution_cwd(
            False,
            declared_cwd=declared_cwd,
            source_cwd=source_cwd,
        )
    else:
        cwd = source_cwd
    python_executable = str(context.get("python_executable") or sys.executable)
    proc_id = new_proc_id()
    work_dir = proc_runtime_dir(proc_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    language = _code_language(payload)
    argv = proc_script_argv(language, str(work_dir), python_executable)
    timeout_seconds = _duration_seconds(payload.timeout)
    idle_timeout_seconds = _duration_seconds(payload.idle_timeout)
    cancel_path = work_dir / CANCEL_FILENAME
    if callable(context.get("cancelled")) and context["cancelled"]():
        raise ProcSubmitError("cancelled")
    xprompt_meta = {
        "logical_id": unit.logical_id,
        "fingerprint": fingerprint,
        "code": agent_launch_wire_to_json_dict(payload.code),
        "workspace": workspace,
        "declared_cwd": declared_cwd,
        "source_cwd": source_cwd,
        "selected_project": selected_project,
        "python_executable": python_executable,
        "timeout": payload.timeout,
        "idle_timeout": payload.idle_timeout,
        "waits": [agent_launch_wire_to_json_dict(wait) for wait in unit.waits],
        "condition_result": context.get("condition_result"),
        "cancel_path": str(cancel_path),
    }
    request = ProcSubmitRequest(
        argv=argv,
        command=[language, payload.code.digest],
        label=payload.label or payload.shell_name or unit.logical_id,
        cwd=cwd,
        origin=xprompt_proc_origin(),
        proc_id=proc_id,
        project=selected_project,
        shell_name=payload.shell_name,
        request_fingerprint=fingerprint,
        reserved_by="launch-admission",
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        xprompt_proc=xprompt_meta,
    )
    return submit_proc_request(
        request,
        after_spawn=lambda _supervisor: _raise_if_cancelled(context, cancel_path),
        after_ack=lambda _proc: _raise_if_cancelled(context, cancel_path),
    )


def _acquire_lease(proc: Proc, meta: Mapping[str, Any]) -> Any:
    from sase.workspace_provider.lease import acquire_operational_lease

    project = proc.project or meta.get("selected_project")
    if not isinstance(project, str) or not project.strip():
        raise ProcSubmitError(
            "workspace=true requires a selected project; workspace 0 is never guessed"
        )
    return acquire_operational_lease(
        project,
        workflow=f"xprompt-proc:{proc.proc_id}",
        holder=proc.proc_id,
        project_file=meta.get("project_file"),
        cl_name=proc.cl_name or proc.shell_name or proc.proc_id,
        pid=os.getpid(),
    )


def _source_cwd(context: Mapping[str, Any]) -> str:
    raw = context.get("source_cwd")
    if raw:
        path = Path(str(raw))
        if path.is_dir():
            return str(path.resolve())
    return str(Path.cwd())


def _code_language(payload: ProcUnitWire) -> str:
    code = payload.code
    language = getattr(code, "language", None)
    if isinstance(language, str) and language.strip():
        return language
    info = getattr(code, "info_string", None)
    if isinstance(info, str) and info.strip():
        return info.split()[0]
    return "bash"


def _duration_seconds(raw: str | None) -> int | None:
    if raw is None or not str(raw).strip():
        return None
    return parse_proc_duration_seconds(str(raw))


def _raise_if_cancelled(context: Mapping[str, Any], cancel_path: Path) -> None:
    if _cancelled(context.get("cancelled")):
        cancel_path.parent.mkdir(parents=True, exist_ok=True)
        cancel_path.write_text("1\n", encoding="utf-8")
        raise ProcSubmitError("cancelled")


def _cancelled(cancelled: Callable[[], bool] | None) -> bool:
    return bool(callable(cancelled) and cancelled())


def _cancel_requested(work_dir: Path) -> bool:
    return (work_dir / CANCEL_FILENAME).is_file()


def _one_line(value: object) -> str:
    return " ".join(str(value).splitlines()) or type(value).__name__


__all__ = [
    "CANCEL_FILENAME",
    "XPROMPT_PROC_ORIGIN",
    "cleanup_xprompt_proc_inputs",
    "dispatch_proc_unit",
    "prepare_xprompt_proc_supervisor",
]
