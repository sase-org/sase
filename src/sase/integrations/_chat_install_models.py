"""Shared data models for chat install/update jobs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
