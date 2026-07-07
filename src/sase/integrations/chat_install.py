"""Detached install/update workflow launcher for chat integrations."""

from __future__ import annotations

import datetime as dt
import fcntl
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from sase.axe.process import is_axe_running, start_axe_daemon
from sase.config.core import load_merged_config
from sase.core.paths import sase_subdir
from sase.core.time import local_now

from ._chat_install_cli import main as _cli_main
from ._chat_install_config import (
    load_chat_install_config as _load_chat_install_config_from_raw,
)
from ._chat_install_models import (
    ChatInstallConfig,
    ChatInstallLaunchResult,
    ChatInstallStatusResult,
    JobStatus,
    LaunchStatus,
)
from ._chat_install_status import (
    read_chat_install_status as _read_chat_install_status_impl,
)
from ._chat_install_state import (
    read_job_state as _read_job_state_impl,
    write_job_state as _write_job_state_impl,
)
from ._chat_install_worker import (
    UpdateCommandResult,
    log_block as _log_block_impl,
    log_message as _log_message_impl,
    restart_axe as _restart_axe_impl,
    run_update_command as _run_update_command_impl,
    write_completion_record as _write_completion_record_impl,
)

_ChatInstallConfig = ChatInstallConfig

_STATE_DIR: Path | None = None
_LOG_DIR: Path | None = None
_COMPLETIONS_DIR: Path | None = None
_JOBS_DIR: Path | None = None
_LOCK_PATH: Path | None = None
_LOCK_FD_ENV = "SASE_CHAT_INSTALL_LOCK_FD"


def _state_dir() -> Path:
    return _STATE_DIR or sase_subdir("chat_install")


def _log_dir() -> Path:
    return _LOG_DIR or _state_dir() / "logs"


def _completions_dir() -> Path:
    return _COMPLETIONS_DIR or _state_dir() / "completions"


def _jobs_dir() -> Path:
    return _JOBS_DIR or _state_dir() / "jobs"


def _lock_path() -> Path:
    return _LOCK_PATH or _state_dir() / "install.lock"


def _load_chat_install_config() -> _ChatInstallConfig:
    return _load_chat_install_config_from_raw(load_merged_config())


def start_chat_install_worker() -> ChatInstallLaunchResult:
    """Launch the detached chat install worker, returning chat-safe status."""
    lock_fd = _acquire_lock()
    if lock_fd is None:
        return ChatInstallLaunchResult(
            status="already_running",
            message="A chat update worker is already running.",
        )

    try:
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
                workspace=None,
                status_path=status_path,
                pid=None,
                started_at=_utc_now(),
                finished_at=_utc_now(),
            )
            return ChatInstallLaunchResult(
                status="launch_failed",
                message=f"Failed to launch chat update worker: {exc}",
                log_path=log_path,
                workspace=None,
                job_id=job_id,
                status_path=status_path,
            )

        _write_job_state(
            job_id,
            status="running",
            message="Update worker started.",
            log_path=log_path,
            workspace=None,
            status_path=status_path,
            pid=proc.pid,
            started_at=_utc_now(),
            finished_at=None,
        )
        return ChatInstallLaunchResult(
            status="launched",
            message=f"Update worker started; log: {_shorten_home(log_path)}",
            log_path=log_path,
            workspace=None,
            pid=proc.pid,
            job_id=job_id,
            status_path=status_path,
        )
    finally:
        os.close(lock_fd)


def read_chat_install_status(job_id: str) -> ChatInstallStatusResult:
    return _read_chat_install_status_impl(
        job_id,
        valid_job_id=_valid_job_id,
        completion_path_for=_completion_path,
        read_job_state=_read_job_state,
        lock_is_held=_lock_is_held,
    )


def _run_worker(
    *,
    job_id: str | None = None,
    status_path: Path | None = None,
    log_path: Path | None = None,
) -> int:
    """Run the built-in SASE update engine in the detached worker."""
    lock_fd = _adopt_lock_fd()
    exit_code = 1
    started_at = _utc_now()
    restart_succeeded: bool | None = None
    message = "Update failed with exit code 1."
    try:
        _log("chat update worker started")
        config = _load_chat_install_config()

        try:
            result = _run_update_command(config)
            exit_code = result.exit_code
            message = result.message

            restart_succeeded = _ensure_axe_running(config.restart_attempts)
            if not restart_succeeded:
                exit_code = 5
                message = "Update failed with exit code 5; axe restart failed."
            return exit_code
        except Exception as exc:
            _log(f"worker failed: {type(exc).__name__}: {exc}")
            exit_code = 1
            message = "Update failed with exit code 1."
            if restart_succeeded is None:
                restart_succeeded = _ensure_axe_running(config.restart_attempts)
                if not restart_succeeded:
                    exit_code = 5
                    message = "Update failed with exit code 5; axe restart failed."
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
                    workspace=None,
                    started_at=started_at,
                    completed_at=_utc_now(),
                    restart_succeeded=restart_succeeded,
                    message=message,
                )
            except Exception as exc:
                _log(f"failed to write completion record: {type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    return _cli_main(argv, run_worker=_run_worker)


def _acquire_lock() -> int | None:
    lock_path = _lock_path()
    _state_dir().mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
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
        lock_stat = _lock_path().stat()
    except (OSError, ValueError):
        return None
    if (fd_stat.st_dev, fd_stat.st_ino) != (lock_stat.st_dev, lock_stat.st_ino):
        return None
    return fd


def _new_job_id() -> str:
    timestamp = local_now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{os.getpid()}_{uuid.uuid4().hex[:8]}"


def _new_log_path(job_id: str | None = None) -> Path:
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    if job_id is None:
        job_id = _new_job_id()
    return log_dir / f"install_{job_id}.log"


def _completion_path(job_id: str) -> Path:
    completions_dir = _completions_dir()
    completions_dir.mkdir(parents=True, exist_ok=True)
    return completions_dir / f"{job_id}.json"


def _job_state_path(job_id: str) -> Path:
    jobs_dir = _jobs_dir()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    return jobs_dir / f"{job_id}.json"


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


def _read_job_state(job_id: str) -> dict[str, object] | None:
    return _read_job_state_impl(
        job_id,
        job_state_path_for=_job_state_path,
        completion_path_for=_completion_path,
    )


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
    _write_job_state_impl(
        job_id,
        status=status,
        message=message,
        log_path=log_path,
        workspace=workspace,
        status_path=status_path,
        pid=pid,
        started_at=started_at,
        finished_at=finished_at,
        job_state_path_for=_job_state_path,
        process_id=os.getpid(),
    )


def _lock_is_held() -> bool:
    lock_path = _lock_path()
    _state_dir().mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _run_update_command(config: _ChatInstallConfig) -> UpdateCommandResult:
    return _run_update_command_impl(
        config,
        run=subprocess.run,
        log=_log,
        log_block=_log_block,
    )


def _ensure_axe_running(attempts: int) -> bool:
    try:
        if is_axe_running():
            _log("axe is already running")
            return True
    except Exception as exc:
        _log(f"could not check axe status: {type(exc).__name__}: {exc}")
    return _restart_axe(attempts)


def _restart_axe(attempts: int) -> bool:
    return _restart_axe_impl(
        attempts,
        start=start_axe_daemon,
        is_running=is_axe_running,
        sleep=time.sleep,
        log=_log,
    )


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _write_completion_record(
    status_path: Path,
    *,
    job_id: str | None,
    exit_code: int,
    log_path: Path | None,
    workspace: Path | None,
    started_at: str,
    completed_at: str,
    restart_succeeded: bool | None,
    message: str,
) -> None:
    _write_completion_record_impl(
        status_path,
        job_id=job_id,
        exit_code=exit_code,
        log_path=log_path,
        workspace=workspace,
        started_at=started_at,
        completed_at=completed_at,
        restart_succeeded=restart_succeeded,
        message=message,
    )


def _log(message: str) -> None:
    _log_message_impl(message)


def _log_block(label: str, text: str | bytes) -> None:
    _log_block_impl(label, text, log=_log)


if __name__ == "__main__":
    raise SystemExit(main())
