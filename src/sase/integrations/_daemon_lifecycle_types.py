"""Shared types for the local SASE daemon lifecycle helpers."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCK_FILENAME = "daemon.lock"
LOCK_METADATA_FILENAME = "daemon.lock.json"
SOCKET_FILENAME = "sase-daemon.sock"
LOCK_SCHEMA_VERSION = 1
DEFAULT_STARTUP_TIMEOUT_SECONDS = 5.0
DEFAULT_STOP_TIMEOUT_SECONDS = 5.0


class DaemonLifecycleError(RuntimeError):
    """User-facing daemon lifecycle error."""


@dataclass(frozen=True)
class DaemonLifecycleConfig:
    command: tuple[str, ...] = ()
    sase_home: Path | None = None
    run_root: Path | None = None
    socket_path: Path | None = None
    disable_mobile_http: bool = False
    startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS


@dataclass(frozen=True)
class DaemonRuntimePaths:
    sase_home: Path
    run_root: Path
    socket_path: Path
    metadata_path: Path

    @property
    def lock_path(self) -> Path:
        return self.run_root / LOCK_FILENAME


@dataclass(frozen=True)
class DaemonLaunch:
    argv: list[str]
    paths: DaemonRuntimePaths
    foreground: bool
    startup_timeout_seconds: float


@dataclass(frozen=True)
class DaemonInspection:
    state: str
    paths: DaemonRuntimePaths
    metadata: dict[str, Any] | None = None
    message: str = ""
    rpc: dict[str, Any] | None = None

    @property
    def log_path(self) -> Path:
        return self.paths.run_root / "daemon.log"

    @property
    def lock_path(self) -> Path:
        return self.paths.lock_path

    @property
    def projection_db_path(self) -> Path:
        return self.paths.run_root / "projections" / "projection.sqlite"

    @property
    def metrics_endpoint(self) -> str | None:
        rpc = self.rpc or {}
        health = rpc.get("health") if isinstance(rpc, dict) else None
        if not isinstance(health, dict):
            return None
        details = health.get("details")
        if not isinstance(details, dict):
            return None
        metrics = details.get("metrics")
        if not isinstance(metrics, dict):
            return None
        endpoint = metrics.get("endpoint")
        return endpoint if isinstance(endpoint, str) and endpoint else None


PopenFactory = Callable[..., subprocess.Popen[Any]]
SleepFn = Callable[[float], None]
KillFn = Callable[[int, int], None]
