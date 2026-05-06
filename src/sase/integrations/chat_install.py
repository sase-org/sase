"""Detached install/update workflow launcher for chat integrations."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.axe.process import is_axe_running, start_axe_daemon, stop_axe_daemon
from sase.config.core import load_merged_config
from sase.vcs_provider import get_vcs_provider

_STATE_DIR = Path.home() / ".sase" / "chat_install"
_LOG_DIR = _STATE_DIR / "logs"
_COMPLETIONS_DIR = _STATE_DIR / "completions"
_JOBS_DIR = _STATE_DIR / "jobs"
_LOCK_PATH = _STATE_DIR / "install.lock"
_LOCK_FD_ENV = "SASE_CHAT_INSTALL_LOCK_FD"

LaunchStatus = Literal[
    "config_missing_command",
    "workspace_resolution_failed",
    "already_running",
    "launched",
    "launch_failed",
]
JobStatus = Literal["running", "succeeded", "failed", "not_found"]


@dataclass(frozen=True)
class ChatInstallConfig:
    command: str
    sync_workspace: bool = True
    timeout_seconds: int = 900
    restart_attempts: int = 3


@dataclass(frozen=True)
class ChatInstallLaunchResult:
    status: LaunchStatus
    message: str
    log_path: Path | None = None
    workspace: Path | None = None
    pid: int | None = None
    job_id: str | None = None
    status_path: Path | None = None


@dataclass(frozen=True)
class ChatInstallStatusResult:
    status: JobStatus
    message: str
    job_id: str
    started_at: str | None = None
    finished_at: str | None = None
    log_path: Path | None = None
    completion_path: Path | None = None
    workspace: Path | None = None
    exit_code: int | None = None
    restart_succeeded: bool | None = None


def load_chat_install_config() -> ChatInstallConfig:
    """Read and normalize the ``chat_install`` merged-config section."""
    raw = load_merged_config().get("chat_install", {})
    if not isinstance(raw, dict):
        raw = {}

    command = raw.get("command", "")
    sync_workspace = raw.get("sync_workspace", True)
    timeout_seconds = raw.get("timeout_seconds", 900)
    restart_attempts = raw.get("restart_attempts", 3)

    return ChatInstallConfig(
        command=command.strip() if isinstance(command, str) else "",
        sync_workspace=bool(sync_workspace),
        timeout_seconds=_positive_int(timeout_seconds, 900),
        restart_attempts=_positive_int(restart_attempts, 3),
    )


def resolve_primary_workspace_for_chat_install() -> Path | None:
    """Resolve the registered SASE project workspace used as install/sync cwd."""
    registered_workspace = _resolve_registered_sase_workspace()
    if registered_workspace is not None:
        return registered_workspace

    from sase.bead.workspace import resolve_primary_workspace

    return resolve_primary_workspace()


def _resolve_registered_sase_workspace() -> Path | None:
    """Resolve ``~/.sase/projects/sase/sase.gp`` without consulting CWD."""
    project_file = Path.home() / ".sase" / "projects" / "sase" / "sase.gp"

    from sase.workspace_provider.utils import parse_workspace_dir

    workspace_dir = parse_workspace_dir(str(project_file))
    if not workspace_dir:
        return None

    workspace = Path(workspace_dir).expanduser()
    if not workspace.is_dir():
        return None
    return workspace


def start_chat_install_worker() -> ChatInstallLaunchResult:
    """Launch the detached chat install worker, returning chat-safe status."""
    config = load_chat_install_config()
    if not config.command:
        return ChatInstallLaunchResult(
            status="config_missing_command",
            message="chat_install.command is not configured; update was not started.",
        )

    lock_fd = _acquire_lock()
    if lock_fd is None:
        return ChatInstallLaunchResult(
            status="already_running",
            message="A chat update worker is already running.",
        )

    try:
        workspace = resolve_primary_workspace_for_chat_install()
        if workspace is None:
            return ChatInstallLaunchResult(
                status="workspace_resolution_failed",
                message="Could not resolve the primary SASE workspace; update was not started.",
            )

        job_id = _new_job_id()
        log_path = _new_log_path(job_id)
        status_path = _completion_path(job_id)
        log_file = open(log_path, "a", encoding="utf-8")
        env = os.environ.copy()
        env[_LOCK_FD_ENV] = str(lock_fd)
        cmd = [
            sys.executable,
            "-m",
            "sase.integrations.chat_install",
            "--workspace",
            str(workspace),
            "--job-id",
            job_id,
            "--status-path",
            str(status_path),
            "--log-path",
            str(log_path),
        ]
        try:
            with log_file:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(workspace),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    pass_fds=(lock_fd,),
                    env=env,
                )
        except Exception as exc:
            _write_job_state(
                job_id,
                status="failed",
                message=f"Failed to launch chat update worker: {exc}",
                log_path=log_path,
                workspace=workspace,
                status_path=status_path,
                pid=None,
                started_at=_utc_now(),
                finished_at=_utc_now(),
            )
            return ChatInstallLaunchResult(
                status="launch_failed",
                message=f"Failed to launch chat update worker: {exc}",
                log_path=log_path,
                workspace=workspace,
                job_id=job_id,
                status_path=status_path,
            )

        _write_job_state(
            job_id,
            status="running",
            message="Update worker started.",
            log_path=log_path,
            workspace=workspace,
            status_path=status_path,
            pid=proc.pid,
            started_at=_utc_now(),
            finished_at=None,
        )
        return ChatInstallLaunchResult(
            status="launched",
            message=f"Update worker started; log: {_shorten_home(log_path)}",
            log_path=log_path,
            workspace=workspace,
            pid=proc.pid,
            job_id=job_id,
            status_path=status_path,
        )
    finally:
        os.close(lock_fd)


def read_chat_install_status(job_id: str) -> ChatInstallStatusResult:
    """Read structured status for a chat install/update job."""
    if not _valid_job_id(job_id):
        return ChatInstallStatusResult(
            status="not_found",
            message="Update job was not found.",
            job_id=job_id,
        )

    completion_path = _completion_path(job_id)
    if completion_path.is_file():
        return _read_completion_status(job_id, completion_path)

    state = _read_job_state(job_id)
    if state is None:
        return ChatInstallStatusResult(
            status="not_found",
            message="Update job was not found.",
            job_id=job_id,
        )

    log_path = _optional_path(state.get("log_path"))
    workspace = _optional_path(state.get("workspace"))
    state_completion = _optional_path(state.get("status_path"))
    if state.get("status") == "running" and _lock_is_held():
        return ChatInstallStatusResult(
            status="running",
            message=_string_or_default(state.get("message"), "Update is running."),
            job_id=job_id,
            started_at=_optional_string_value(state.get("started_at")),
            finished_at=None,
            log_path=log_path,
            completion_path=state_completion or completion_path,
            workspace=workspace,
        )

    state_status = state.get("status")
    if state_status == "failed":
        return ChatInstallStatusResult(
            status="failed",
            message=_string_or_default(state.get("message"), "Update failed."),
            job_id=job_id,
            started_at=_optional_string_value(state.get("started_at")),
            finished_at=_optional_string_value(state.get("finished_at")),
            log_path=log_path,
            completion_path=state_completion or completion_path,
            workspace=workspace,
        )

    return ChatInstallStatusResult(
        status="failed",
        message="Update job ended before writing a completion record.",
        job_id=job_id,
        started_at=_optional_string_value(state.get("started_at")),
        finished_at=_optional_string_value(state.get("finished_at")),
        log_path=log_path,
        completion_path=state_completion or completion_path,
        workspace=workspace,
    )


def run_worker(
    workspace: Path,
    *,
    job_id: str | None = None,
    status_path: Path | None = None,
    log_path: Path | None = None,
) -> int:
    """Run the stop/sync/install/start sequence in the detached worker."""
    lock_fd = _adopt_lock_fd()
    exit_code = 1
    started_at = _utc_now()
    restart_succeeded: bool | None = None
    message = "Update failed with exit code 1."
    try:
        _log("chat install worker started")
        _log(f"workspace: {workspace}")
        config = load_chat_install_config()
        if not config.command:
            _log("chat_install.command is empty; skipping stop/sync/install")
            exit_code = 2
            message = "Update failed with exit code 2."
            return exit_code

        try:
            _log("stopping axe")
            stopped = stop_axe_daemon()
            _log(f"stop axe result: {'stopped' if stopped else 'not running'}")

            if not workspace.is_dir():
                _log(f"workspace does not exist: {workspace}")
                exit_code = 3
                message = "Update failed with exit code 3."
            elif config.sync_workspace:
                _log("syncing workspace")
                provider = get_vcs_provider(str(workspace))
                success, error = provider.sync_workspace(str(workspace))
                if not success:
                    _log(
                        f"sync failed; skipping install command: {error or 'unknown error'}"
                    )
                    exit_code = 4
                    message = "Update failed with exit code 4."
                else:
                    _log("sync succeeded")
                    exit_code = _run_install_command(config, workspace)
                    message = (
                        "Update completed successfully."
                        if exit_code == 0
                        else f"Update failed with exit code {exit_code}."
                    )
            else:
                _log("workspace sync disabled by config")
                exit_code = _run_install_command(config, workspace)
                message = (
                    "Update completed successfully."
                    if exit_code == 0
                    else f"Update failed with exit code {exit_code}."
                )

            restart_succeeded = _restart_axe(config.restart_attempts)
            if exit_code == 0 and not restart_succeeded:
                exit_code = 5
                message = "Update failed with exit code 5; axe restart failed."
            return exit_code
        except Exception as exc:
            _log(f"worker failed: {type(exc).__name__}: {exc}")
            exit_code = 1
            message = "Update failed with exit code 1."
            if restart_succeeded is None:
                restart_succeeded = _restart_axe(config.restart_attempts)
            return exit_code
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        _log(f"chat install worker exiting with status {exit_code}")
        if status_path is not None:
            try:
                _write_completion_record(
                    status_path,
                    job_id=job_id,
                    exit_code=exit_code,
                    log_path=log_path,
                    workspace=workspace,
                    started_at=started_at,
                    completed_at=_utc_now(),
                    restart_succeeded=restart_succeeded,
                    message=message,
                )
            except Exception as exc:
                _log(f"failed to write completion record: {type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sase.integrations.chat_install")
    parser.add_argument("--workspace", required=True, help="Primary SASE workspace")
    parser.add_argument("--job-id", default=None, help="Chat install job id")
    parser.add_argument(
        "--status-path",
        default=None,
        help="Path to write the final chat install completion JSON",
    )
    parser.add_argument("--log-path", default=None, help="Worker log path")
    args = parser.parse_args(argv)
    return run_worker(
        Path(args.workspace).expanduser().resolve(),
        job_id=args.job_id,
        status_path=Path(args.status_path).expanduser() if args.status_path else None,
        log_path=Path(args.log_path).expanduser() if args.log_path else None,
    )


def _positive_int(value: object, default: int) -> int:
    if not isinstance(value, int | str | bytes | bytearray):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _acquire_lock() -> int | None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(_LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def _adopt_lock_fd() -> int | None:
    raw = os.environ.pop(_LOCK_FD_ENV, None)
    if raw is None:
        return None
    try:
        fd = int(raw)
        fd_stat = os.fstat(fd)
        lock_stat = _LOCK_PATH.stat()
    except (OSError, ValueError):
        return None
    if (fd_stat.st_dev, fd_stat.st_ino) != (lock_stat.st_dev, lock_stat.st_ino):
        return None
    return fd


def _new_job_id() -> str:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{os.getpid()}_{uuid.uuid4().hex[:8]}"


def _new_log_path(job_id: str | None = None) -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    if job_id is None:
        job_id = _new_job_id()
    return _LOG_DIR / f"install_{job_id}.log"


def _completion_path(job_id: str) -> Path:
    _COMPLETIONS_DIR.mkdir(parents=True, exist_ok=True)
    return _COMPLETIONS_DIR / f"{job_id}.json"


def _job_state_path(job_id: str) -> Path:
    _JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return _JOBS_DIR / f"{job_id}.json"


def _valid_job_id(job_id: str) -> bool:
    return (
        0 < len(job_id) <= 128
        and job_id not in {".", ".."}
        and all(
            char.isascii() and (char.isalnum() or char in {"_", "-", "."})
            for char in job_id
        )
    )


def _shorten_home(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home) :] if text.startswith(home + os.sep) else text


def _read_completion_status(
    job_id: str, completion_path: Path
) -> ChatInstallStatusResult:
    try:
        raw = json.loads(completion_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ChatInstallStatusResult(
            status="failed",
            message=f"Update completion record is malformed: {type(exc).__name__}.",
            job_id=job_id,
            completion_path=completion_path,
        )
    if not isinstance(raw, dict):
        return ChatInstallStatusResult(
            status="failed",
            message="Update completion record is malformed: expected object.",
            job_id=job_id,
            completion_path=completion_path,
        )

    raw_status = raw.get("status")
    status: JobStatus = "succeeded" if raw_status == "success" else "failed"
    return ChatInstallStatusResult(
        status=status,
        message=_string_or_default(
            raw.get("message"),
            "Update completed successfully."
            if status == "succeeded"
            else "Update failed.",
        ),
        job_id=_string_or_default(raw.get("job_id"), job_id),
        started_at=_optional_string_value(raw.get("started_at")),
        finished_at=_optional_string_value(raw.get("completed_at")),
        log_path=_optional_path(raw.get("log_path")),
        completion_path=completion_path,
        workspace=_optional_path(raw.get("workspace")),
        exit_code=_optional_int(raw.get("exit_code")),
        restart_succeeded=(
            raw.get("restart_succeeded")
            if isinstance(raw.get("restart_succeeded"), bool)
            else None
        ),
    )


def _read_job_state(job_id: str) -> dict[str, object] | None:
    path = _job_state_path(job_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "failed",
            "message": "Update job state is malformed.",
            "status_path": str(_completion_path(job_id)),
        }
    if not isinstance(raw, dict):
        return {
            "status": "failed",
            "message": "Update job state is malformed.",
            "status_path": str(_completion_path(job_id)),
        }
    return raw


def _write_job_state(
    job_id: str,
    *,
    status: str,
    message: str,
    log_path: Path | None,
    workspace: Path | None,
    status_path: Path | None,
    pid: int | None,
    started_at: str,
    finished_at: str | None,
) -> None:
    path = _job_state_path(job_id)
    record = {
        "job_id": job_id,
        "status": status,
        "message": message,
        "log_path": str(log_path) if log_path is not None else None,
        "workspace": str(workspace) if workspace is not None else None,
        "status_path": str(status_path) if status_path is not None else None,
        "pid": pid,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _lock_is_held() -> bool:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(_LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _optional_path(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


def _optional_string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_or_default(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _run_install_command(config: ChatInstallConfig, workspace: Path) -> int:
    _log(f"running install command: {config.command}")
    try:
        completed = subprocess.run(
            config.command,
            shell=True,
            cwd=str(workspace),
            text=True,
            capture_output=True,
            timeout=config.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        _log(f"install command timed out after {config.timeout_seconds}s")
        if exc.stdout:
            _log_block("stdout", exc.stdout)
        if exc.stderr:
            _log_block("stderr", exc.stderr)
        return 124

    if completed.stdout:
        _log_block("stdout", completed.stdout)
    if completed.stderr:
        _log_block("stderr", completed.stderr)
    _log(f"install command exit code: {completed.returncode}")
    return completed.returncode


def _restart_axe(attempts: int) -> bool:
    for attempt in range(1, attempts + 1):
        _log(f"starting axe (attempt {attempt}/{attempts})")
        try:
            pid = start_axe_daemon()
        except Exception as exc:
            _log(f"start axe attempt failed: {type(exc).__name__}: {exc}")
            pid = None
        if pid is not None and is_axe_running():
            _log(f"axe restart succeeded: pid {pid}")
            return True
        time.sleep(min(attempt, 5))
    _log("axe restart failed after all attempts")
    return False


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _write_completion_record(
    status_path: Path,
    *,
    job_id: str | None,
    exit_code: int,
    log_path: Path | None,
    workspace: Path,
    started_at: str,
    completed_at: str,
    restart_succeeded: bool | None,
    message: str,
) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "job_id": job_id,
        "status": "success" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "log_path": str(log_path) if log_path is not None else None,
        "workspace": str(workspace),
        "started_at": started_at,
        "completed_at": completed_at,
        "restart_succeeded": restart_succeeded,
        "message": message,
    }
    temp_path = status_path.with_name(f".{status_path.name}.{os.getpid()}.tmp")
    temp_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    temp_path.replace(status_path)


def _log(message: str) -> None:
    timestamp = dt.datetime.now().isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


def _log_block(label: str, text: str | bytes) -> None:
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    _log(f"{label}:")
    print(text.rstrip(), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
