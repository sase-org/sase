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
import select
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.paths import sase_projects_dir
from sase.history.chat import save_chat_history
from sase.notifications.senders import notify_workflow_complete
from sase.running_field import release_workspace

from .models import MonitorState
from .output import OutputCapture

_POLL_SECONDS = 0.5
_KILL_GRACE_SECONDS = 5.0


class _Termination:
    """Forward stop/timeout signals to the monitored command's process group."""

    def __init__(self) -> None:
        self.requested = False
        self.child: subprocess.Popen[str] | None = None
        self.kill_deadline: float | None = None

    def request(self, _signum: int, _frame: object) -> None:
        self.requested = True
        self._signal_child()

    def trigger_timeout(self) -> None:
        self._signal_child()

    def attach(self, child: subprocess.Popen[str]) -> None:
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


def _signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _run_supervisor(artifacts_dir: str) -> int:
    """Own one monitor member from command spawn through terminal marker."""
    meta = _read_meta(artifacts_dir)
    if meta.get("monitor_state") != "running":
        return 0

    command = str(meta["monitor_command"])
    cwd = str(meta["monitor_cwd"])
    timeout_seconds = float(meta.get("monitor_timeout_seconds") or 0.0)

    termination = _Termination()
    signal.signal(signal.SIGTERM, termination.request)
    signal.signal(signal.SIGINT, termination.request)

    output_path = os.path.join(artifacts_dir, "live_reply.md")
    capture = OutputCapture(output_path)
    started = time.monotonic()
    monitor_state: MonitorState
    exit_code: int | None = None
    error: str | None = None

    try:
        child = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            text=True,
        )
    except (OSError, ValueError) as exc:
        capture.append(f"could not start command: {exc}\n")
        capture.close()
        monitor_state = "failed"
        error = str(exc)
        _finish_monitor(
            artifacts_dir,
            meta,
            monitor_state=monitor_state,
            exit_code=None,
            elapsed_seconds=time.monotonic() - started,
            capture=capture,
            error=error,
        )
        return 1

    termination.attach(child)
    timed_out = _stream_output(child, capture, termination, timeout_seconds)
    capture.close()

    if termination.requested:
        monitor_state = "stopped"
    elif timed_out:
        monitor_state = "timeout"
    elif child.returncode == 0:
        monitor_state = "completed"
    else:
        monitor_state = "failed"
    exit_code = child.returncode

    _finish_monitor(
        artifacts_dir,
        meta,
        monitor_state=monitor_state,
        exit_code=exit_code,
        elapsed_seconds=time.monotonic() - started,
        capture=capture,
        error=error,
    )
    return 0 if monitor_state in {"completed", "stopped"} else 1


def _stream_output(
    child: subprocess.Popen[str],
    capture: OutputCapture,
    termination: _Termination,
    timeout_seconds: float,
) -> bool:
    """Stream merged output until the child exits; return whether it timed out."""
    assert child.stdout is not None
    stdout = child.stdout
    deadline = time.monotonic() + timeout_seconds if timeout_seconds > 0 else None
    timed_out = False
    while True:
        ready, _, _ = select.select([stdout], [], [], _POLL_SECONDS)
        if ready:
            line = stdout.readline()
            if line:
                capture.append(line)
                continue
            break  # EOF
        if child.poll() is not None:
            break
        if deadline is not None and not timed_out and time.monotonic() >= deadline:
            timed_out = True
            termination.trigger_timeout()
        termination.maybe_escalate()

    for line in stdout:
        capture.append(line)
    child.wait()
    return timed_out


def _finish_monitor(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: MonitorState,
    exit_code: int | None,
    elapsed_seconds: float,
    capture: OutputCapture,
    error: str | None,
) -> None:
    """Write the terminal marker, save chat history, and settle the claim."""
    stop_status = str(meta.get("monitor_stop_status") or "MONITORED")
    retained = capture.retained_text()

    meta["monitor_state"] = monitor_state
    if exit_code is not None:
        meta["monitor_exit_code"] = exit_code
    meta["monitor_output_truncated"] = capture.truncated
    meta["stopped_at"] = _utc_now_iso()
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
    write_done_marker_and_update_index(artifacts_dir, done_marker)

    project_name = _project_name_from_artifacts_dir(artifacts_dir)
    _touch_refresh_pulse(project_name)

    next_action = meta.get("monitor_next_action")
    if next_action and monitor_state != "stopped":
        # engine-next (a later, dependent phase) launches the follow-up agent
        # from here and transfers the workspace claim onward. Until it does,
        # keep holding the claim rather than releasing a result nobody has
        # acted on yet.
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
) -> None:
    workspace_num = meta.get("workspace_num")
    cl_name = meta.get("cl_name")
    if project_name and workspace_num is not None:
        from sase.workflows.utils import get_project_file_path

        release_workspace(
            get_project_file_path(project_name),
            int(workspace_num),
            cl_name=cl_name,
        )

    success = monitor_state in {"completed", "stopped"}
    notify_workflow_complete(
        "monitor",
        cl_name,
        success,
        [f"{stop_status}: {meta.get('monitor_command')}"],
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


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supervise one SASE monitor member.")
    parser.add_argument("--artifacts-dir", required=True)
    return parser


def _main() -> int:
    return _run_supervisor(_parser().parse_args().artifacts_dir)


if __name__ == "__main__":
    raise SystemExit(_main())
