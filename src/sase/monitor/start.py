"""The ``start`` API used by both the ``sase monitor`` CLI and epic launch."""

from __future__ import annotations

import json
import os
import select
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
    WorkspaceClaim,
    claim_workspace,
    get_claimed_workspaces,
    release_workspace,
    transfer_workspace_claim,
)
from sase.workflows.utils import get_project_file_path

from . import naming, store
from .followup_prompt import DEFAULT_NEXT_OUTPUT, NEXT_OUTPUT_CHOICES
from .identity import process_identity, supervisor_is_alive
from .member import create_monitor_member
from .models import (
    MonitorAlreadyRunningError,
    MonitorError,
    MonitorLaneError,
    MonitorRecord,
)
from .settlement import finalize_monitor_workflow_state, project_name_from_artifacts_dir
from .transaction import (
    MONITOR_GO_MARKER,
    MONITOR_START_ACK_TIMEOUT_SECONDS,
    monitor_go_path,
    monitor_lane_lock_path,
    monitor_started_path,
    write_json_marker_atomic,
)

#: RUNNING-field workflow label used for a monitor's workspace claim, distinct
#: from ``"ace-run"`` so the starter's own runner-exit cleanup no longer
#: matches (and therefore cannot release) the claim once it is transferred.
MONITOR_WORKSPACE_CLAIM_WORKFLOW = "ace-monitor"

DEFAULT_START_STATUS = "MONITORING"
DEFAULT_STOP_STATUS = DEFAULT_MONITOR_STOP_STATUS
DEFAULT_TAIL_LINES = 200
MONITOR_PENDING_MARKER = ".sase_monitor_pending"
SUPERVISOR_LOG_NAME = "supervisor.log"
_SUPERVISOR_BOOTSTRAP_PID_TIMEOUT_SECONDS = 5.0
_SUPERVISOR_STOP_POLL_SECONDS = 0.05
_SUPERVISOR_ACK_POLL_SECONDS = 0.05


class _SupervisorSpawnError(RuntimeError):
    """Raised when the bootstrap process cannot report the real supervisor."""


@dataclass(frozen=True)
class _DetachedSupervisor:
    """The real supervisor is a reparented grandchild, not the Popen child."""

    pid: int
    identity: str | None = None


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
            supervisor = _spawn_detached_supervisor(
                artifacts_dir,
                env=supervisor_env,
                stdout=supervisor_stdout,
            )
        except (OSError, ValueError, _SupervisorSpawnError) as exc:
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
    update_meta_field(artifacts_dir, "pid", supervisor.pid)
    supervisor_identity = process_identity(supervisor.pid)
    update_meta_field(artifacts_dir, "monitor_supervisor_identity", supervisor_identity)
    supervisor = _DetachedSupervisor(supervisor.pid, supervisor_identity)

    member_timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    if transfer_from_pid is not None:
        starter_claim = _find_claim(
            newest.project_file,
            workspace_num=resolved_workspace_num,
            pid=transfer_from_pid,
        )
        claim_result = transfer_workspace_claim(
            newest.project_file,
            resolved_workspace_num,
            from_pid=transfer_from_pid,
            to_pid=supervisor.pid,
            new_workflow=MONITOR_WORKSPACE_CLAIM_WORKFLOW,
            new_artifacts_timestamp=member_timestamp,
            cl_name=raw_meta.get("cl_name"),
        )
    else:
        starter_claim = None
        claim_result = claim_workspace(
            newest.project_file,
            0,
            MONITOR_WORKSPACE_CLAIM_WORKFLOW,
            supervisor.pid,
            raw_meta.get("cl_name"),
            artifacts_timestamp=member_timestamp,
        )
    if not claim_result.success:
        _terminate_supervisor(supervisor)
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
        _terminate_supervisor(supervisor)
        _release_start_claim(
            newest.project_file,
            resolved_workspace_num,
            cl_name=raw_meta.get("cl_name"),
        )
        _teardown_failed_member(
            artifacts_dir, f"could not release monitor launch barrier: {exc}"
        )
        raise MonitorError(f"could not release monitor launch barrier: {exc}") from exc

    ack_error = _wait_for_start_acknowledgement(artifacts_dir, supervisor)
    if ack_error is not None:
        _terminate_supervisor(supervisor)
        _undo_workspace_claim(
            newest.project_file,
            resolved_workspace_num,
            supervisor_pid=supervisor.pid,
            starter_claim=starter_claim,
            cl_name=raw_meta.get("cl_name"),
        )
        _teardown_failed_member(artifacts_dir, ack_error)
        raise MonitorError(ack_error)

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
        pid=supervisor.pid,
        supervisor_identity=supervisor.identity,
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
    write_json_marker_atomic(
        monitor_go_path(artifacts_dir),
        {
            "monitor_id": monitor_id,
            "request_fingerprint": request_fingerprint,
            "timestamp": time.time(),
        },
    )


def _find_claim(
    project_file: str,
    *,
    workspace_num: int,
    pid: int,
) -> WorkspaceClaim | None:
    """Return the live claim for *workspace_num*/*pid*, if any.

    Captured before a forward claim transfer so a later reversal (a missing
    startup acknowledgement) can hand the exact same workflow and artifacts
    timestamp back to the starter instead of guessing at them.
    """
    return next(
        (
            claim
            for claim in get_claimed_workspaces(project_file)
            if claim.workspace_num == workspace_num and claim.pid == pid
        ),
        None,
    )


def _wait_for_start_acknowledgement(
    artifacts_dir: str,
    supervisor: _DetachedSupervisor,
) -> str | None:
    """Block until the supervisor proves it is alive, or return an error.

    Polls the supervisor's own liveness alongside the marker so a supervisor
    that died outright fails fast instead of waiting out the full budget.
    """
    marker_path = monitor_started_path(artifacts_dir)
    deadline = time.monotonic() + MONITOR_START_ACK_TIMEOUT_SECONDS
    while True:
        if marker_path.exists():
            return None
        if not supervisor_is_alive(supervisor.pid, supervisor.identity):
            return (
                "monitor supervisor died without acknowledging startup; "
                "no process group was recorded"
            )
        if time.monotonic() >= deadline:
            return (
                "monitor supervisor did not acknowledge startup within "
                f"{MONITOR_START_ACK_TIMEOUT_SECONDS:g}s"
            )
        time.sleep(_SUPERVISOR_ACK_POLL_SECONDS)


def _undo_workspace_claim(
    project_file: str,
    workspace_num: int,
    *,
    supervisor_pid: int,
    starter_claim: WorkspaceClaim | None,
    cl_name: object,
) -> None:
    """Give a dead-on-arrival supervisor's claim back to the still-live starter.

    A missing acknowledgement means the starter agent -- not the supervisor
    -- is the process that is actually still alive, and it must get its
    workspace back exactly as it held it, never released into the free pool
    where another agent could claim it out from under the starter.
    """
    if starter_claim is not None:
        result = transfer_workspace_claim(
            project_file,
            workspace_num,
            from_pid=supervisor_pid,
            to_pid=starter_claim.pid,
            new_workflow=starter_claim.workflow,
            new_artifacts_timestamp=starter_claim.artifacts_timestamp,
            cl_name=cl_name if isinstance(cl_name, str) else None,
        )
        if result.success:
            return
    _release_start_claim(project_file, workspace_num, cl_name=cl_name)


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
    done_marker: dict[str, Any] = {
        "outcome": "monitored",
        "monitor_state": "failed",
        "error": error,
        "status_label": meta.get("monitor_stop_status") or DEFAULT_STOP_STATUS,
    }
    project_name = project_name_from_artifacts_dir(artifacts_dir)
    if project_name:
        done_marker["project_file"] = get_project_file_path(project_name)
    write_done_marker_and_update_index(artifacts_dir, done_marker)
    finalize_monitor_workflow_state(artifacts_dir)


def _spawn_detached_supervisor(
    artifacts_dir: str,
    *,
    env: dict[str, str],
    stdout: int | BinaryIO,
) -> _DetachedSupervisor:
    """Start the bootstrap and return the reparented supervisor grandchild."""
    read_fd, write_fd = os.pipe()
    launcher: subprocess.Popen[bytes] | None = None
    try:
        launcher = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("supervisor_bootstrap.py")),
                "--artifacts-dir",
                artifacts_dir,
                "--pid-fd",
                str(write_fd),
            ],
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            pass_fds=(write_fd,),
            env=env,
        )
        os.close(write_fd)
        write_fd = -1
        pid = _read_supervisor_pid(read_fd, launcher)
        _wait_for_bootstrap_exit(launcher)
        return _DetachedSupervisor(pid)
    finally:
        for fd in (read_fd, write_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if launcher is not None and launcher.poll() is None:
            _terminate_bootstrap(launcher)


def _read_supervisor_pid(
    read_fd: int,
    launcher: subprocess.Popen[bytes],
) -> int:
    deadline = time.monotonic() + _SUPERVISOR_BOOTSTRAP_PID_TIMEOUT_SECONDS
    chunks: list[bytes] = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_bootstrap(launcher)
            raise _SupervisorSpawnError("timed out waiting for supervisor pid")
        ready, _, _ = select.select([read_fd], [], [], remaining)
        if not ready:
            continue
        chunk = os.read(read_fd, 4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break

    raw = b"".join(chunks).splitlines()[0] if chunks else b""
    if not raw:
        detail = _bootstrap_exit_detail(launcher)
        raise _SupervisorSpawnError(f"bootstrap exited without reporting a pid{detail}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _SupervisorSpawnError(
            "bootstrap reported an invalid pid payload"
        ) from exc
    if not isinstance(payload, dict):
        raise _SupervisorSpawnError("bootstrap reported a non-object pid payload")
    error = payload.get("error")
    if isinstance(error, str) and error:
        raise _SupervisorSpawnError(error)
    try:
        pid = int(payload["pid"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _SupervisorSpawnError("bootstrap did not report a valid pid") from exc
    if pid <= 0:
        raise _SupervisorSpawnError("bootstrap reported a non-positive pid")
    return pid


def _wait_for_bootstrap_exit(launcher: subprocess.Popen[bytes]) -> None:
    try:
        returncode = launcher.wait(timeout=_SUPERVISOR_BOOTSTRAP_PID_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        _terminate_bootstrap(launcher)
        raise _SupervisorSpawnError("bootstrap did not exit after forking") from exc
    if returncode != 0:
        raise _SupervisorSpawnError(f"bootstrap exited with status {returncode}")


def _bootstrap_exit_detail(launcher: subprocess.Popen[bytes]) -> str:
    returncode = launcher.poll()
    if returncode is None:
        return ""
    return f" before exiting with status {returncode}"


def _terminate_bootstrap(launcher: subprocess.Popen[bytes]) -> None:
    try:
        launcher.terminate()
    except (ProcessLookupError, PermissionError):
        pass
    try:
        launcher.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            launcher.kill()
        except (ProcessLookupError, PermissionError):
            pass
        launcher.wait()


def _terminate_supervisor(supervisor: _DetachedSupervisor) -> None:
    try:
        os.kill(supervisor.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    if not _wait_for_supervisor_exit(supervisor, timeout=5.0):
        try:
            os.kill(supervisor.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        _wait_for_supervisor_exit(supervisor, timeout=1.0)


def _wait_for_supervisor_exit(
    supervisor: _DetachedSupervisor,
    *,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not supervisor_is_alive(supervisor.pid, supervisor.identity):
            return True
        time.sleep(_SUPERVISOR_STOP_POLL_SECONDS)
    return not supervisor_is_alive(supervisor.pid, supervisor.identity)


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
