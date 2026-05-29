"""Checkpointed automatic episode batch builder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
import errno
import fcntl
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, TextIO

from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.memory.episodes._collector_utils import compact_timestamp
from sase.memory.episodes.builder import build_episode
from sase.memory.episodes.collector import EpisodeSelector
from sase.memory.episodes.components import (
    EpisodeComponentPlan,
    build_episode_component_plans,
    collect_episode_draft_for_component_plan,
)
from sase.memory.episodes.identity import read_episode_alias_rows_unlocked
from sase.memory.episodes.index import (
    episode_index_lock_path,
    episode_index_path,
    project_episodes_dir,
    read_episode_index,
    read_episode_index_unlocked,
)
from sase.memory.episodes.inventory import canonical_index_rows
from sase.memory.episodes.source_refs import normalize_source_path
from sase.memory.episodes.storage import write_project_episode_unlocked

AUTO_BUILD_STATE_SCHEMA_VERSION = 1
BUILD_STATE_FILE_NAME = "build_state.json"
BUILD_STATE_PREV_FILE_NAME = "build_state.json.prev"
METRICS_DIR_NAME = "metrics"
DEFAULT_AUTO_BUILD_LIMIT = 50


@dataclass(frozen=True)
class _EpisodeAutoBuildState:
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
class _EpisodeAutoBuildMetrics:
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
class _HeldLock:
    handle: TextIO
    wait_seconds: float


def run_episode_auto_build(
    project: str,
    *,
    projects_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    limit: int | None = DEFAULT_AUTO_BUILD_LIMIT,
    dry_run: bool = False,
    now_fn: Callable[[], str] | None = None,
) -> EpisodeAutoBuildReport:
    """Run one checkpointed automatic episode build cycle."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be >= 1")
    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    index_path = episode_index_path(project, projects_root=projects_root)
    started_at = _now_iso(now_fn)
    wall_start = time.perf_counter()
    held = _try_acquire_episode_lock(episode_index_lock_path(index_path), fcntl.LOCK_EX)
    if held is None:
        return EpisodeAutoBuildReport(
            project=project,
            episodes_dir=str(episodes_dir.resolve(strict=False)),
            status="lock_busy",
            message="Episode index lock is held by another writer.",
            dry_run=dry_run,
            lock_acquired=False,
            lock_wait_seconds=0.0,
            checkpoint_before=None,
            checkpoint_after=None,
        )

    try:
        state_status, state, state_error = _read_build_state_details_unlocked(
            episodes_dir,
            project,
        )
        if state is None:
            return EpisodeAutoBuildReport(
                project=project,
                episodes_dir=str(episodes_dir.resolve(strict=False)),
                status="state_corrupt",
                message="build_state.json is corrupt; run doctor to inspect or repair.",
                dry_run=dry_run,
                lock_acquired=True,
                lock_wait_seconds=held.wait_seconds,
                checkpoint_before=None,
                checkpoint_after=None,
                warnings=[state_error or "invalid build_state.json"],
                error=state_error,
            )
        if _in_backoff(state, started_at):
            return EpisodeAutoBuildReport(
                project=project,
                episodes_dir=str(episodes_dir.resolve(strict=False)),
                status="backoff",
                message=f"Automatic builder is in backoff until {state.backoff_until}.",
                dry_run=dry_run,
                lock_acquired=True,
                lock_wait_seconds=held.wait_seconds,
                checkpoint_before=state.checkpoint_timestamp,
                checkpoint_after=state.checkpoint_timestamp,
            )

        try:
            return _run_auto_build_locked(
                project,
                state=state,
                state_status=state_status,
                episodes_dir=episodes_dir,
                projects_root=projects_root,
                repo_root=repo_root,
                limit=limit,
                dry_run=dry_run,
                started_at=started_at,
                wall_start=wall_start,
                lock_wait_seconds=held.wait_seconds,
                now_fn=now_fn,
            )
        except Exception as exc:
            finished_at = _now_iso(now_fn)
            failed_state = _failure_state(
                state,
                started_at=started_at,
                finished_at=finished_at,
                error=str(exc),
            )
            if not dry_run:
                _write_build_state_unlocked(episodes_dir, failed_state)
                metric = _metrics_row(
                    project,
                    state=failed_state,
                    started_at=started_at,
                    finished_at=finished_at,
                    status="error",
                    dry_run=dry_run,
                    limit=limit,
                    checkpoint_before=state.checkpoint_timestamp,
                    seeds_scanned=0,
                    seeds_skipped=0,
                    components_planned=0,
                    components_built=0,
                    aliases_written=0,
                    changed_count=0,
                    unchanged_count=0,
                    importance_histogram={},
                    lock_wait_seconds=held.wait_seconds,
                    wall_start=wall_start,
                    error=str(exc),
                )
                metrics_path = _append_metrics_unlocked(episodes_dir, metric)
            else:
                metric = None
                metrics_path = None
            return EpisodeAutoBuildReport(
                project=project,
                episodes_dir=str(episodes_dir.resolve(strict=False)),
                status="error",
                message=f"Automatic builder failed: {exc}",
                dry_run=dry_run,
                lock_acquired=True,
                lock_wait_seconds=held.wait_seconds,
                checkpoint_before=state.checkpoint_timestamp,
                checkpoint_after=state.checkpoint_timestamp,
                metrics_path=(
                    str(metrics_path.resolve(strict=False))
                    if metrics_path is not None
                    else None
                ),
                metrics=metric.to_json_dict() if metric is not None else None,
                error=str(exc),
            )
    finally:
        _release_episode_lock(held)


def read_episode_auto_build_status(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> EpisodeAutoBuildStatus:
    """Read automatic builder state and latest metrics for a project."""

    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    index_path = episode_index_path(project, projects_root=projects_root)
    state_status, state, state_error = _read_build_state_details(episodes_dir, project)
    latest_metrics = _read_latest_metrics(episodes_dir)
    return EpisodeAutoBuildStatus(
        project=project,
        episodes_dir=str(episodes_dir.resolve(strict=False)),
        index_path=str(index_path.resolve(strict=False)),
        lock_available=_lock_available(episode_index_lock_path(index_path)),
        state_status=state_status,
        state_error=state_error,
        state=state.to_json_dict() if state is not None else None,
        episode_count=len(canonical_index_rows(project, projects_root)),
        index_row_count=len(read_episode_index(project, projects_root=projects_root)),
        latest_metrics=latest_metrics,
    )


def build_episode_auto_doctor_report(
    project: str,
    *,
    projects_root: Path | str | None = None,
    repair: bool = False,
) -> EpisodeDoctorReport:
    """Inspect and optionally repair automatic episode builder state."""

    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    index_path = episode_index_path(project, projects_root=projects_root)
    held = _try_acquire_episode_lock(episode_index_lock_path(index_path), fcntl.LOCK_EX)
    if held is None:
        return EpisodeDoctorReport(
            project=project,
            episodes_dir=str(episodes_dir.resolve(strict=False)),
            status="ERROR",
            checks=[
                _doctor_check(
                    "lock",
                    "ERROR",
                    "Episode index lock is held by another writer.",
                )
            ],
            repairs=[],
            repaired=False,
            lock_acquired=False,
        )
    try:
        checks: list[dict[str, Any]] = []
        repairs: list[dict[str, Any]] = []
        state_status, state, state_error = _read_build_state_details_unlocked(
            episodes_dir,
            project,
        )
        prev_status, prev_state, prev_error = _read_build_state_details_unlocked(
            episodes_dir,
            project,
            previous=True,
        )
        checks.append(
            _state_doctor_check(
                state_status,
                state,
                state_error,
                prev_status=prev_status,
                prev_error=prev_error,
            )
        )
        checks.append(
            _doctor_check(
                "build_state_prev",
                "OK" if prev_status in {"ok", "missing"} else "WARN",
                _prev_state_summary(prev_status, prev_error),
            )
        )
        index_rows = read_episode_index_unlocked(index_path)
        checks.append(
            _doctor_check(
                "index",
                "OK",
                f"Episode index has {len(index_rows)} row(s).",
            )
        )
        temp_dirs = _storage_temp_dirs(episodes_dir)
        if temp_dirs:
            repairs.append(
                _repair_plan(
                    "remove_temp_dirs",
                    f"Remove {len(temp_dirs)} abandoned episode temp dir(s).",
                )
            )
            checks.append(
                _doctor_check(
                    "temp_dirs",
                    "WARN",
                    f"Found {len(temp_dirs)} abandoned episode temp dir(s).",
                    details=[str(path) for path in temp_dirs],
                )
            )
        else:
            checks.append(
                _doctor_check("temp_dirs", "OK", "No abandoned temp dirs found.")
            )
        if state_status == "corrupt" and prev_status == "ok" and prev_state is not None:
            repairs.append(
                _repair_plan(
                    "restore_build_state_prev",
                    "Restore build_state.json from build_state.json.prev.",
                )
            )

        executed_repairs = False
        if repair:
            executed_repairs = _execute_repairs(
                episodes_dir,
                project,
                repairs=repairs,
                prev_state=prev_state,
                temp_dirs=temp_dirs,
            )
            repairs = [dict(item, executed=True) for item in repairs]
        aggregate = _aggregate_doctor_status(checks)
        return EpisodeDoctorReport(
            project=project,
            episodes_dir=str(episodes_dir.resolve(strict=False)),
            status=aggregate,
            checks=checks,
            repairs=repairs,
            repaired=executed_repairs,
            lock_acquired=True,
        )
    finally:
        _release_episode_lock(held)


def _run_auto_build_locked(
    project: str,
    *,
    state: _EpisodeAutoBuildState,
    state_status: str,
    episodes_dir: Path,
    projects_root: Path | str | None,
    repo_root: Path | str | None,
    limit: int | None,
    dry_run: bool,
    started_at: str,
    wall_start: float,
    lock_wait_seconds: float,
    now_fn: Callable[[], str] | None,
) -> EpisodeAutoBuildReport:
    del state_status
    scan_root = episodes_dir.parent.parent
    if projects_root is not None:
        scan_root = Path(projects_root).expanduser()
    scan = _scan_project(project, scan_root)
    candidates, skipped, scanned = _candidate_done_records(scan, state, limit)
    if not candidates:
        return EpisodeAutoBuildReport(
            project=project,
            episodes_dir=str(episodes_dir.resolve(strict=False)),
            status="idle",
            message="No new done markers matched the automatic builder checkpoint.",
            dry_run=dry_run,
            lock_acquired=True,
            lock_wait_seconds=lock_wait_seconds,
            checkpoint_before=state.checkpoint_timestamp,
            checkpoint_after=state.checkpoint_timestamp,
            seeds_scanned=scanned,
            seeds_skipped=skipped,
        )

    plans = _plans_for_candidate_records(
        project,
        candidates,
        scan=scan,
        projects_root=scan_root,
        repo_root=repo_root,
    )
    component_rows: list[dict[str, Any]] = []
    changed_count = 0
    unchanged_count = 0
    aliases_written = 0
    importance_histogram: dict[str, int] = {}
    for plan in plans:
        draft = collect_episode_draft_for_component_plan(
            plan,
            projects_root=scan_root,
            scan=scan,
            repo_root=repo_root if repo_root is not None else Path.cwd(),
        )
        episode = build_episode(draft)
        before_aliases = {
            row.alias_episode_id
            for row in read_episode_alias_rows_unlocked(episodes_dir)
        }
        if dry_run:
            stored_episode_id = episode.episode_id
            changed = False
            band = episode.importance_band
        else:
            write_result = write_project_episode_unlocked(
                episode,
                projects_root=scan_root,
            )
            after_aliases = {
                row.alias_episode_id
                for row in read_episode_alias_rows_unlocked(episodes_dir)
            }
            aliases_written += len(after_aliases - before_aliases)
            stored_episode_id = write_result.episode_id
            changed = write_result.changed
            band = write_result.index_row.importance_band
        if changed:
            changed_count += 1
        else:
            unchanged_count += 1
        importance_histogram[band] = importance_histogram.get(band, 0) + 1
        component_rows.append(
            {
                "component_key": plan.component_key,
                "episode_id": stored_episode_id,
                "importance_band": band,
                "source_count": len(episode.sources),
                "title": episode.title,
                "changed": changed,
            }
        )

    finished_at = _now_iso(now_fn)
    if dry_run:
        state_after = state
        metrics_path = None
        metric = _metrics_row(
            project,
            state=state_after,
            started_at=started_at,
            finished_at=finished_at,
            status="dry_run",
            dry_run=True,
            limit=limit,
            checkpoint_before=state.checkpoint_timestamp,
            seeds_scanned=scanned,
            seeds_skipped=skipped,
            components_planned=len(plans),
            components_built=len(component_rows),
            aliases_written=0,
            changed_count=0,
            unchanged_count=len(component_rows),
            importance_histogram=importance_histogram,
            lock_wait_seconds=lock_wait_seconds,
            wall_start=wall_start,
        )
    else:
        state_after = _success_state(
            state,
            candidates,
            started_at=started_at,
            finished_at=finished_at,
            candidate_count=len(candidates),
            component_count=len(component_rows),
        )
        metric = _metrics_row(
            project,
            state=state_after,
            started_at=started_at,
            finished_at=finished_at,
            status="success",
            dry_run=False,
            limit=limit,
            checkpoint_before=state.checkpoint_timestamp,
            seeds_scanned=scanned,
            seeds_skipped=skipped,
            components_planned=len(plans),
            components_built=len(component_rows),
            aliases_written=aliases_written,
            changed_count=changed_count,
            unchanged_count=unchanged_count,
            importance_histogram=importance_histogram,
            lock_wait_seconds=lock_wait_seconds,
            wall_start=wall_start,
        )
        metrics_path = _append_metrics_unlocked(episodes_dir, metric)
        state_after = replace(
            state_after,
            last_metrics_path=str(metrics_path.resolve(strict=False)),
        )
        _write_build_state_unlocked(episodes_dir, state_after)

    return EpisodeAutoBuildReport(
        project=project,
        episodes_dir=str(episodes_dir.resolve(strict=False)),
        status="dry_run" if dry_run else "success",
        message=(
            f"Would build {len(component_rows)} component episode(s)."
            if dry_run
            else f"Built {len(component_rows)} component episode(s)."
        ),
        dry_run=dry_run,
        lock_acquired=True,
        lock_wait_seconds=lock_wait_seconds,
        checkpoint_before=state.checkpoint_timestamp,
        checkpoint_after=state_after.checkpoint_timestamp,
        seeds_scanned=scanned,
        seeds_skipped=skipped,
        candidates=[
            normalize_source_path(record.artifact_dir) for record in candidates
        ],
        components=component_rows,
        component_count=len(component_rows),
        built_count=len(component_rows),
        changed_count=changed_count,
        unchanged_count=unchanged_count,
        aliases_written=aliases_written,
        metrics_path=(
            str(metrics_path.resolve(strict=False))
            if metrics_path is not None
            else None
        ),
        metrics=metric.to_json_dict(),
    )


def _scan_project(project: str, projects_root: Path) -> AgentArtifactScanWire:
    return scan_agent_artifacts(
        projects_root,
        AgentArtifactScanOptionsWire(
            include_prompt_step_markers=True,
            include_raw_prompt_snippets=False,
            include_done_markers=True,
            include_workflow_state=True,
            include_waiting=True,
            only_projects=(project,),
        ),
    )


def _candidate_done_records(
    scan: AgentArtifactScanWire,
    state: _EpisodeAutoBuildState,
    limit: int | None,
) -> tuple[list[AgentArtifactRecordWire], int, int]:
    done_records = [
        record
        for record in sorted(scan.records, key=_record_sort_key)
        if record.has_done_marker
    ]
    candidates = [
        record for record in done_records if not _record_is_checkpointed(record, state)
    ]
    if limit is not None and len(candidates) > limit:
        skipped = len(done_records) - limit
        candidates = candidates[:limit]
    else:
        skipped = len(done_records) - len(candidates)
    return candidates, skipped, len(done_records)


def _record_is_checkpointed(
    record: AgentArtifactRecordWire,
    state: _EpisodeAutoBuildState,
) -> bool:
    if state.checkpoint_timestamp is None:
        return False
    timestamp = compact_timestamp(record.timestamp)
    if timestamp < state.checkpoint_timestamp:
        return True
    if timestamp > state.checkpoint_timestamp:
        return False
    return normalize_source_path(record.artifact_dir) in state.checkpoint_artifact_dirs


def _plans_for_candidate_records(
    project: str,
    records: list[AgentArtifactRecordWire],
    *,
    scan: AgentArtifactScanWire,
    projects_root: Path,
    repo_root: Path | str | None,
) -> list[EpisodeComponentPlan]:
    plans_by_key: dict[str, EpisodeComponentPlan] = {}
    for record in records:
        plans = build_episode_component_plans(
            EpisodeSelector(project=project, artifact_dir=record.artifact_dir),
            projects_root=projects_root,
            scan=scan,
            repo_root=repo_root if repo_root is not None else Path.cwd(),
        )
        for plan in plans:
            plans_by_key[plan.component_key] = plan
    return sorted(
        plans_by_key.values(),
        key=lambda plan: (
            plan.project,
            plan.root_timestamp or "",
            plan.root_chat_key or "",
            plan.component_key,
        ),
    )


def _success_state(
    state: _EpisodeAutoBuildState,
    records: list[AgentArtifactRecordWire],
    *,
    started_at: str,
    finished_at: str,
    candidate_count: int,
    component_count: int,
) -> _EpisodeAutoBuildState:
    checkpoint = max(compact_timestamp(record.timestamp) for record in records)
    previous_dirs = (
        set(state.checkpoint_artifact_dirs)
        if state.checkpoint_timestamp == checkpoint
        else set()
    )
    checkpoint_dirs = previous_dirs | {
        normalize_source_path(record.artifact_dir)
        for record in records
        if compact_timestamp(record.timestamp) == checkpoint
    }
    return _EpisodeAutoBuildState(
        project=state.project,
        checkpoint_timestamp=checkpoint,
        checkpoint_artifact_dirs=tuple(sorted(checkpoint_dirs)),
        last_success_at=finished_at,
        last_failure_at=None,
        last_error=None,
        consecutive_failures=0,
        backoff_until=None,
        last_cycle_started_at=started_at,
        last_cycle_finished_at=finished_at,
        last_metrics_path=state.last_metrics_path,
        last_candidate_count=candidate_count,
        last_component_count=component_count,
    )


def _failure_state(
    state: _EpisodeAutoBuildState,
    *,
    started_at: str,
    finished_at: str,
    error: str,
) -> _EpisodeAutoBuildState:
    consecutive_failures = state.consecutive_failures + 1
    backoff_seconds = min(300, 30 * (2 ** (consecutive_failures - 1)))
    backoff_until = (
        (
            datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
            + timedelta(seconds=backoff_seconds)
        )
        .isoformat()
        .replace("+00:00", "Z")
    )
    return replace(
        state,
        last_failure_at=finished_at,
        last_error=error,
        consecutive_failures=consecutive_failures,
        backoff_until=backoff_until,
        last_cycle_started_at=started_at,
        last_cycle_finished_at=finished_at,
    )


def _metrics_row(
    project: str,
    *,
    state: _EpisodeAutoBuildState,
    started_at: str,
    finished_at: str,
    status: str,
    dry_run: bool,
    limit: int | None,
    checkpoint_before: str | None,
    seeds_scanned: int,
    seeds_skipped: int,
    components_planned: int,
    components_built: int,
    aliases_written: int,
    changed_count: int,
    unchanged_count: int,
    importance_histogram: dict[str, int],
    lock_wait_seconds: float,
    wall_start: float,
    error: str | None = None,
) -> _EpisodeAutoBuildMetrics:
    return _EpisodeAutoBuildMetrics(
        schema_version=AUTO_BUILD_STATE_SCHEMA_VERSION,
        project=project,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        dry_run=dry_run,
        limit=limit,
        checkpoint_before=checkpoint_before,
        checkpoint_after=state.checkpoint_timestamp,
        seeds_scanned=seeds_scanned,
        seeds_skipped=seeds_skipped,
        components_planned=components_planned,
        components_built=components_built,
        aliases_written=aliases_written,
        episodes_changed=changed_count,
        episodes_unchanged=unchanged_count,
        importance_histogram=dict(sorted(importance_histogram.items())),
        lock_wait_seconds=round(lock_wait_seconds, 6),
        wall_time_seconds=round(time.perf_counter() - wall_start, 6),
        consecutive_failures=state.consecutive_failures,
        backoff_until=state.backoff_until,
        error=error,
    )


def _read_build_state_details(
    episodes_dir: Path,
    project: str,
) -> tuple[str, _EpisodeAutoBuildState | None, str | None]:
    index_path = episode_index_path(project, projects_root=episodes_dir.parent.parent)
    held = _try_acquire_episode_lock(episode_index_lock_path(index_path), fcntl.LOCK_SH)
    if held is None:
        return _read_build_state_details_unlocked(episodes_dir, project)
    try:
        return _read_build_state_details_unlocked(episodes_dir, project)
    finally:
        _release_episode_lock(held)


def _read_build_state_details_unlocked(
    episodes_dir: Path,
    project: str,
    *,
    previous: bool = False,
) -> tuple[str, _EpisodeAutoBuildState | None, str | None]:
    path = _build_state_path(episodes_dir, previous=previous)
    if not path.exists():
        return "missing", _EpisodeAutoBuildState(project=project), None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return "corrupt", None, str(exc)
    if not isinstance(data, dict):
        return "corrupt", None, "state file is not a JSON object"
    try:
        return "ok", _state_from_dict(data, project), None
    except (TypeError, ValueError) as exc:
        return "corrupt", None, str(exc)


def _state_from_dict(data: dict[str, Any], project: str) -> _EpisodeAutoBuildState:
    schema_version = int(data.get("schema_version", 0))
    if schema_version < 1 or schema_version > AUTO_BUILD_STATE_SCHEMA_VERSION:
        raise ValueError(f"unsupported build state schema_version {schema_version}")
    state_project = _optional_str(data.get("project")) or project
    if state_project != project:
        raise ValueError(f"build state project {state_project!r} != {project!r}")
    dirs = data.get("checkpoint_artifact_dirs", [])
    if not isinstance(dirs, list):
        raise ValueError("checkpoint_artifact_dirs must be a list")
    return _EpisodeAutoBuildState(
        schema_version=schema_version,
        project=state_project,
        checkpoint_timestamp=_optional_str(data.get("checkpoint_timestamp")),
        checkpoint_artifact_dirs=tuple(
            sorted(item for item in dirs if isinstance(item, str) and item)
        ),
        last_success_at=_optional_str(data.get("last_success_at")),
        last_failure_at=_optional_str(data.get("last_failure_at")),
        last_error=_optional_str(data.get("last_error")),
        consecutive_failures=int(data.get("consecutive_failures", 0) or 0),
        backoff_until=_optional_str(data.get("backoff_until")),
        last_cycle_started_at=_optional_str(data.get("last_cycle_started_at")),
        last_cycle_finished_at=_optional_str(data.get("last_cycle_finished_at")),
        last_metrics_path=_optional_str(data.get("last_metrics_path")),
        last_candidate_count=int(data.get("last_candidate_count", 0) or 0),
        last_component_count=int(data.get("last_component_count", 0) or 0),
    )


def _write_build_state_unlocked(
    episodes_dir: Path,
    state: _EpisodeAutoBuildState,
) -> None:
    path = _build_state_path(episodes_dir)
    current_status, _current_state, _current_error = _read_build_state_details_unlocked(
        episodes_dir,
        state.project,
    )
    if current_status == "ok" and path.exists():
        prev_path = _build_state_path(episodes_dir, previous=True)
        _atomic_write_text(prev_path, path.read_text(encoding="utf-8"))
    _atomic_write_json(path, state.to_json_dict())
    _fsync_dir(episodes_dir)


def _append_metrics_unlocked(
    episodes_dir: Path,
    metric: _EpisodeAutoBuildMetrics,
) -> Path:
    metrics_dir = episodes_dir / METRICS_DIR_NAME
    metrics_dir.mkdir(parents=True, exist_ok=True)
    path = metrics_dir / f"{metric.finished_at[:7].replace('-', '')}.jsonl"
    line = json.dumps(metric.to_json_dict(), sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_dir(metrics_dir)
    return path


def _read_latest_metrics(episodes_dir: Path) -> dict[str, Any] | None:
    metrics_dir = episodes_dir / METRICS_DIR_NAME
    if not metrics_dir.is_dir():
        return None
    for path in sorted(metrics_dir.glob("*.jsonl"), reverse=True):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return None


def _try_acquire_episode_lock(lock_path: Path, flags: int) -> _HeldLock | None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    handle = lock_path.open("a", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), flags | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            return None
        raise
    return _HeldLock(handle=handle, wait_seconds=time.perf_counter() - started)


def _release_episode_lock(lock: _HeldLock) -> None:
    try:
        fcntl.flock(lock.handle.fileno(), fcntl.LOCK_UN)
    finally:
        lock.handle.close()


def _lock_available(lock_path: Path) -> bool:
    held = _try_acquire_episode_lock(lock_path, fcntl.LOCK_EX)
    if held is None:
        return False
    _release_episode_lock(held)
    return True


def _in_backoff(state: _EpisodeAutoBuildState, now: str) -> bool:
    return state.backoff_until is not None and now < state.backoff_until


def _record_sort_key(record: AgentArtifactRecordWire) -> tuple[str, str, str]:
    return (
        compact_timestamp(record.timestamp),
        record.workflow_dir_name,
        normalize_source_path(record.artifact_dir),
    )


def _build_state_path(episodes_dir: Path, *, previous: bool = False) -> Path:
    name = BUILD_STATE_PREV_FILE_NAME if previous else BUILD_STATE_FILE_NAME
    return episodes_dir / name


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    _atomic_write_text(path, payload)


def _atomic_write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _storage_temp_dirs(episodes_dir: Path) -> list[Path]:
    if not episodes_dir.exists():
        return []
    return [
        path
        for path in sorted(episodes_dir.iterdir(), key=lambda item: item.name)
        if path.is_dir() and path.name.startswith(".") and ".tmp." in path.name
    ]


def _execute_repairs(
    episodes_dir: Path,
    project: str,
    *,
    repairs: list[dict[str, Any]],
    prev_state: _EpisodeAutoBuildState | None,
    temp_dirs: list[Path],
) -> bool:
    executed = False
    repair_ids = {repair["id"] for repair in repairs}
    if "restore_build_state_prev" in repair_ids and prev_state is not None:
        _write_build_state_unlocked(episodes_dir, prev_state)
        executed = True
    if "remove_temp_dirs" in repair_ids:
        for path in temp_dirs:
            shutil.rmtree(path, ignore_errors=True)
        _fsync_dir(episodes_dir)
        executed = True
    del project
    return executed


def _state_doctor_check(
    status: str,
    state: _EpisodeAutoBuildState | None,
    error: str | None,
    *,
    prev_status: str,
    prev_error: str | None,
) -> dict[str, Any]:
    if status == "ok" and state is not None:
        return _doctor_check(
            "build_state",
            "OK",
            "build_state.json is valid.",
            details=[
                f"checkpoint={state.checkpoint_timestamp or '-'}",
                f"consecutive_failures={state.consecutive_failures}",
            ],
        )
    if status == "missing":
        return _doctor_check(
            "build_state",
            "OK",
            "build_state.json is not present yet.",
        )
    if prev_status == "ok":
        return _doctor_check(
            "build_state",
            "WARN",
            "build_state.json is corrupt but build_state.json.prev is valid.",
            details=[error or "invalid state"],
        )
    detail = error or prev_error or "invalid state"
    return _doctor_check(
        "build_state",
        "ERROR",
        "build_state.json is corrupt and no valid previous state is available.",
        details=[detail],
    )


def _prev_state_summary(status: str, error: str | None) -> str:
    if status == "ok":
        return "build_state.json.prev is valid."
    if status == "missing":
        return "build_state.json.prev is not present."
    return f"build_state.json.prev is corrupt: {error or 'invalid state'}"


def _doctor_check(
    check_id: str,
    status: str,
    summary: str,
    *,
    details: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "summary": summary,
        "details": details or [],
    }


def _repair_plan(repair_id: str, summary: str) -> dict[str, Any]:
    return {"id": repair_id, "summary": summary, "executed": False}


def _aggregate_doctor_status(checks: list[dict[str, Any]]) -> str:
    statuses = {str(check.get("status")) for check in checks}
    if "ERROR" in statuses:
        return "ERROR"
    if "WARN" in statuses:
        return "WARN"
    return "OK"


def _now_iso(now_fn: Callable[[], str] | None) -> str:
    if now_fn is not None:
        return now_fn()
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "AUTO_BUILD_STATE_SCHEMA_VERSION",
    "BUILD_STATE_FILE_NAME",
    "BUILD_STATE_PREV_FILE_NAME",
    "DEFAULT_AUTO_BUILD_LIMIT",
    "EpisodeAutoBuildReport",
    "EpisodeAutoBuildStatus",
    "EpisodeDoctorReport",
    "build_episode_auto_doctor_report",
    "read_episode_auto_build_status",
    "run_episode_auto_build",
]
