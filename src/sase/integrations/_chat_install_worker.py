"""Detached worker execution for chat install/update jobs."""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import subprocess
import time
from pathlib import Path

from sase.axe.process import is_axe_running, start_axe_daemon, stop_axe_daemon
from sase.vcs_provider import get_vcs_provider

from ._chat_install_config import load_chat_install_config
from ._chat_install_lock import adopt_lock_fd
from ._chat_install_models import ChatInstallConfig


def run_worker(
    workspace: Path,
    *,
    job_id: str | None = None,
    status_path: Path | None = None,
    log_path: Path | None = None,
) -> int:
    """Run the stop/sync/install/start sequence in the detached worker."""
    lock_fd = adopt_lock_fd()
    exit_code = 1
    started_at = utc_now()
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
                    completed_at=utc_now(),
                    restart_succeeded=restart_succeeded,
                    message=message,
                )
            except Exception as exc:
                _log(f"failed to write completion record: {type(exc).__name__}: {exc}")


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


def utc_now() -> str:
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
