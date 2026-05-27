"""Detached install/update workflow launcher for chat integrations."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from sase.axe.process import is_axe_running, start_axe_daemon, stop_axe_daemon
from sase.config.core import load_merged_config
from sase.vcs_provider import get_vcs_provider

from . import _chat_install_config as _config
from . import _chat_install_launch as _launch
from . import _chat_install_lock as _lock
from . import _chat_install_paths as _paths
from . import _chat_install_state as _state
from . import _chat_install_worker as _worker
from . import _chat_install_models as _models
from ._chat_install_paths import _LOCK_FD_ENV
from ._chat_install_worker import run_worker as _run_worker_impl

ChatInstallLaunchResult = _models.ChatInstallLaunchResult
ChatInstallStatusResult = _models.ChatInstallStatusResult
ChatInstallConfig = _models.ChatInstallConfig
JobStatus = _models.JobStatus
LaunchStatus = _models.LaunchStatus
_ChatInstallConfig = ChatInstallConfig

_STATE_DIR: Path | None = None
_LOG_DIR: Path | None = None
_COMPLETIONS_DIR: Path | None = None
_JOBS_DIR: Path | None = None
_LOCK_PATH: Path | None = None

__all__ = [
    "ChatInstallLaunchResult",
    "ChatInstallStatusResult",
    "JobStatus",
    "LaunchStatus",
    "read_chat_install_status",
    "start_chat_install_worker",
]


def start_chat_install_worker() -> ChatInstallLaunchResult:
    """Launch the detached chat install worker, returning chat-safe status."""
    _sync_dependency_overrides()
    return _launch.start_chat_install_worker()


def read_chat_install_status(job_id: str) -> ChatInstallStatusResult:
    """Read structured status for a chat install/update job."""
    _sync_dependency_overrides()
    return _state.read_chat_install_status(job_id)


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
    return _run_worker(
        Path(args.workspace).expanduser().resolve(),
        job_id=args.job_id,
        status_path=Path(args.status_path).expanduser() if args.status_path else None,
        log_path=Path(args.log_path).expanduser() if args.log_path else None,
    )


def _load_chat_install_config() -> ChatInstallConfig:
    _sync_dependency_overrides()
    return _config.load_chat_install_config()


def _resolve_primary_workspace_for_chat_install() -> Path | None:
    _sync_dependency_overrides()
    return _config.resolve_primary_workspace_for_chat_install()


def _run_worker(
    workspace: Path,
    *,
    job_id: str | None = None,
    status_path: Path | None = None,
    log_path: Path | None = None,
) -> int:
    _sync_dependency_overrides()
    return _run_worker_impl(
        workspace,
        job_id=job_id,
        status_path=status_path,
        log_path=log_path,
    )


def _sync_dependency_overrides() -> None:
    """Preserve legacy monkeypatch targets on this facade module."""
    _paths._STATE_DIR = _STATE_DIR
    _paths._LOG_DIR = _LOG_DIR
    _paths._COMPLETIONS_DIR = _COMPLETIONS_DIR
    _paths._JOBS_DIR = _JOBS_DIR
    _paths._LOCK_PATH = _LOCK_PATH

    _config.load_merged_config = load_merged_config

    _launch.subprocess = subprocess
    _launch.load_chat_install_config = _load_chat_install_config
    _launch.resolve_primary_workspace_for_chat_install = (
        _resolve_primary_workspace_for_chat_install
    )

    _state.lock_is_held = _lock_is_held

    _worker.subprocess = subprocess
    _worker.time = time
    _worker.load_chat_install_config = _load_chat_install_config
    _worker.stop_axe_daemon = stop_axe_daemon
    _worker.get_vcs_provider = get_vcs_provider
    _worker.start_axe_daemon = start_axe_daemon
    _worker.is_axe_running = is_axe_running


def _lock_is_held() -> bool:
    _sync_dependency_overrides()
    return _lock.lock_is_held()


if __name__ == "__main__":
    raise SystemExit(main())
