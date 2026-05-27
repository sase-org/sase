"""Launcher for detached chat install/update jobs."""

from __future__ import annotations

import os
import subprocess
import sys

from ._chat_install_models import ChatInstallLaunchResult
from ._chat_install_config import (
    load_chat_install_config,
    resolve_primary_workspace_for_chat_install,
)
from ._chat_install_lock import acquire_lock
from ._chat_install_paths import (
    _LOCK_FD_ENV,
    completion_path,
    new_job_id,
    new_log_path,
    shorten_home,
)
from ._chat_install_state import write_job_state
from ._chat_install_worker import utc_now


def start_chat_install_worker() -> ChatInstallLaunchResult:
    """Launch the detached chat install worker, returning chat-safe status."""
    config = load_chat_install_config()
    if not config.command:
        return ChatInstallLaunchResult(
            status="config_missing_command",
            message="chat_install.command is not configured; update was not started.",
        )

    lock_fd = acquire_lock()
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

        job_id = new_job_id()
        log_path = new_log_path(job_id)
        status_path = completion_path(job_id)
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
            write_job_state(
                job_id,
                status="failed",
                message=f"Failed to launch chat update worker: {exc}",
                log_path=log_path,
                workspace=workspace,
                status_path=status_path,
                pid=None,
                started_at=utc_now(),
                finished_at=utc_now(),
            )
            return ChatInstallLaunchResult(
                status="launch_failed",
                message=f"Failed to launch chat update worker: {exc}",
                log_path=log_path,
                workspace=workspace,
                job_id=job_id,
                status_path=status_path,
            )

        write_job_state(
            job_id,
            status="running",
            message="Update worker started.",
            log_path=log_path,
            workspace=workspace,
            status_path=status_path,
            pid=proc.pid,
            started_at=utc_now(),
            finished_at=None,
        )
        return ChatInstallLaunchResult(
            status="launched",
            message=f"Update worker started; log: {shorten_home(log_path)}",
            log_path=log_path,
            workspace=workspace,
            pid=proc.pid,
            job_id=job_id,
            status_path=status_path,
        )
    finally:
        os.close(lock_fd)
