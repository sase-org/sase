"""Detached install/update workflow launcher for chat integrations."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.axe.process import is_axe_running, start_axe_daemon, stop_axe_daemon
from sase.config.core import load_merged_config
from sase.vcs_provider import get_vcs_provider

_STATE_DIR = Path.home() / ".sase" / "chat_install"
_LOG_DIR = _STATE_DIR / "logs"
_LOCK_PATH = _STATE_DIR / "install.lock"
_LOCK_FD_ENV = "SASE_CHAT_INSTALL_LOCK_FD"

LaunchStatus = Literal[
    "config_missing_command",
    "workspace_resolution_failed",
    "already_running",
    "launched",
    "launch_failed",
]


@dataclass(frozen=True)
class ChatInstallConfig:
    command: str
    sync_workspace: bool = True
    timeout_seconds: int = 900
    restart_attempts: int = 3


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class ChatInstallLaunchResult:
    status: LaunchStatus
    message: str
    log_path: Path | None = None
    workspace: Path | None = None
    pid: int | None = None


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

        log_path = _new_log_path()
        log_file = open(log_path, "a", encoding="utf-8")
        env = os.environ.copy()
        env[_LOCK_FD_ENV] = str(lock_fd)
        cmd = [
            sys.executable,
            "-m",
            "sase.integrations.chat_install",
            "--workspace",
            str(workspace),
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
            return ChatInstallLaunchResult(
                status="launch_failed",
                message=f"Failed to launch chat update worker: {exc}",
                log_path=log_path,
                workspace=workspace,
            )

        return ChatInstallLaunchResult(
            status="launched",
            message=f"Update worker started; log: {_shorten_home(log_path)}",
            log_path=log_path,
            workspace=workspace,
            pid=proc.pid,
        )
    finally:
        os.close(lock_fd)


def run_worker(workspace: Path) -> int:
    """Run the stop/sync/install/start sequence in the detached worker."""
    lock_fd = _adopt_lock_fd()
    exit_code = 1
    try:
        _log("chat install worker started")
        _log(f"workspace: {workspace}")
        config = load_chat_install_config()
        if not config.command:
            _log("chat_install.command is empty; skipping stop/sync/install")
            exit_code = 2
            return 2

        try:
            try:
                _log("stopping axe")
                stopped = stop_axe_daemon()
                _log(f"stop axe result: {'stopped' if stopped else 'not running'}")

                if not workspace.is_dir():
                    _log(f"workspace does not exist: {workspace}")
                    exit_code = 3
                    return 3

                if config.sync_workspace:
                    _log("syncing workspace")
                    provider = get_vcs_provider(str(workspace))
                    success, error = provider.sync_workspace(str(workspace))
                    if not success:
                        _log(
                            f"sync failed; skipping install command: {error or 'unknown error'}"
                        )
                        exit_code = 4
                        return 4
                    _log("sync succeeded")
                else:
                    _log("workspace sync disabled by config")

                exit_code = _run_install_command(config, workspace)
                return exit_code
            finally:
                _restart_axe(config.restart_attempts)
        except Exception as exc:
            _log(f"worker failed: {type(exc).__name__}: {exc}")
            exit_code = 1
            return 1
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        _log(f"chat install worker exiting with status {exit_code}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sase.integrations.chat_install")
    parser.add_argument("--workspace", required=True, help="Primary SASE workspace")
    args = parser.parse_args(argv)
    return run_worker(Path(args.workspace).expanduser().resolve())


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
    raw = os.environ.get(_LOCK_FD_ENV)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _new_log_path() -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _LOG_DIR / f"install_{timestamp}_{os.getpid()}.log"


def _shorten_home(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home) :] if text.startswith(home + os.sep) else text


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


def _restart_axe(attempts: int) -> None:
    for attempt in range(1, attempts + 1):
        _log(f"starting axe (attempt {attempt}/{attempts})")
        try:
            pid = start_axe_daemon()
        except Exception as exc:
            _log(f"start axe attempt failed: {type(exc).__name__}: {exc}")
            pid = None
        if pid is not None and is_axe_running():
            _log(f"axe restart succeeded: pid {pid}")
            return
        time.sleep(min(attempt, 5))
    _log("axe restart failed after all attempts")


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
