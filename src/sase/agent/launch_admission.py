"""Durable launch-admission coordinator over the Rust journal planner.

The coordinator is infrastructure owned by a launch-request bundle: it is not
a proc shell, agent, or Agents-tab row. Waiting never claims runners,
workspaces, proc records, or provider capacity. Eligible AgentUnits still
dispatch through the established agent launch path.

The on-disk journal lives in ``launch_admission_store``, the in-process
driver in ``launch_admission_engine``, and wait resolution plus unit
dispatch in ``launch_admission_runtime``.
"""

from __future__ import annotations

import fcntl
import os
import signal
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.launch_admission_engine import (
    AdmissionEngine,
    AdmissionProgress,
    request_safe_inputs,
    request_source_cwd,
    typed_plan_from_request,
)
from sase.agent.launch_admission_runtime import (
    ConditionEvaluator,
    UnitDispatcher,
    WaitResolver,
)
from sase.agent.launch_admission_store import (
    ADMISSION_DIRNAME,
    COORDINATOR_ENV,
    COORDINATOR_LOG_FILENAME,
    LOCK_FILENAME,
    POLL_SECONDS,
    RECEIPT_FILENAME,
    SIDECAR_FILENAME,
    START_ACK_TIMEOUT_SECONDS,
    STARTED_FILENAME,
    STOP_KILL_SECONDS,
    STOP_TERM_SECONDS,
    admission_dir,
    read_json,
    write_sidecar,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.agent.launch_request_types import ApprovedLaunchDispatchResult
from sase.core.agent_launch_wire import (
    LaunchAdmissionSummaryWire,
    LaunchPlanWire,
    LaunchUnitWire,
    ProcUnitWire,
)
from sase.monitor.transaction import write_json_marker_atomic


def dispatch_typed_launch_request(
    response_dir: Path,
    data: Mapping[str, Any],
    *,
    until_blocked: bool = True,
    wait_resolver: WaitResolver | None = None,
    condition_evaluator: ConditionEvaluator | None = None,
    agent_dispatcher: UnitDispatcher | None = None,
    proc_dispatcher: UnitDispatcher | None = None,
    spawn_coordinator: bool = True,
    cancelled: Callable[[], bool] | None = None,
) -> ApprovedLaunchDispatchResult:
    """Admit an approved typed plan, detaching only when waits remain."""

    plan = typed_plan_from_request(data)
    request_id = str(data.get("request_id") or "")
    root = admission_dir(response_dir)
    lock_path = root / LOCK_FILENAME
    root.mkdir(parents=True, exist_ok=True)
    agent_dispatcher = agent_dispatcher or _agent_dispatcher_for_request(
        data, response_dir
    )
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            write_sidecar(root, data, plan)
            engine = AdmissionEngine(
                plan=plan,
                admission_dir=root,
                request_id=request_id,
                wait_resolver=wait_resolver,
                condition_evaluator=condition_evaluator,
                agent_dispatcher=agent_dispatcher,
                proc_dispatcher=proc_dispatcher,
                cancelled=cancelled or (lambda: False),
                source_cwd=request_source_cwd(data),
                safe_inputs=request_safe_inputs(data),
            )
            progress = engine.run(until_blocked=until_blocked)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    if spawn_coordinator and not progress.complete:
        from sase.agent.launch_admission_coordinator import start_detached_coordinator

        start_detached_coordinator(response_dir)
    elif progress.complete and _should_notify_admission_complete(data, plan, progress):
        _notify_admission_complete(request_id, progress, root / RECEIPT_FILENAME)
    return _dispatch_result(request_id, progress)


def run_coordinator_in_bundle(
    response_dir: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> AdmissionProgress:
    """Reconcile and finish an approved bundle as the detached coordinator."""

    from sase.agent.launch_request_response import read_launch_request

    data = read_launch_request(response_dir)
    plan = typed_plan_from_request(data)
    agent_dispatcher = _agent_dispatcher_for_request(data, response_dir)
    root = admission_dir(response_dir)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / LOCK_FILENAME
    stop = cancelled or (lambda: False)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            write_json_marker_atomic(
                root / STARTED_FILENAME,
                {
                    "pid": os.getpid(),
                    "request_id": str(data.get("request_id") or ""),
                    "plan_digest": plan.content_digest,
                    "started_at_unix": time.time(),
                },
            )
            engine = AdmissionEngine(
                plan=plan,
                admission_dir=root,
                request_id=str(data.get("request_id") or ""),
                cancelled=stop,
                agent_dispatcher=agent_dispatcher,
                source_cwd=request_source_cwd(data),
                safe_inputs=request_safe_inputs(data),
            )
            progress = engine.run(until_blocked=False)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    if _should_notify_admission_complete(data, plan, progress):
        _notify_admission_complete(
            str(data.get("request_id") or ""),
            progress,
            root / RECEIPT_FILENAME,
        )
    return progress


def stop_launch_admission(response_dir: Path) -> None:
    """Escalate SIGTERM then SIGKILL against a live admission coordinator."""

    sidecar = read_json(admission_dir(response_dir) / SIDECAR_FILENAME)
    pid = sidecar.get("pid") if isinstance(sidecar, dict) else None
    if not isinstance(pid, int) or pid <= 0:
        return
    _escalate_pid(pid)


def install_coordinator_signal_flag() -> Callable[[], bool]:
    cancelled = threading.Event()

    def _handle(signum: int, frame: object) -> None:
        del signum, frame
        cancelled.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)
    return cancelled.is_set


def _format_admission_summary(summary: LaunchAdmissionSummaryWire) -> str:
    return (
        f"{summary.total} total, {summary.eligible} eligible, "
        f"{summary.launched} launched, {summary.skipped} skipped, "
        f"{summary.condition_errors} condition error(s), "
        f"{summary.launch_errors} launch error(s)"
    )


def _dispatch_result(
    request_id: str,
    progress: AdmissionProgress,
) -> ApprovedLaunchDispatchResult:
    return ApprovedLaunchDispatchResult(
        request_id=request_id,
        results=list(progress.results),
        summary=progress.summary,
        unit_results=progress.unit_results,
        plan_digest=str(progress.receipt.get("plan_digest") or ""),
        admission_complete=progress.complete,
    )


def _agent_dispatcher_for_request(
    data: Mapping[str, Any], response_dir: Path
) -> UnitDispatcher | None:
    from sase.axe.chop_typed_admission import (
        is_axe_chop_typed_request,
        make_axe_chop_agent_dispatcher,
    )

    if is_axe_chop_typed_request(data):
        dispatcher = make_axe_chop_agent_dispatcher(data, bundle_dir=response_dir)
        if dispatcher is not None:
            return dispatcher

        def _missing_metadata(
            unit: LaunchUnitWire,
            fingerprint: str,
        ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
            del fingerprint
            return (
                False,
                None,
                f"missing AXE chop dispatch metadata for {unit.logical_id}",
                [],
            )

        return _missing_metadata
    return None


def _should_notify_admission_complete(
    data: Mapping[str, Any],
    plan: LaunchPlanWire,
    progress: AdmissionProgress,
) -> bool:
    try:
        from sase.axe.chop_typed_admission import is_axe_chop_typed_request

        if is_axe_chop_typed_request(data):
            return False
    except Exception:
        return True
    if _is_clean_proc_only_admission(plan, progress):
        return False
    return True


def _is_clean_proc_only_admission(
    plan: LaunchPlanWire,
    progress: AdmissionProgress,
) -> bool:
    unit_count = len(plan.units)
    if unit_count == 0:
        return False
    if not all(isinstance(unit.payload, ProcUnitWire) for unit in plan.units):
        return False
    summary = progress.summary
    if (
        not progress.complete
        or summary.total != unit_count
        or summary.eligible != unit_count
        or summary.launched != unit_count
        or summary.skipped != 0
        or summary.condition_errors != 0
        or summary.launch_errors != 0
        or len(progress.unit_results) != unit_count
    ):
        return False
    return all(result.outcome == "launched" for result in progress.unit_results)


def _notify_admission_complete(
    request_id: str,
    progress: AdmissionProgress,
    receipt_path: Path,
) -> None:
    try:
        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="launch.admission",
            cl_name=None,
            success=(
                progress.summary.condition_errors == 0
                and progress.summary.launch_errors == 0
            ),
            notes=[
                f"Launch admission finished for `{request_id}`",
                _format_admission_summary(progress.summary),
            ],
            extra_files=[str(receipt_path)],
            tags=["launch"],
        )
    except Exception:
        return


def _escalate_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + STOP_TERM_SECONDS
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            return
        time.sleep(POLL_SECONDS)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return
    kill_deadline = time.monotonic() + STOP_KILL_SECONDS
    while time.monotonic() < kill_deadline:
        if not _pid_is_running(pid):
            return
        time.sleep(POLL_SECONDS)


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
    except (OSError, IndexError):
        return True
    return state != "Z"


__all__ = [
    "ADMISSION_DIRNAME",
    "COORDINATOR_ENV",
    "COORDINATOR_LOG_FILENAME",
    "STARTED_FILENAME",
    "START_ACK_TIMEOUT_SECONDS",
    "admission_dir",
    "dispatch_typed_launch_request",
    "install_coordinator_signal_flag",
    "run_coordinator_in_bundle",
    "stop_launch_admission",
]
