"""Shared types for the automatic episode builder."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, TextIO

AUTO_BUILD_STATE_SCHEMA_VERSION = 1
BUILD_STATE_FILE_NAME = "build_state.json"
BUILD_STATE_PREV_FILE_NAME = "build_state.json.prev"
METRICS_DIR_NAME = "metrics"
DEFAULT_AUTO_BUILD_LIMIT = 50


@dataclass(frozen=True)
class EpisodeAutoBuildStateRecord:
    """Durable checkpoint for one project's automatic episode builder."""

    schema_version: int = AUTO_BUILD_STATE_SCHEMA_VERSION
    project: str = ""
    checkpoint_timestamp: str | None = None
    checkpoint_artifact_dirs: tuple[str, ...] = ()
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    backoff_until: str | None = None
    last_cycle_started_at: str | None = None
    last_cycle_finished_at: str | None = None
    last_metrics_path: str | None = None
    last_candidate_count: int = 0
    last_component_count: int = 0

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checkpoint_artifact_dirs"] = list(self.checkpoint_artifact_dirs)
        return payload


@dataclass(frozen=True)
class EpisodeAutoBuildMetricsRecord:
    """One JSONL metrics row for an automatic builder cycle."""

    schema_version: int
    project: str
    started_at: str
    finished_at: str
    status: str
    dry_run: bool
    limit: int | None
    checkpoint_before: str | None
    checkpoint_after: str | None
    seeds_scanned: int
    seeds_skipped: int
    components_planned: int
    components_built: int
    aliases_written: int
    episodes_changed: int
    episodes_unchanged: int
    importance_histogram: dict[str, int]
    lock_wait_seconds: float
    wall_time_seconds: float
    consecutive_failures: int
    backoff_until: str | None = None
    error: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EpisodeAutoBuildReport:
    """Structured result returned by one automatic builder invocation."""

    project: str
    episodes_dir: str
    status: str
    message: str
    dry_run: bool
    lock_acquired: bool
    lock_wait_seconds: float
    checkpoint_before: str | None
    checkpoint_after: str | None
    seeds_scanned: int = 0
    seeds_skipped: int = 0
    candidates: list[str] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    component_count: int = 0
    built_count: int = 0
    changed_count: int = 0
    unchanged_count: int = 0
    aliases_written: int = 0
    metrics_path: str | None = None
    metrics: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EpisodeAutoBuildStatus:
    """Current automatic builder status for one project."""

    project: str
    episodes_dir: str
    index_path: str
    lock_available: bool
    state_status: str
    state_error: str | None
    state: dict[str, Any] | None
    episode_count: int
    index_row_count: int
    latest_metrics: dict[str, Any] | None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EpisodeDoctorReport:
    """Health report for automatic episode builder state."""

    project: str
    episodes_dir: str
    status: str
    checks: list[dict[str, Any]]
    repairs: list[dict[str, Any]]
    repaired: bool
    lock_acquired: bool

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HeldLock:
    handle: TextIO
    wait_seconds: float


__all__ = [
    "AUTO_BUILD_STATE_SCHEMA_VERSION",
    "BUILD_STATE_FILE_NAME",
    "BUILD_STATE_PREV_FILE_NAME",
    "DEFAULT_AUTO_BUILD_LIMIT",
    "METRICS_DIR_NAME",
    "EpisodeAutoBuildReport",
    "EpisodeAutoBuildStatus",
    "EpisodeDoctorReport",
    "EpisodeAutoBuildMetricsRecord",
    "EpisodeAutoBuildStateRecord",
    "HeldLock",
]
