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

from sase.axe.process import is_axe_running, start_axe_daemon, stop_axe_daemon
from sase.config.core import load_merged_config
from sase.core.paths import sase_projects_dir, sase_subdir
from sase.vcs_provider import get_vcs_provider

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
    log_block as _log_block_impl,
    log_message as _log_message_impl,
    restart_axe as _restart_axe_impl,
    run_install_command as _run_install_command_impl,
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


def _resolve_primary_workspace_for_chat_install() -> Path | None:
    """Resolve the registered SASE project workspace used as install/sync cwd."""
    registered_workspace = _resolve_registered_sase_workspace()
    if registered_workspace is not None:
        return registered_workspace

    from sase.bead.workspace import resolve_primary_workspace

    return resolve_primary_workspace()


def _resolve_registered_sase_workspace() -> Path | None:
    """Resolve the registered ``sase`` project workspace without consulting CWD."""
    from sase.ace.changespec.project_spec_path import preferred_project_spec_path

    project_dir = sase_projects_dir() / "sase"
    project_file = Path(preferred_project_spec_path(str(project_dir), "sase"))

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
    config = _load_chat_install_config()
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
        workspace = _resolve_primary_workspace_for_chat_install()
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
    return _read_chat_install_status_impl(
        job_id,
        valid_job_id=_valid_job_id,
        completion_path_for=_completion_path,
        read_job_state=_read_job_state,
        lock_is_held=_lock_is_held,
    )


def _run_worker(
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
        config = _load_chat_install_config()
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
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
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


def _run_install_command(config: _ChatInstallConfig, workspace: Path) -> int:
    return _run_install_command_impl(
        config,
        workspace,
        run=subprocess.run,
        log=_log,
        log_block=_log_block,
    )


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
    workspace: Path,
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
