"""Locked build-cycle execution for the automatic episode builder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.memory.episodes._auto_build_metrics import (
    append_metrics_unlocked,
    metrics_row,
)
from sase.memory.episodes._auto_build_planning import (
    candidate_done_records,
    plans_for_candidate_records,
    scan_project,
)
from sase.memory.episodes._auto_build_state import (
    now_iso,
    success_state,
    write_build_state_unlocked,
)
from sase.memory.episodes._auto_build_types import (
    EpisodeAutoBuildReport,
    EpisodeAutoBuildStateRecord,
)
from sase.memory.episodes.builder import build_episode
from sase.memory.episodes.components import collect_episode_draft_for_component_plan
from sase.memory.episodes.identity import read_episode_alias_rows_unlocked
from sase.memory.episodes.source_refs import normalize_source_path
from sase.memory.episodes.storage import EpisodeWriteResult

EpisodeWriter = Callable[..., EpisodeWriteResult]


def run_auto_build_locked(
    project: str,
    *,
    state: EpisodeAutoBuildStateRecord,
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
    write_episode_unlocked: EpisodeWriter,
) -> EpisodeAutoBuildReport:
    del state_status
    scan_root = episodes_dir.parent.parent
    if projects_root is not None:
        scan_root = Path(projects_root).expanduser()
    scan = scan_project(project, scan_root)
    candidates, skipped, scanned = candidate_done_records(scan, state, limit)
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

    plans = plans_for_candidate_records(
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
            write_result = write_episode_unlocked(
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

    finished_at = now_iso(now_fn)
    if dry_run:
        state_after = state
        metrics_path = None
        metric = metrics_row(
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
        state_after = success_state(
            state,
            candidates,
            started_at=started_at,
            finished_at=finished_at,
            candidate_count=len(candidates),
            component_count=len(component_rows),
        )
        metric = metrics_row(
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
        metrics_path = append_metrics_unlocked(episodes_dir, metric)
        state_after = replace(
            state_after,
            last_metrics_path=str(metrics_path.resolve(strict=False)),
        )
        write_build_state_unlocked(episodes_dir, state_after)

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
