"""The ``start`` API used by both the ``sase monitor`` CLI and epic launch."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, BinaryIO

from sase.agent.env_hygiene import scrub_agent_identity_env
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.logs._bounded import log_file_lock
from sase.monitor_state import DEFAULT_MONITOR_STOP_STATUS
from sase.plan_chain import agent_family_base
from sase.running_field import (
    claim_workspace,
    release_workspace,
    transfer_workspace_claim,
)

from . import naming, store
from .followup_prompt import DEFAULT_NEXT_OUTPUT, NEXT_OUTPUT_CHOICES
from .identity import process_identity
from .member import create_monitor_member
from .models import (
    MonitorAlreadyRunningError,
    MonitorError,
    MonitorLaneError,
    MonitorRecord,
)
from .transaction import MONITOR_GO_MARKER, monitor_go_path, monitor_lane_lock_path

#: RUNNING-field workflow label used for a monitor's workspace claim, distinct
#: from ``"ace-run"`` so the starter's own runner-exit cleanup no longer
#: matches (and therefore cannot release) the claim once it is transferred.
MONITOR_WORKSPACE_CLAIM_WORKFLOW = "ace-monitor"

DEFAULT_START_STATUS = "MONITORING"
DEFAULT_STOP_STATUS = DEFAULT_MONITOR_STOP_STATUS
DEFAULT_TAIL_LINES = 200
MONITOR_PENDING_MARKER = ".sase_monitor_pending"
SUPERVISOR_LOG_NAME = "supervisor.log"


@dataclass(frozen=True)
class StartMonitorRequest:
    """Fully-resolved request to start one monitor.

    ``project_name`` and ``cwd`` are resolved by the caller (the CLI or the
    host epic-launch path); only the lane is optionally left for
    :func:`start_monitor` to default from the calling agent's own environment.
    """

    command: str
    reason: str
    timeout_seconds: float
    cwd: str
    project_name: str
    lane: str | None = None
    label: str | None = None
    next_action: str | None = None
    start_status: str = DEFAULT_START_STATUS
    stop_status: str = DEFAULT_STOP_STATUS
    tail_lines: int = DEFAULT_TAIL_LINES
    idle_timeout_seconds: float = 0.0
    next_output: str = DEFAULT_NEXT_OUTPUT
    inherit_lane_workspace_claim: bool = True


def start_monitor(request: StartMonitorRequest) -> MonitorRecord:
    """Start (or return the existing) monitor for *request*'s lane."""
    lane = request.lane or store.default_lane()
    if not lane:
        raise MonitorLaneError(
            "no lane given and SASE_AGENT_NAME is unset; pass an explicit lane"
        )

    with log_file_lock(monitor_lane_lock_path(request.project_name, lane)):
        return _start_monitor_locked(request, lane)


def _start_monitor_locked(request: StartMonitorRequest, lane: str) -> MonitorRecord:
    """Start one monitor while the caller holds the lane start lock."""
    label = request.label or _default_label(request.command)
    request_fingerprint = _monitor_request_fingerprint(
        request,
        lane=lane,
        label=label,
    )

    existing_record = store.monitor_blocking_start_for_lane(request.project_name, lane)
    if existing_record is not None:
        if existing_record.monitor_state == "lost":
            if existing_record.request_fingerprint == request_fingerprint:
                short_id = naming.short_monitor_id(existing_record.monitor_id)
                raise MonitorAlreadyRunningError(
                    f"lane {lane!r} has lost monitor {existing_record.monitor_id}; "
                    f"inspect it with `sase monitor show {short_id} --all-lines` "
                    "before replaying the same monitor request"
                )
        elif existing_record.request_fingerprint == request_fingerprint:
            return existing_record
        else:
            raise MonitorAlreadyRunningError(
                _active_monitor_message(
                    lane,
                    existing_record,
                    requested_fingerprint=request_fingerprint,
                    requested_command=request.command,
                )
            )

    lane_ctx = store.resolve_lane(request.project_name, lane)
    newest = lane_ctx.record
    raw_meta = _read_meta(newest.artifact_dir)

    durable_lane = str(raw_meta.get("agent_family") or "")
    if not durable_lane:
        from sase.agent._family_promotion import promote_agent_to_family

        promoted_name = promote_agent_to_family(newest.artifact_dir, lane)
        durable_lane = agent_family_base(promoted_name) or lane
        raw_meta = _read_meta(newest.artifact_dir)

    workspace_dir = raw_meta.get("workspace_dir")
    raw_lane_workspace_num = raw_meta.get("workspace_num")
    raw_runner_pid = raw_meta.get("pid")
    lane_workspace_num = (
        int(raw_lane_workspace_num) if raw_lane_workspace_num is not None else None
    )
    runner_pid = int(raw_runner_pid) if raw_runner_pid is not None else None
    cwd_matches_lane = bool(workspace_dir) and _same_path(
        request.cwd, str(workspace_dir)
    )

    suffix = naming.allocate_monitor_suffix(
        durable_lane,
        has_existing_monitor=store.has_any_monitor(request.project_name, durable_lane),
    )
    monitor_id = naming.new_monitor_id()

    transfer_from_pid: int | None = None
    starter_agent: str | None = None
    if (
        request.inherit_lane_workspace_claim
        and cwd_matches_lane
        and lane_workspace_num is not None
        and runner_pid is not None
    ):
        resolved_workspace_num = lane_workspace_num
        transfer_from_pid = runner_pid
        raw_name = raw_meta.get("name")
        starter_agent = raw_name if isinstance(raw_name, str) and raw_name else None
    else:
        resolved_workspace_num = 0

    artifacts_dir = create_monitor_member(
        request.project_name,
        raw_meta,
        lane=durable_lane,
        suffix=suffix,
        prev_artifacts_timestamp=newest.timestamp,
        workspace_num=resolved_workspace_num,
        monitor_id=monitor_id,
        command=request.command,
        cwd=request.cwd,
        label=label,
        reason=request.reason,
        next_action=request.next_action,
        start_status=request.start_status,
        stop_status=request.stop_status,
        timeout_seconds=request.timeout_seconds,
        tail_lines=request.tail_lines,
        idle_timeout_seconds=request.idle_timeout_seconds,
        next_output=request.next_output,
        request_fingerprint=request_fingerprint,
        starter_agent=starter_agent,
    )

    supervisor_env = os.environ.copy()
    scrub_agent_identity_env(supervisor_env)
    # SASE_ARTIFACTS_DIR does not carry the SASE_AGENT_ prefix the scrubber
    # matches on, but it still names the (possibly dead) starter's own
    # artifacts and must not leak into the detached supervisor.
    supervisor_env.pop("SASE_ARTIFACTS_DIR", None)
    supervisor_log = _open_supervisor_log(artifacts_dir)
    supervisor_stdout: int | BinaryIO = supervisor_log or subprocess.DEVNULL
    try:
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "sase",
                    "monitor",
                    "_supervise",
                    "--artifacts-dir",
                    artifacts_dir,
                ],
                stdin=subprocess.DEVNULL,
                stdout=supervisor_stdout,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                env=supervisor_env,
            )
        except (OSError, ValueError) as exc:
            _teardown_failed_member(
                artifacts_dir, f"could not start monitor supervisor: {exc}"
            )
            raise MonitorError(f"could not start monitor supervisor: {exc}") from exc
    finally:
        if supervisor_log is not None:
            supervisor_log.close()

    # Write the pid before its identity: a crash between these two calls
    # still leaves a pid a caller can signal, and the identity is the
    # stronger of the two, not a substitute. The launch barrier below holds
    # the command behind the claim without reordering this pair.
    update_meta_field(artifacts_dir, "pid", process.pid)
    update_meta_field(
        artifacts_dir, "monitor_supervisor_identity", process_identity(process.pid)
    )

    member_timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    if transfer_from_pid is not None:
        claim_result = transfer_workspace_claim(
            newest.project_file,
            resolved_workspace_num,
            from_pid=transfer_from_pid,
            to_pid=process.pid,
            new_workflow=MONITOR_WORKSPACE_CLAIM_WORKFLOW,
            new_artifacts_timestamp=member_timestamp,
            cl_name=raw_meta.get("cl_name"),
        )
    else:
        claim_result = claim_workspace(
            newest.project_file,
            0,
            MONITOR_WORKSPACE_CLAIM_WORKFLOW,
            process.pid,
            raw_meta.get("cl_name"),
            artifacts_timestamp=member_timestamp,
        )
    if not claim_result.success:
        _terminate_supervisor(process)
        _teardown_failed_member(
            artifacts_dir, f"could not claim workspace: {claim_result.error}"
        )
        raise MonitorError(
            f"could not claim workspace for monitor: {claim_result.error}"
        )

    try:
        _write_monitor_go_marker(
            artifacts_dir,
            monitor_id=monitor_id,
            request_fingerprint=request_fingerprint,
        )
    except OSError as exc:
        _terminate_supervisor(process)
        _release_start_claim(
            newest.project_file,
            resolved_workspace_num,
            cl_name=raw_meta.get("cl_name"),
        )
        _teardown_failed_member(
            artifacts_dir, f"could not release monitor launch barrier: {exc}"
        )
        raise MonitorError(f"could not release monitor launch barrier: {exc}") from exc

    return MonitorRecord(
        monitor_id=monitor_id,
        member_agent_name=f"{durable_lane}{suffix}",
        lane=durable_lane,
        project_name=request.project_name,
        artifacts_dir=artifacts_dir,
        timestamp=member_timestamp,
        command=request.command,
        cwd=request.cwd,
        reason=request.reason,
        label=label,
        start_status=request.start_status,
        stop_status=request.stop_status,
        timeout_seconds=request.timeout_seconds,
        tail_lines=request.tail_lines,
        idle_timeout_seconds=request.idle_timeout_seconds,
        next_output=request.next_output,
        monitor_state="running",
        next_action=request.next_action or None,
        pid=process.pid,
        request_fingerprint=request_fingerprint,
    )


def will_handoff_monitor_to_agent_runner() -> bool:
    """Return whether ``maybe_handoff_monitor_from_agent`` will kill this runner.

    ``kill_agent_runner_group()`` is ``NoReturn``, so any output a caller
    wants to show (a start summary, a ``--json`` envelope) must be emitted
    *before* calling ``maybe_handoff_monitor_from_agent`` -- not after, and
    not conditioned on its return value, which the process never lives to
    observe when this is true.
    """
    return bool(os.environ.get("SASE_AGENT"))


def maybe_handoff_monitor_from_agent(
    record: MonitorRecord,
    *,
    artifacts_dir: str | None = None,
) -> bool:
    """Write the in-agent monitor handoff marker and kill this runner.

    ``start_monitor()`` is shared by host-owned monitor starts and future CLI
    code.  The CLI should call this helper after a record is created; it is a
    no-op outside an agent process and terminates the current runner when
    ``SASE_AGENT`` is set.
    """
    if not os.environ.get("SASE_AGENT"):
        return False

    resolved_artifacts_dir = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not resolved_artifacts_dir:
        raise MonitorError(
            "cannot hand monitor to agent runner: SASE_ARTIFACTS_DIR is unset"
        )

    write_monitor_pending_marker(record, resolved_artifacts_dir)

    from sase.main.utils import kill_agent_runner_group

    kill_agent_runner_group(resolved_artifacts_dir)
    return True


def write_monitor_pending_marker(
    record: MonitorRecord,
    artifacts_dir: str,
    *,
    timestamp: float | None = None,
) -> Path:
    """Persist the pending monitor handoff marker for the runner to adopt."""
    marker_path = Path(artifacts_dir) / MONITOR_PENDING_MARKER
    marker_data = {
        "monitor_id": record.monitor_id,
        "member_artifacts_dir": record.artifacts_dir,
        "member_agent_name": record.member_agent_name,
        "timestamp": time.time() if timestamp is None else timestamp,
    }
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        with marker_path.open("w", encoding="utf-8") as f:
            json.dump(marker_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        raise MonitorError(f"could not write monitor handoff marker: {exc}") from exc

    _touch_agent_artifacts_refresh_pulse(artifacts_dir)
    return marker_path


def _touch_agent_artifacts_refresh_pulse(artifacts_dir: str) -> None:
    try:
        pulse_path = Path(artifacts_dir).parents[1] / ".ace_refresh_pulse"
    except IndexError:
        return
    try:
        pulse_path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def _monitor_request_fingerprint(
    request: StartMonitorRequest,
    *,
    lane: str,
    label: str,
) -> str:
    payload = {
        "command": request.command,
        "cwd": request.cwd,
        "idle_timeout_seconds": request.idle_timeout_seconds,
        "inherit_lane_workspace_claim": request.inherit_lane_workspace_claim,
        "label": label,
        "lane": lane,
        "next_action": request.next_action or None,
        "next_output": request.next_output,
        "project_name": request.project_name,
        "reason": request.reason,
        "start_status": request.start_status,
        "stop_status": request.stop_status,
        "tail_lines": request.tail_lines,
        "timeout_seconds": request.timeout_seconds,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _active_monitor_message(
    lane: str,
    existing_record: MonitorRecord,
    *,
    requested_fingerprint: str,
    requested_command: str,
) -> str:
    if existing_record.command == requested_command:
        existing_fingerprint = (
            existing_record.request_fingerprint or "missing fingerprint"
        )
        return (
            f"lane {lane!r} already has an active monitor "
            f"({existing_record.monitor_id}) with the same command but a "
            "different request "
            f"(existing {existing_fingerprint}, requested {requested_fingerprint})"
        )
    return (
        f"lane {lane!r} already has an active monitor "
        f"({existing_record.monitor_id}): {existing_record.command!r}"
    )


def _write_monitor_go_marker(
    artifacts_dir: str,
    *,
    monitor_id: str,
    request_fingerprint: str,
) -> None:
    marker_path = monitor_go_path(artifacts_dir)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = marker_path.with_name(
        f".{marker_path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "monitor_id": monitor_id,
                    "request_fingerprint": request_fingerprint,
                    "timestamp": time.time(),
                },
                f,
                indent=2,
                sort_keys=True,
            )
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, marker_path)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _release_start_claim(
    project_file: str,
    workspace_num: int,
    *,
    cl_name: object,
) -> None:
    release_workspace(
        project_file,
        workspace_num,
        MONITOR_WORKSPACE_CLAIM_WORKFLOW,
        cl_name=cl_name if isinstance(cl_name, str) else None,
    )


def _teardown_failed_member(artifacts_dir: str, error: str) -> None:
    """Mark a half-created monitor member failed rather than phantom-running."""
    meta = _read_meta(artifacts_dir)
    meta["monitor_state"] = "failed"
    meta["monitor_settled"] = True
    write_agent_meta_atomic(
        artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )
    write_done_marker_and_update_index(
        artifacts_dir,
        {
            "outcome": "monitored",
            "monitor_state": "failed",
            "error": error,
            "status_label": meta.get("monitor_stop_status") or DEFAULT_STOP_STATUS,
        },
    )


def _terminate_supervisor(process: subprocess.Popen[bytes]) -> None:
    try:
        os.kill(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        try:
            os.kill(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        process.wait()


def _open_supervisor_log(artifacts_dir: str) -> BinaryIO | None:
    """Open the detached supervisor's diagnostic stream when possible."""

    try:
        return (Path(artifacts_dir) / SUPERVISOR_LOG_NAME).open("ab")
    except OSError:
        return None


def _same_path(left: str, right: str) -> bool:
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return left == right


def _default_label(command: str) -> str:
    head = command.strip().split(maxsplit=1)[0] if command.strip() else command
    return head[:48]


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise MonitorError(f"agent_meta.json at {artifacts_dir!r} is not an object")
    return data


__all__ = [
    "DEFAULT_NEXT_OUTPUT",
    "DEFAULT_START_STATUS",
    "DEFAULT_STOP_STATUS",
    "DEFAULT_TAIL_LINES",
    "MONITOR_GO_MARKER",
    "MONITOR_PENDING_MARKER",
    "MONITOR_WORKSPACE_CLAIM_WORKFLOW",
    "NEXT_OUTPUT_CHOICES",
    "SUPERVISOR_LOG_NAME",
    "StartMonitorRequest",
    "maybe_handoff_monitor_from_agent",
    "start_monitor",
    "will_handoff_monitor_to_agent_runner",
    "write_monitor_pending_marker",
]
