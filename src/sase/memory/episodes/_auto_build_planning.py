"""Candidate scanning and component planning for automatic episode builds."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.memory.episodes._auto_build_types import EpisodeAutoBuildStateRecord
from sase.memory.episodes._collector_utils import compact_timestamp
from sase.memory.episodes.collector import EpisodeSelector
from sase.memory.episodes.components import (
    EpisodeComponentPlan,
    build_episode_component_plans,
)
from sase.memory.episodes.source_refs import normalize_source_path


def scan_project(project: str, projects_root: Path) -> AgentArtifactScanWire:
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


def candidate_done_records(
    scan: AgentArtifactScanWire,
    state: EpisodeAutoBuildStateRecord,
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
    state: EpisodeAutoBuildStateRecord,
) -> bool:
    if state.checkpoint_timestamp is None:
        return False
    timestamp = compact_timestamp(record.timestamp)
    if timestamp < state.checkpoint_timestamp:
        return True
    if timestamp > state.checkpoint_timestamp:
        return False
    return normalize_source_path(record.artifact_dir) in state.checkpoint_artifact_dirs


def plans_for_candidate_records(
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


def _record_sort_key(record: AgentArtifactRecordWire) -> tuple[str, str, str]:
    return (
        compact_timestamp(record.timestamp),
        record.workflow_dir_name,
        normalize_source_path(record.artifact_dir),
    )
