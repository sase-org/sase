"""Reusable worker-side helpers for chat install/update jobs."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.core.time import local_now

from ._chat_install_models import ChatInstallConfig


def run_install_command(
    config: ChatInstallConfig,
    workspace: Path,
    *,
    run: Callable[..., Any],
    log: Callable[[str], None],
    log_block: Callable[[str, str | bytes], None],
) -> int:
    log(f"running install command: {config.command}")
    try:
        completed = run(
            config.command,
            shell=True,
            cwd=str(workspace),
            text=True,
            capture_output=True,
            timeout=config.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        log(f"install command timed out after {config.timeout_seconds}s")
        if exc.stdout:
            log_block("stdout", exc.stdout)
        if exc.stderr:
            log_block("stderr", exc.stderr)
        return 124

    if completed.stdout:
        log_block("stdout", completed.stdout)
    if completed.stderr:
        log_block("stderr", completed.stderr)
    log(f"install command exit code: {completed.returncode}")
    return completed.returncode


def restart_axe(
    attempts: int,
    *,
    start: Callable[[], int | None],
    is_running: Callable[[], bool],
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> bool:
    for attempt in range(1, attempts + 1):
        log(f"starting axe (attempt {attempt}/{attempts})")
        try:
            pid = start()
        except Exception as exc:
            log(f"start axe attempt failed: {type(exc).__name__}: {exc}")
            pid = None
        if pid is not None and is_running():
            log(f"axe restart succeeded: pid {pid}")
            return True
        sleep(min(attempt, 5))
    log("axe restart failed after all attempts")
    return False


def write_completion_record(
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


def log_message(message: str) -> None:
    timestamp = local_now().isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


def log_block(
    label: str,
    text: str | bytes,
    *,
    log: Callable[[str], None] = log_message,
) -> None:
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    log(f"{label}:")
    print(text.rstrip(), flush=True)
