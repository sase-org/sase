"""Resumable, idempotent settlement for a proc-shell row."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sase.running_field import release_workspace

from .models import (
    PROC_LIFECYCLE_PROC_SHELL,
    TERMINAL_PROC_STATUSES,
    Proc,
    ProcFinish,
    ProcSettlement,
    ProcSupervisorClaim,
)
from .runtime import (
    proc_request_sidecar_path,
    proc_settlement_sidecar_path,
    read_json_object,
    write_json_atomic,
)
from .store import begin_proc_settlement, claim_proc_supervisor, finish_proc, get_proc

_SETTLEMENT_SCHEMA_VERSION = 1
_CRASH_AFTER_ENV = "SASE_PROC_SUPERVISOR_CRASH_AFTER"

Checkpoint = Literal[
    "command_gone",
    "output_closed",
    "result_written",
    "claim_settled",
    "artifacts_settled",
    "followup_settled",
]
_CHECKPOINTS: tuple[Checkpoint, ...] = (
    "command_gone",
    "output_closed",
    "claim_settled",
    "artifacts_settled",
    "followup_settled",
    "result_written",
)


def settle_proc_shell(
    proc_id: str,
    *,
    supervisor_id: str,
    status: str,
    message: str,
    termination_reason: str,
    exit_code: int | None = None,
    result: dict[str, Any] | None = None,
) -> Proc:
    """Run remaining settlement checkpoints, then publish the terminal row."""
    current = get_proc(proc_id)
    if current is None:
        raise RuntimeError(f"proc {proc_id} disappeared during settlement")
    if current.status in TERMINAL_PROC_STATUSES:
        return current
    current = _ensure_claimed(current, supervisor_id=supervisor_id)
    if current.status != "settling":
        begin_proc_settlement(
            ProcSettlement(
                proc_id=proc_id,
                supervisor_id=supervisor_id,
                settling_at=_utc_timestamp(),
                exit_code=exit_code,
                message=message,
            )
        )
        current = get_proc(proc_id) or current

    state = _load_settlement_state(current, supervisor_id=supervisor_id)
    state["exit_code"] = exit_code
    state["message"] = message
    state["status"] = status
    state["termination_reason"] = termination_reason
    if result is not None:
        state["result"] = result
    _save_settlement_state(proc_id, state)
    maybe_crash("command_gone")
    _mark(state, "command_gone")

    _close_output_checkpoint(state)
    maybe_crash("output_closed")
    _mark(state, "output_closed")

    _settle_workspace_claim(state)
    maybe_crash("claim_settled")
    _mark(state, "claim_settled")

    _settle_artifacts(state)
    maybe_crash("artifacts_settled")
    _mark(state, "artifacts_settled")

    _settle_followup(state)
    maybe_crash("followup_settled")
    _mark(state, "followup_settled")

    status, message, termination_reason = _finalize_operation_result(
        current,
        state,
        status=status,
        message=message,
        termination_reason=termination_reason,
    )
    state["status"] = status
    state["message"] = message
    state["termination_reason"] = termination_reason
    _save_settlement_state(proc_id, state)

    envelope = _result_envelope(current, state)
    if not state.get("operation"):
        _write_result_envelope(current, state, envelope)
    maybe_crash("result_written")
    _mark(state, "result_written")

    finished = finish_proc(
        ProcFinish(
            proc_id=proc_id,
            supervisor_id=supervisor_id,
            status=status,
            finished_at=_utc_timestamp(),
            exit_code=exit_code,
            message=message,
            result=envelope,
        )
    ).proc
    if finished is None:
        raise RuntimeError(f"proc {proc_id} disappeared before finish")
    return finished


def maybe_crash(checkpoint: str) -> None:
    """Exit immediately after *checkpoint* when crash injection is enabled."""
    if os.environ.get(_CRASH_AFTER_ENV) == checkpoint:
        os._exit(90)


def is_proc_shell_row(proc: Proc) -> bool:
    return proc.lifecycle == PROC_LIFECYCLE_PROC_SHELL


def _ensure_claimed(proc: Proc, *, supervisor_id: str) -> Proc:
    if proc.supervisor_id:
        return proc
    claimed = claim_proc_supervisor(
        ProcSupervisorClaim(
            proc_id=proc.proc_id,
            supervisor_id=supervisor_id,
            claimed_at=_utc_timestamp(),
            pid=proc.pid,
            pgid=proc.pgid,
        )
    ).proc
    return claimed or proc


def _load_settlement_state(proc: Proc, *, supervisor_id: str) -> dict[str, Any]:
    path = proc_settlement_sidecar_path(proc.proc_id)
    state = read_json_object(path)
    request = read_json_object(proc_request_sidecar_path(proc.proc_id))
    if not state:
        state = {
            "schema_version": _SETTLEMENT_SCHEMA_VERSION,
            "argv": list(proc.argv or proc.command),
            "artifacts_dir": request.get("artifacts_dir"),
            "checkpoints": dict.fromkeys(_CHECKPOINTS, False),
            "cwd": proc.cwd,
            "followup": request.get("followup"),
            "log_path": proc.log_path,
            "operation": request.get("operation"),
            "proc_id": proc.proc_id,
            "request_path": request.get("request_path"),
            "result_path": request.get("result_path"),
            "supervisor_id": supervisor_id,
            "workspace_claim": request.get("workspace_claim"),
        }
    checkpoints = state.setdefault("checkpoints", {})
    for name in _CHECKPOINTS:
        checkpoints.setdefault(name, False)
    state.setdefault("artifacts_dir", request.get("artifacts_dir"))
    state.setdefault("followup", request.get("followup"))
    state.setdefault("operation", request.get("operation"))
    state.setdefault("request_path", request.get("request_path"))
    state.setdefault("result_path", request.get("result_path"))
    state.setdefault("workspace_claim", request.get("workspace_claim"))
    state["log_path"] = proc.log_path
    state["supervisor_id"] = supervisor_id
    return state


def _save_settlement_state(proc_id: str, state: dict[str, Any]) -> None:
    write_json_atomic(proc_settlement_sidecar_path(proc_id), state)


def _mark(state: dict[str, Any], checkpoint: Checkpoint) -> None:
    checkpoints = state.setdefault("checkpoints", {})
    checkpoints[checkpoint] = True
    _save_settlement_state(str(state["proc_id"]), state)


def _already(state: dict[str, Any], checkpoint: Checkpoint) -> bool:
    checkpoints = state.get("checkpoints") or {}
    return bool(checkpoints.get(checkpoint))


def _close_output_checkpoint(state: dict[str, Any]) -> None:
    if _already(state, "output_closed"):
        return
    log_path = state.get("log_path")
    if not isinstance(log_path, str) or not log_path:
        return
    path = Path(log_path)
    try:
        with path.open("ab") as handle:
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass


def _result_envelope(proc: Proc, state: dict[str, Any]) -> dict[str, Any]:
    existing = state.get("result")
    envelope = dict(existing) if isinstance(existing, dict) else {}
    envelope.update(
        {
            "argv": list(proc.argv or proc.command),
            "cwd": proc.cwd,
            "exit_code": state.get("exit_code"),
            "followup": state.get("followup_outcome"),
            "log_path": proc.log_path,
            "message": state.get("message"),
            "proc_id": proc.proc_id,
            "schema_version": _SETTLEMENT_SCHEMA_VERSION,
            "status": state.get("status"),
            "termination_reason": state.get("termination_reason"),
        }
    )
    return envelope


def _finalize_operation_result(
    proc: Proc,
    state: dict[str, Any],
    *,
    status: str,
    message: str,
    termination_reason: str,
) -> tuple[str, str, str]:
    """Validate or publish the typed command result before terminalizing.

    A successful command without a required valid result settles as an explicit
    durable error. Failure, kill, and timeout still produce a valid error
    envelope and never infer payload data from logs.
    """
    operation = state.get("operation")
    result_path = state.get("result_path")
    if not isinstance(operation, str) or not operation:
        return status, message, termination_reason
    if not isinstance(result_path, str) or not result_path:
        if status == "success":
            return (
                "error",
                "operation succeeded without a configured result path",
                "missing-result",
            )
        return status, message, termination_reason

    from sase.ops import (
        DurableOperationResult,
        OperationIOError,
        read_operation_result,
        write_operation_result,
    )

    parsed: DurableOperationResult | None
    read_error: OperationIOError | None
    try:
        parsed = read_operation_result(
            result_path,
            expected_operation=operation,
            expected_proc_id=proc.proc_id,
        )
    except OperationIOError as exc:
        parsed = None
        read_error = exc
    else:
        read_error = None

    if (
        parsed is not None
        and parsed.success
        and termination_reason
        in {
            "supervisor-loss",
            "reboot",
        }
    ):
        return "success", parsed.message or message, "success"

    if status == "success":
        if parsed is None:
            assert read_error is not None
            error = DurableOperationResult(
                operation=operation,
                proc_id=proc.proc_id,
                success=False,
                message=str(read_error),
                error=str(read_error),
            )
            write_operation_result(result_path, error)
            return "error", str(read_error), "missing-result"
        if not parsed.success:
            return (
                "error",
                parsed.message or parsed.error or "operation reported failure",
                "operation-error",
            )
        return status, parsed.message or message, termination_reason

    if parsed is None:
        error = DurableOperationResult(
            operation=operation,
            proc_id=proc.proc_id,
            success=False,
            message=message,
            error=message,
        )
        write_operation_result(result_path, error)
    return status, message, termination_reason


def _write_result_envelope(
    proc: Proc,
    state: dict[str, Any],
    envelope: dict[str, Any],
) -> None:
    if _already(state, "result_written"):
        return
    result_path = state.get("result_path")
    if not isinstance(result_path, str) or not result_path:
        return
    path = Path(result_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    encoded = json.dumps(envelope, indent=2, sort_keys=True).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, 0o600)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _settle_workspace_claim(state: dict[str, Any]) -> None:
    if _already(state, "claim_settled"):
        return
    policy = state.get("workspace_claim")
    if not isinstance(policy, dict) or not policy:
        return
    from sase.workspace_provider.lease import (
        OPERATIONAL_LEASE_POLICY_KIND,
        is_operational_lease_policy,
        release_operational_lease,
    )

    if policy.get(
        "kind"
    ) == OPERATIONAL_LEASE_POLICY_KIND or is_operational_lease_policy(policy):
        release_operational_lease(policy)
        return
    if _looks_like_monitor_settlement(state):
        return
    project_file = policy.get("project_file")
    workspace_num = policy.get("workspace_num")
    if not isinstance(project_file, str) or workspace_num is None:
        return
    workflow = policy.get("workflow")
    cl_name = policy.get("cl_name")
    release_workspace(
        project_file,
        int(workspace_num),
        workflow=workflow if isinstance(workflow, str) else None,
        cl_name=cl_name if isinstance(cl_name, str) else None,
    )


def _settle_artifacts(state: dict[str, Any]) -> None:
    if _already(state, "artifacts_settled"):
        return
    artifacts_dir = state.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return
    if _looks_like_monitor_settlement(state):
        from sase.monitor.proc_adapter import settle_monitor_artifacts

        settle_monitor_artifacts(state)
    path = Path(artifacts_dir) / ".proc_settled.json"
    write_json_atomic(
        path,
        {
            "log_path": state.get("log_path"),
            "proc_id": state.get("proc_id"),
            "status": state.get("status"),
            "termination_reason": state.get("termination_reason"),
        },
    )


def _settle_followup(state: dict[str, Any]) -> None:
    if _already(state, "followup_settled"):
        return
    if _looks_like_monitor_settlement(state):
        from sase.monitor.proc_adapter import settle_monitor_followup

        settle_monitor_followup(state)
        return
    policy = state.get("followup")
    if not isinstance(policy, dict) or not policy:
        state["followup_outcome"] = None
        return
    if state.get("termination_reason") in {"stop", "reboot", "supervisor-loss"}:
        state["followup_outcome"] = "suppressed"
        return
    if state.get("followup_outcome") == "launched":
        return
    state["followup_outcome"] = "pending"


def _looks_like_monitor_settlement(state: dict[str, Any]) -> bool:
    """Detect monitor settlement without importing the monitor package."""
    followup = state.get("followup")
    if isinstance(followup, dict) and followup.get("kind") == "monitor":
        return True
    artifacts_dir = state.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return False
    try:
        with open(
            os.path.join(artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as handle:
            meta = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    return isinstance(meta, dict) and bool(meta.get("monitor_id"))


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "is_proc_shell_row",
    "maybe_crash",
    "settle_proc_shell",
]
