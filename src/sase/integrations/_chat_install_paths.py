"""Filesystem paths and identifiers for chat install/update jobs."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path

from sase.core.paths import sase_subdir

_STATE_DIR: Path | None = None
_LOG_DIR: Path | None = None
_COMPLETIONS_DIR: Path | None = None
_JOBS_DIR: Path | None = None
_LOCK_PATH: Path | None = None
_LOCK_FD_ENV = "SASE_CHAT_INSTALL_LOCK_FD"


def state_dir() -> Path:
    return _STATE_DIR or sase_subdir("chat_install")


def _log_dir() -> Path:
    return _LOG_DIR or state_dir() / "logs"


def _completions_dir() -> Path:
    return _COMPLETIONS_DIR or state_dir() / "completions"


def _jobs_dir() -> Path:
    return _JOBS_DIR or state_dir() / "jobs"


def lock_path() -> Path:
    return _LOCK_PATH or state_dir() / "install.lock"


def new_job_id() -> str:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{os.getpid()}_{uuid.uuid4().hex[:8]}"


def new_log_path(job_id: str | None = None) -> Path:
    current_log_dir = _log_dir()
    current_log_dir.mkdir(parents=True, exist_ok=True)
    if job_id is None:
        job_id = new_job_id()
    return current_log_dir / f"install_{job_id}.log"


def completion_path(job_id: str) -> Path:
    current_completions_dir = _completions_dir()
    current_completions_dir.mkdir(parents=True, exist_ok=True)
    return current_completions_dir / f"{job_id}.json"


def job_state_path(job_id: str) -> Path:
    current_jobs_dir = _jobs_dir()
    current_jobs_dir.mkdir(parents=True, exist_ok=True)
    return current_jobs_dir / f"{job_id}.json"


def valid_job_id(job_id: str) -> bool:
    return (
        0 < len(job_id) <= 128
        and job_id not in {".", ".."}
        and all(
            char.isascii() and (char.isalnum() or char in {"_", "-", "."})
            for char in job_id
        )
    )


def shorten_home(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home) :] if text.startswith(home + os.sep) else text
