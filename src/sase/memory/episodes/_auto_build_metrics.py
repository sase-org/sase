"""Metrics helpers for the automatic episode builder."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

from sase.memory.episodes._auto_build_state import fsync_dir
from sase.memory.episodes._auto_build_types import (
    AUTO_BUILD_STATE_SCHEMA_VERSION,
    METRICS_DIR_NAME,
    EpisodeAutoBuildMetricsRecord,
    EpisodeAutoBuildStateRecord,
)


def metrics_row(
    project: str,
    *,
    state: EpisodeAutoBuildStateRecord,
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
) -> EpisodeAutoBuildMetricsRecord:
    return EpisodeAutoBuildMetricsRecord(
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


def append_metrics_unlocked(
    episodes_dir: Path,
    metric: EpisodeAutoBuildMetricsRecord,
) -> Path:
    metrics_dir = episodes_dir / METRICS_DIR_NAME
    metrics_dir.mkdir(parents=True, exist_ok=True)
    path = metrics_dir / f"{metric.finished_at[:7].replace('-', '')}.jsonl"
    line = json.dumps(metric.to_json_dict(), sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    fsync_dir(metrics_dir)
    return path


def read_latest_metrics(episodes_dir: Path) -> dict[str, Any] | None:
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
