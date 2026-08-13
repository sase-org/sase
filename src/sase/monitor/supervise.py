"""Detached supervisor process for one monitor family member.

Invoked as ``python -m sase.monitor.supervise --artifacts-dir <dir>``, mirroring
:mod:`sase.tasks.supervisor`. Owns the monitored command from spawn through the
terminal marker: streams its merged output, enforces the timeout, and reacts
to ``SIGTERM`` (sent by :func:`sase.monitor.store.stop_monitor`) by killing
the command's whole process group rather than just itself.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from sase.agent.env_hygiene import scrub_agent_identity_env
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.paths import sase_projects_dir
from sase.history.chat import save_chat_history
from sase.logs.pipe import BoundedLogPipe
from sase.notifications.senders import notify_workflow_complete
from sase.running_field import release_workspace

from .followup import launch_followup_agent
from .logs import append_monitor_log_bytes, monitor_log_max_bytes, monitor_log_path
from .models import MonitorState
from .output import OutputCapture

_POLL_SECONDS = 0.05
_KILL_GRACE_SECONDS = 5.0
_TimeoutKind = Literal["total", "idle"]


class _Termination:
    """Forward stop/timeout signals to the monitored command's process group."""

    def __init__(self) -> None:
        self.requested = False
        self.child: subprocess.Popen[bytes] | None = None
        self.kill_deadline: float | None = None

    def request(self, _signum: int, _frame: object) -> None:
        self.requested = True
        self._signal_child()

    def trigger_timeout(self) -> None:
        self._signal_child()

    def attach(self, child: subprocess.Popen[bytes]) -> None:
        self.child = child
        if self.requested:
            self._signal_child()

    def maybe_escalate(self) -> None:
        if (
            self.kill_deadline is not None
            and self.child is not None
            and self.child.poll() is None
            and time.monotonic() >= self.kill_deadline
        ):
            _signal_group(self.child.pid, signal.SIGKILL)
            self.kill_deadline = None

    def _signal_child(self) -> None:
        if self.child is not None and self.child.poll() is None:
            _signal_group(self.child.pid, signal.SIGTERM)
            self.kill_deadline = time.monotonic() + _KILL_GRACE_SECONDS

    def terminate_after_failure(self) -> None:
        """Best-effort TERM->KILL cleanup for an internally failing supervisor."""
        if self.child is None or self.child.poll() is not None:
            return
        _signal_group(self.child.pid, signal.SIGTERM)
        try:
            self.child.wait(timeout=_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _signal_group(self.child.pid, signal.SIGKILL)
            self.child.wait()


class _OutputActivity:
    """Track output arrival from the drain thread for idle-timeout checks."""

    def __init__(self, capture: OutputCapture) -> None:
        self._capture = capture
        self._lock = threading.Lock()
        self._last_chunk_at = time.monotonic()

    def append_bytes(self, chunk: bytes) -> None:
        self._capture.append_bytes(chunk)
        with self._lock:
            self._last_chunk_at = time.monotonic()

    def idle_seconds(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_chunk_at


def _signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def run_supervisor(artifacts_dir: str) -> int:
    """Own one monitor member from command spawn through terminal marker."""
    meta = _read_meta(artifacts_dir)
    if meta.get("monitor_state") != "running":
        return 0

    command = str(meta["monitor_command"])
    cwd = str(meta["monitor_cwd"])
    timeout_seconds = float(meta.get("monitor_timeout_seconds") or 0.0)
    idle_timeout_seconds = float(meta.get("monitor_idle_timeout_seconds") or 0.0)

    termination = _Termination()
    signal.signal(signal.SIGTERM, termination.request)
    signal.signal(signal.SIGINT, termination.request)

    output_path = monitor_log_path(artifacts_dir)
    capture = OutputCapture()
    activity = _OutputActivity(capture)
    started = time.monotonic()
    monitor_state: MonitorState = "failed"
    exit_code: int | None = None
    error: str | None = None
    timeout_kind: _TimeoutKind | None = None
    output_pipe: BoundedLogPipe | None = None

    try:
        output_pipe = BoundedLogPipe(
            output_path,
            monitor_log_max_bytes(),
            on_chunk=activity.append_bytes,
            close_drain_seconds=0.5,
        )
        command_env = os.environ.copy()
        scrub_agent_identity_env(command_env)
        # SASE_ARTIFACTS_DIR does not carry the SASE_AGENT_ prefix the
        # scrubber matches on, but it still names the dead starter's
        # artifacts and must not leak into the monitored command.
        command_env.pop("SASE_ARTIFACTS_DIR", None)
        try:
            child = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=cast(Any, output_pipe),
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                text=False,
                env=command_env,
            )
        except (OSError, ValueError) as exc:
            error = f"could not start command: {_one_line(exc)}"
            _append_supervisor_line(output_path, output_pipe, capture, error)
        else:
            termination.attach(child)
            # Persist the child's pgid before waiting on it, so nothing can
            # outlive this recorder: start_new_session=True makes the pgid
            # equal the child's own pid.
            meta["monitor_pgid"] = child.pid
            write_agent_meta_atomic(
                artifacts_dir,
                meta,
                index_updater=update_agent_artifact_index_for_marker_mutation,
            )
            timeout_kind = _wait_for_child(
                child,
                termination,
                timeout_seconds,
                idle_timeout_seconds,
                activity,
            )

            if termination.requested:
                monitor_state = "stopped"
            elif timeout_kind is not None:
                monitor_state = "timeout"
            elif child.returncode == 0:
                monitor_state = "completed"
            else:
                monitor_state = "failed"
            exit_code = child.returncode
    except BaseException as exc:
        termination.terminate_after_failure()
        error = f"supervisor error: {_one_line(exc)}"
        _append_supervisor_line(output_path, output_pipe, capture, error)
    finally:
        close_error = _close_output_pipe(output_pipe)
        if close_error is not None:
            error = error or f"supervisor error: {_one_line(close_error)}"
            monitor_state = "failed"
            _append_supervisor_line(output_path, None, capture, error)
        _finish_monitor(
            artifacts_dir,
            meta,
            monitor_state=monitor_state,
            exit_code=exit_code,
            elapsed_seconds=time.monotonic() - started,
            capture=capture,
            error=error,
            timeout_kind=timeout_kind,
        )
    return 0 if monitor_state in {"completed", "stopped"} else 1


def _wait_for_child(
    child: subprocess.Popen[bytes],
    termination: _Termination,
    timeout_seconds: float,
    idle_timeout_seconds: float,
    activity: _OutputActivity,
) -> _TimeoutKind | None:
    """Wait for process exit; return which timeout budget fired, if any."""
    deadline = time.monotonic() + timeout_seconds if timeout_seconds > 0 else None
    timeout_kind: _TimeoutKind | None = None
    while True:
        if child.poll() is not None:
            return timeout_kind
        now = time.monotonic()
        if deadline is not None and timeout_kind is None and now >= deadline:
            timeout_kind = "total"
            termination.trigger_timeout()
        if (
            idle_timeout_seconds > 0
            and timeout_kind is None
            and activity.idle_seconds() >= idle_timeout_seconds
        ):
            timeout_kind = "idle"
            termination.trigger_timeout()
        termination.maybe_escalate()
        time.sleep(_POLL_SECONDS)


def _close_output_pipe(output_pipe: BoundedLogPipe | None) -> BaseException | None:
    if output_pipe is None or output_pipe.closed:
        return None
    try:
        output_pipe.close()
    except BaseException as exc:
        return exc
    return None


def _append_supervisor_line(
    output_path: Path,
    output_pipe: BoundedLogPipe | None,
    capture: OutputCapture,
    message: str,
) -> None:
    line = f"{message.rstrip()}\n"
    if output_pipe is not None and not output_pipe.closed:
        try:
            output_pipe.write(line)
            return
        except (OSError, ValueError):
            pass
    encoded = line.encode("utf-8", errors="replace")
    capture.append_bytes(encoded)
    try:
        append_monitor_log_bytes(output_path, encoded)
    except OSError:
        pass


def _finish_monitor(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: MonitorState,
    exit_code: int | None,
    elapsed_seconds: float,
    capture: OutputCapture,
    error: str | None,
    timeout_kind: _TimeoutKind | None,
) -> None:
    """Write the terminal marker, save chat history, and settle the claim."""
    stop_status = str(meta.get("monitor_stop_status") or "MONITORED")
    retained = capture.retained_text()

    meta["monitor_state"] = monitor_state
    if exit_code is not None:
        meta["monitor_exit_code"] = exit_code
    meta["monitor_output_truncated"] = capture.truncated
    meta["stopped_at"] = _utc_now_iso()
    timeout_message = _timeout_message(
        timeout_kind,
        total_timeout_seconds=float(meta.get("monitor_timeout_seconds") or 0.0),
        idle_timeout_seconds=float(meta.get("monitor_idle_timeout_seconds") or 0.0),
        elapsed_seconds=elapsed_seconds,
    )
    if timeout_kind is not None:
        meta["monitor_timeout_kind"] = timeout_kind
        if timeout_message:
            meta["monitor_timeout_message"] = timeout_message
    write_agent_meta_atomic(
        artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )

    member_name = str(meta.get("name") or "")
    timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    response_path = save_chat_history(
        f"sase monitor start --command {meta.get('monitor_command')!r} "
        f"--reason {meta.get('monitor_reason')!r}",
        retained,
        "ace-run",
        agent=member_name,
        timestamp=timestamp,
        branch_or_workspace=meta.get("cl_name"),
        metadata_agent=member_name,
        metadata_model=meta.get("model"),
        metadata_llm_provider=meta.get("llm_provider"),
    )

    done_marker: dict[str, Any] = {
        "outcome": "monitored",
        "name": meta.get("name"),
        "cl_name": meta.get("cl_name"),
        "workspace_dir": meta.get("workspace_dir"),
        "workspace_num": meta.get("workspace_num"),
        "monitor_state": monitor_state,
        "monitor_exit_code": exit_code,
        "monitor_elapsed_seconds": elapsed_seconds,
        "status_label": stop_status,
        "response_path": response_path,
    }
    if error:
        done_marker["error"] = error
    if timeout_kind is not None:
        done_marker["monitor_timeout_kind"] = timeout_kind
        if timeout_message:
            done_marker["monitor_timeout_message"] = timeout_message
    write_done_marker_and_update_index(artifacts_dir, done_marker)

    project_name = _project_name_from_artifacts_dir(artifacts_dir)
    _touch_refresh_pulse(project_name)

    next_action = meta.get("monitor_next_action")
    if next_action and monitor_state != "stopped":
        followup_error: str | None = None
        launched = False
        if project_name:
            launched = launch_followup_agent(
                artifacts_dir,
                meta,
                monitor_state=monitor_state,
                exit_code=exit_code,
                elapsed_seconds=elapsed_seconds,
                capture=capture,
                timeout_kind=timeout_kind,
                project_name=project_name,
            )
            followup_error = str(meta.get("monitor_followup_error") or "") or None
        else:
            followup_error = (
                "could not resolve the monitor's project from its artifacts path"
            )
        if launched:
            return
        _release_claim_and_notify(
            meta,
            project_name=project_name,
            monitor_state=monitor_state,
            stop_status=stop_status,
            followup_error=followup_error or "follow-up launch failed",
        )
        return

    _release_claim_and_notify(
        meta,
        project_name=project_name,
        monitor_state=monitor_state,
        stop_status=stop_status,
    )


def _release_claim_and_notify(
    meta: dict[str, Any],
    *,
    project_name: str | None,
    monitor_state: MonitorState,
    stop_status: str,
    followup_error: str | None = None,
) -> None:
    workspace_num = meta.get("workspace_num")
    cl_name = meta.get("cl_name")
    if project_name and workspace_num is not None:
        from sase.monitor.start import MONITOR_WORKSPACE_CLAIM_WORKFLOW
        from sase.workflows.utils import get_project_file_path

        release_workspace(
            get_project_file_path(project_name),
            int(workspace_num),
            MONITOR_WORKSPACE_CLAIM_WORKFLOW,
            cl_name=cl_name,
        )

    success = monitor_state in {"completed", "stopped"} and followup_error is None
    notes = [f"{stop_status}: {meta.get('monitor_command')}"]
    if followup_error:
        monitor_id = meta.get("monitor_id") or ""
        notes.append(
            f"follow-up launch failed: {followup_error} "
            f"(inspect with `sase monitor show {monitor_id} --all-lines`)"
        )
    notify_workflow_complete(
        "monitor",
        cl_name,
        success,
        notes,
        tags=["monitor"],
    )


def _touch_refresh_pulse(project_name: str | None) -> None:
    if project_name is None:
        return
    pulse_path = sase_projects_dir() / project_name / "artifacts" / ".ace_refresh_pulse"
    try:
        pulse_path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def _project_name_from_artifacts_dir(artifacts_dir: str) -> str | None:
    try:
        relative = (
            Path(artifacts_dir)
            .expanduser()
            .resolve()
            .relative_to(sase_projects_dir().resolve())
        )
    except ValueError:
        return None
    return relative.parts[0] if relative.parts else None


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"agent_meta.json at {artifacts_dir!r} is not an object")
    return data


def _one_line(exc: BaseException) -> str:
    return " ".join(str(exc).splitlines()) or exc.__class__.__name__


def _timeout_message(
    timeout_kind: _TimeoutKind | None,
    *,
    total_timeout_seconds: float,
    idle_timeout_seconds: float,
    elapsed_seconds: float,
) -> str | None:
    if timeout_kind == "idle":
        return f"no output for {_format_duration(idle_timeout_seconds)}"
    if timeout_kind == "total":
        elapsed = _format_duration(elapsed_seconds)
        total = _format_duration(total_timeout_seconds)
        return f"did not finish after {elapsed} of a {total} budget"
    return None


def _format_duration(seconds: float) -> str:
    if 0 < seconds < 1:
        return f"{seconds:g}s"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supervise one SASE monitor member.")
    parser.add_argument("--artifacts-dir", required=True)
    return parser


def _main() -> int:
    return run_supervisor(_parser().parse_args().artifacts_dir)


if __name__ == "__main__":
    raise SystemExit(_main())
