"""Resumable, idempotent settlement for a named-proc row."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sase.running_field import release_workspace

from .models import (
    PROC_LIFECYCLE_NAMED_PROC,
    TERMINAL_PROC_STATUSES,
    Proc,
    ProcFinish,
    ProcObservedSettlementOutcome,
    ProcSettlement,
    ProcSupervisorClaim,
)
from .runtime import (
    proc_request_sidecar_path,
    proc_runtime_dir,
    proc_settlement_sidecar_path,
    read_json_object,
    write_json_atomic,
)
from .spawn import SUPERVISOR_LOG_NAME
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


def settle_named_proc(
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
    with _settlement_lock(proc_id):
        return _settle_named_proc_locked(
            proc_id,
            supervisor_id=supervisor_id,
            status=status,
            message=message,
            termination_reason=termination_reason,
            exit_code=exit_code,
            result=result,
        )


def observed_command_has_exited(proc: Proc) -> bool:
    """Return whether durable evidence shows the command has already exited."""
    outcome = ProcObservedSettlementOutcome.from_dict(proc.settlement_outcome)
    if outcome is not None and outcome.is_known_command_result():
        return True
    return _sidecar_has_known_outcome(proc.proc_id, supervisor_id=proc.supervisor_id)


def _settle_named_proc_locked(
    proc_id: str,
    *,
    supervisor_id: str,
    status: str,
    message: str,
    termination_reason: str,
    exit_code: int | None,
    result: dict[str, Any] | None,
) -> Proc:
    current = get_proc(proc_id)
    if current is None:
        raise RuntimeError(f"proc {proc_id} disappeared during settlement")
    if current.status in TERMINAL_PROC_STATUSES:
        _release_proc_holds(current)
        return current
    current = _ensure_claimed(current, supervisor_id=supervisor_id)
    owner = current.supervisor_id or supervisor_id
    proposed = ProcObservedSettlementOutcome(
        status=status,
        termination_reason=termination_reason,
        command_ended_at=_utc_timestamp(),
        exit_code=exit_code,
        message=message,
    )
    sidecar = read_json_object(proc_settlement_sidecar_path(proc_id))
    begun = begin_proc_settlement(
        ProcSettlement(
            proc_id=proc_id,
            supervisor_id=owner,
            settling_at=current.settling_started_at or proposed.command_ended_at,
            exit_code=exit_code,
            message=message,
            outcome=proposed,
            sidecar=sidecar or None,
        )
    ).proc
    current = begun or get_proc(proc_id) or current
    maybe_crash("settlement_begun")
    frozen = ProcObservedSettlementOutcome.from_dict(current.settlement_outcome)
    if frozen is not None:
        status = frozen.status
        termination_reason = frozen.termination_reason
        exit_code = frozen.exit_code
        if frozen.message:
            message = frozen.message
        command_ended_at = frozen.command_ended_at
    else:
        command_ended_at = proposed.command_ended_at

    state = _load_settlement_state(current, supervisor_id=owner)
    state["exit_code"] = exit_code
    state["message"] = message
    state["status"] = status
    state["termination_reason"] = termination_reason
    state["command_ended_at"] = command_ended_at
    if result is not None:
        state["result"] = result
    _save_settlement_state(proc_id, state)

    try:
        _run_checkpoint(state, "command_gone", lambda _state: None)
        _run_checkpoint(state, "output_closed", _close_output_checkpoint)
        _run_checkpoint(state, "claim_settled", _settle_workspace_claim)
        from sase.legacy_xprompt_names import prompt_proc_origin_matches

        if prompt_proc_origin_matches(current.origin):
            from sase.agent.launch_proc_runtime import cleanup_prompt_proc_inputs

            cleanup_prompt_proc_inputs(proc_id)

        _run_checkpoint(state, "artifacts_settled", _settle_artifacts)
        _run_checkpoint(state, "followup_settled", _settle_followup)

        status, message, termination_reason = _finalize_operation_result(
            current,
            state,
            status=str(state.get("status") or status),
            message=str(state.get("message") or message),
            termination_reason=str(
                state.get("termination_reason") or termination_reason
            ),
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
    except Exception as exc:
        _record_settlement_error(state, step=_failed_step(state), exc=exc)
        raise

    # Release proc holds before the terminal row is visible, so observers
    # never see success while the proc hold is still stored.
    _release_proc_holds({"proc_id": proc_id, "status": status})
    finished = finish_proc(
        ProcFinish(
            proc_id=proc_id,
            supervisor_id=owner,
            status=status,
            finished_at=_utc_timestamp(),
            exit_code=exit_code,
            message=message,
            result=envelope,
        )
    ).proc
    if finished is None:
        raise RuntimeError(f"proc {proc_id} disappeared before finish")
    _release_proc_holds(finished)
    return finished


def _release_proc_holds(proc: Proc | Mapping[str, Any]) -> None:
    try:
        from sase.core.agent_hold_facade import release_proc_agent_holds

        release_proc_agent_holds(proc)
    except Exception:  # noqa: BLE001 - hold cleanup must never fail settlement
        pass


def maybe_crash(checkpoint: str) -> None:
    """Exit immediately after *checkpoint* when crash injection is enabled."""
    if os.environ.get(_CRASH_AFTER_ENV) == checkpoint:
        os._exit(90)


@contextmanager
def _settlement_lock(proc_id: str) -> Iterator[None]:
    lock_path = proc_runtime_dir(proc_id) / ".settlement.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _run_checkpoint(state: dict[str, Any], checkpoint: Checkpoint, fn: Any) -> None:
    if _already(state, checkpoint):
        return
    fn(state)
    maybe_crash(checkpoint)
    _mark(state, checkpoint)


def _record_settlement_error(
    state: dict[str, Any], *, step: str, exc: BaseException
) -> None:
    proc_id = str(state.get("proc_id") or "")
    error = f"{type(exc).__name__}: {exc}".strip() or type(exc).__name__
    state["settlement_error"] = {
        "step": step,
        "error": error[:500],
        "supervisor_log": str(proc_runtime_dir(proc_id) / SUPERVISOR_LOG_NAME),
    }
    if proc_id:
        _save_settlement_state(proc_id, state)


def _failed_step(state: dict[str, Any]) -> str:
    checkpoints = state.get("checkpoints") or {}
    for name in _CHECKPOINTS:
        if not checkpoints.get(name):
            return name
    return "result_written"


def _sidecar_has_known_outcome(proc_id: str, *, supervisor_id: str | None) -> bool:
    state = read_json_object(proc_settlement_sidecar_path(proc_id))
    if not state:
        return False
    if supervisor_id and state.get("supervisor_id") not in {None, supervisor_id}:
        return False
    reason = state.get("termination_reason")
    status = state.get("status")
    return (
        isinstance(status, str)
        and status in TERMINAL_PROC_STATUSES
        and isinstance(reason, str)
        and reason not in {"", "supervisor-loss", "reboot"}
    )


def is_named_proc_row(proc: Proc) -> bool:
    """Return whether *proc* is a named-proc lifecycle row (either spelling)."""

    # legacy sase-shell spelling: pre-rename rows carry ``proc-shell``.
    return proc.lifecycle in ("named-proc", "proc-shell")


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
            "command_ended_at": state.get("command_ended_at"),
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
    if policy.get("kind") == "tool-run":
        _settle_tool_run_followup(state)
        return
    if state.get("termination_reason") in {"stop", "reboot", "supervisor-loss"}:
        state["followup_outcome"] = "suppressed"
        return
    if state.get("followup_outcome") == "launched":
        return
    state["followup_outcome"] = "pending"


def _settle_tool_run_followup(state: dict[str, Any]) -> None:
    """Settle a hand-off ToolRun from its proc owner; must never wedge settlement."""
    try:
        from sase.tool.settlement import settle_tool_run_followup

        settle_tool_run_followup(state)
    except Exception as exc:  # noqa: BLE001 - a ToolRun error must not block the proc
        state["followup_outcome"] = "tool-run-error"
        state["followup_error"] = str(exc) or type(exc).__name__


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
    "is_named_proc_row",
    "maybe_crash",
    "observed_command_has_exited",
    "settle_named_proc",
]
