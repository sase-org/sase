"""Own one monitor member from command spawn through the terminal marker.

This is the orchestration half of the detached supervisor: it reads the
member meta, opens the output log, waits on the launch barrier, spawns the
monitored command, and hands terminal settlement to
:mod:`sase.monitor.supervise_finish`. Process control lives in
:mod:`sase.monitor.supervise_proc`.
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from typing import Any

from sase.agent.env_hygiene import scrub_agent_identity_env
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.source_skew import preload_host_completion_modules
from sase.bead.epic_launch_handoff import MONITOR_ARTIFACTS_ENV
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.atomic_json import write_json_marker_atomic
from sase.logs.pipe import BoundedLogPipe
from sase.macro.directive_edit import SASE_AGENT_TAB_ENV

from ._supervise_shared import TimeoutKind, utc_now_iso
from .diagnostics import diagnostics_dir
from .identity import process_identity
from .logs import append_monitor_log_bytes, monitor_log_max_bytes, monitor_log_path
from .models import MonitorState
from .output import OutputCapture
from .supervise_finish import finish_monitor
from .supervise_proc import (
    SupervisorOutputActivity,
    SupervisorTermination,
    popen_monitored_command,
    wait_for_child,
    wait_for_launch_barrier,
)
from .transaction import monitor_started_path


def run_supervisor(artifacts_dir: str, *, startup_signal: int | None = None) -> int:
    """Own one monitor member from spawn through terminal marker."""
    termination = SupervisorTermination()
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, termination.request)
    signal.signal(signal.SIGINT, termination.request)
    if startup_signal is not None:
        termination.request(startup_signal, None)

    meta = _read_meta(artifacts_dir)
    if meta.get("monitor_state") != "running":
        return 0

    command = str(meta["monitor_command"])
    cwd = str(meta["monitor_cwd"])
    timeout_seconds = float(meta.get("monitor_timeout_seconds") or 0.0)
    idle_timeout_seconds = float(meta.get("monitor_idle_timeout_seconds") or 0.0)

    output_path = monitor_log_path(artifacts_dir)
    meta["monitor_output_path"] = str(output_path)
    write_agent_meta_atomic(
        artifacts_dir,
        meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )
    capture = OutputCapture()
    activity = SupervisorOutputActivity(capture)
    started = time.monotonic()
    monitor_state: MonitorState = "failed"
    exit_code: int | None = None
    error: str | None = None
    timeout_kind: TimeoutKind | None = None
    output_pipe: BoundedLogPipe | None = None

    try:
        output_pipe = BoundedLogPipe(
            output_path,
            monitor_log_max_bytes(),
            on_chunk=activity.append_bytes,
            close_drain_seconds=0.5,
        )
        _write_start_acknowledgement(artifacts_dir, meta)
        # Settlement runs host completion finalizers after the command exits,
        # possibly after a code swap. Import that surface and the native
        # binding now so settlement never lazily imports a torn tree.
        preload_host_completion_modules()
        barrier_error = wait_for_launch_barrier(artifacts_dir, termination)
        if barrier_error is not None:
            error = barrier_error
            monitor_state = "stopped" if termination.requested else "failed"
            _append_supervisor_line(output_path, output_pipe, capture, error)
        elif termination.requested:
            error = termination.before_command_start_message()
            monitor_state = "stopped"
            _append_supervisor_line(output_path, output_pipe, capture, error)
        else:
            command_env = os.environ.copy()
            scrub_agent_identity_env(command_env)
            # The member re-derives the creator's tab from its own resolved
            # meta (inherited at creation), so option commands and follow-up
            # launches keep the planner's tab after the scrub above.
            _reexport_member_agent_tab(command_env, meta)
            # SASE_ARTIFACTS_DIR does not carry the SASE_AGENT_ prefix the
            # scrubber matches on, but it still names the dead starter's
            # artifacts and must not leak into the monitored command.
            command_env.pop("SASE_ARTIFACTS_DIR", None)
            command_env["SASE_MONITOR_DIAGNOSTICS_DIR"] = str(
                diagnostics_dir(artifacts_dir)
            )
            command_env[MONITOR_ARTIFACTS_ENV] = str(artifacts_dir)
            command_env["SASE_MONITOR_ID"] = str(meta.get("monitor_id") or "")
            try:
                child = popen_monitored_command(
                    meta,
                    command=command,
                    cwd=cwd,
                    output_pipe=output_pipe,
                    command_env=command_env,
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
                # Recorded here (not at member creation) so displayed runtime
                # excludes member-creation and supervisor-spawn latency.
                meta["run_started_at"] = utc_now_iso()
                write_agent_meta_atomic(
                    artifacts_dir,
                    meta,
                    index_updater=update_agent_artifact_index_for_marker_mutation,
                )
                timeout_kind = wait_for_child(
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
        retention = (
            output_pipe.retention_snapshot() if output_pipe is not None else None
        )
        if close_error is not None:
            error = error or f"supervisor error: {_one_line(close_error)}"
            monitor_state = "failed"
            _append_supervisor_line(output_path, None, capture, error)
            retention = None
        finish_monitor(
            artifacts_dir,
            meta,
            monitor_state=monitor_state,
            exit_code=exit_code,
            elapsed_seconds=time.monotonic() - started,
            capture=capture,
            error=error,
            timeout_kind=timeout_kind,
            retention=retention,
        )
    return 0 if monitor_state in {"completed", "stopped"} else 1


def _reexport_member_agent_tab(
    command_env: dict[str, str],
    meta: dict[str, Any],
) -> None:
    """Restore ``SASE_AGENT_TAB`` from the member's own resolved meta."""
    tab = meta.get("agent_tab")
    if isinstance(tab, str) and tab:
        command_env[SASE_AGENT_TAB_ENV] = tab


def _write_start_acknowledgement(artifacts_dir: str, meta: dict[str, Any]) -> None:
    """Prove this supervisor survived its own startup window.

    Written once dispositions are set, meta is read, and the output log is
    open -- before waiting on the launch barrier -- so ``start_monitor`` can
    stop blocking its caller the moment ownership is real, independent of
    whether the barrier has been released yet.
    """
    pid = os.getpid()
    write_json_marker_atomic(
        monitor_started_path(artifacts_dir),
        {
            "monitor_id": meta.get("monitor_id"),
            "pid": pid,
            "pgid": os.getpgid(0),
            "monitor_supervisor_identity": process_identity(pid),
            "timestamp": time.time(),
        },
    )


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


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"agent_meta.json at {artifacts_dir!r} is not an object")
    return data


def _one_line(exc: BaseException) -> str:
    return " ".join(str(exc).splitlines()) or exc.__class__.__name__


__all__ = [
    "run_supervisor",
]
