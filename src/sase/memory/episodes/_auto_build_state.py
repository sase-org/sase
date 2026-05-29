"""Build-state persistence for the automatic episode builder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.memory.episodes._auto_build_locks import (
    release_episode_lock,
    try_acquire_episode_lock,
)
from sase.memory.episodes._auto_build_types import (
    AUTO_BUILD_STATE_SCHEMA_VERSION,
    BUILD_STATE_FILE_NAME,
    BUILD_STATE_PREV_FILE_NAME,
    EpisodeAutoBuildStateRecord,
)
from sase.memory.episodes._collector_utils import compact_timestamp
from sase.memory.episodes.index import episode_index_lock_path, episode_index_path
from sase.memory.episodes.source_refs import normalize_source_path


def success_state(
    state: EpisodeAutoBuildStateRecord,
    records: list[AgentArtifactRecordWire],
    *,
    started_at: str,
    finished_at: str,
    candidate_count: int,
    component_count: int,
) -> EpisodeAutoBuildStateRecord:
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
    return EpisodeAutoBuildStateRecord(
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


def failure_state(
    state: EpisodeAutoBuildStateRecord,
    *,
    started_at: str,
    finished_at: str,
    error: str,
) -> EpisodeAutoBuildStateRecord:
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


def read_build_state_details(
    episodes_dir: Path,
    project: str,
) -> tuple[str, EpisodeAutoBuildStateRecord | None, str | None]:
    index_path = episode_index_path(project, projects_root=episodes_dir.parent.parent)
    held = try_acquire_episode_lock(episode_index_lock_path(index_path), fcntl.LOCK_SH)
    if held is None:
        return read_build_state_details_unlocked(episodes_dir, project)
    try:
        return read_build_state_details_unlocked(episodes_dir, project)
    finally:
        release_episode_lock(held)


def read_build_state_details_unlocked(
    episodes_dir: Path,
    project: str,
    *,
    previous: bool = False,
) -> tuple[str, EpisodeAutoBuildStateRecord | None, str | None]:
    path = _build_state_path(episodes_dir, previous=previous)
    if not path.exists():
        return "missing", EpisodeAutoBuildStateRecord(project=project), None
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


def _state_from_dict(
    data: dict[str, Any],
    project: str,
) -> EpisodeAutoBuildStateRecord:
    schema_version = int(data.get("schema_version", 0))
    if schema_version < 1 or schema_version > AUTO_BUILD_STATE_SCHEMA_VERSION:
        raise ValueError(f"unsupported build state schema_version {schema_version}")
    state_project = _optional_str(data.get("project")) or project
    if state_project != project:
        raise ValueError(f"build state project {state_project!r} != {project!r}")
    dirs = data.get("checkpoint_artifact_dirs", [])
    if not isinstance(dirs, list):
        raise ValueError("checkpoint_artifact_dirs must be a list")
    return EpisodeAutoBuildStateRecord(
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


def write_build_state_unlocked(
    episodes_dir: Path,
    state: EpisodeAutoBuildStateRecord,
) -> None:
    path = _build_state_path(episodes_dir)
    current_status, _current_state, _current_error = read_build_state_details_unlocked(
        episodes_dir,
        state.project,
    )
    if current_status == "ok" and path.exists():
        prev_path = _build_state_path(episodes_dir, previous=True)
        _atomic_write_text(prev_path, path.read_text(encoding="utf-8"))
    _atomic_write_json(path, state.to_json_dict())
    fsync_dir(episodes_dir)


def in_backoff(state: EpisodeAutoBuildStateRecord, now: str) -> bool:
    return state.backoff_until is not None and now < state.backoff_until


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


def now_iso(now_fn: Callable[[], str] | None) -> str:
    if now_fn is not None:
        return now_fn()
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
