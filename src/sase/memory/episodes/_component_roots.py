"""Root and metadata helpers for episode component plans."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.memory.episodes._collector_utils import compact_timestamp, read_json_object
from sase.memory.episodes._component_types import EpisodeComponentPlan
from sase.memory.episodes.identity import (
    read_episode_alias_rows,
    read_episode_member_rows,
    resolve_alias_episode_id,
)
from sase.memory.episodes.source_refs import hash_file


def plan_metadata(plan: EpisodeComponentPlan) -> dict[str, str]:
    return {
        "component_key": plan.component_key,
        "component_root_kind": plan.component_root_kind,
        "component_root_timestamp": plan.root_timestamp or "",
        "component_root_chat_key": plan.root_chat_key or "",
        "component_seed_reason": plan.seed_reason,
        "component_strong_edge_count": str(len(plan.strong_edges)),
        "existing_episode_ids": ",".join(plan.existing_episode_ids),
        "weak_changespec_names": ",".join(plan.weak_refs.changespec_names),
        "weak_bead_ids": ",".join(plan.weak_refs.bead_ids),
        "weak_agent_families": ",".join(plan.weak_refs.agent_families),
        "weak_touched_paths": ",".join(plan.weak_refs.touched_paths),
    }


def component_root(
    project: str,
    records: list[AgentArtifactRecordWire],
    chat_paths: list[str],
) -> tuple[str, str | None, str | None, str]:
    if records:
        root_kind, timestamp, workflow = _artifact_component_root(records)
        return (
            root_kind,
            timestamp,
            None,
            f"component/{root_kind}/{project}/{workflow}/{timestamp}",
        )
    root_chat_key = chat_paths[0] if chat_paths else None
    if root_chat_key is not None:
        chat_name = Path(root_chat_key).name
        digest = _chat_content_sha256_prefix(root_chat_key) or "missing"
        return (
            "chat",
            None,
            root_chat_key,
            f"component/chat/{project}/{chat_name}/{digest}",
        )
    return "empty", None, None, f"component/empty/{project}"


def _artifact_component_root(
    records: list[AgentArtifactRecordWire],
) -> tuple[str, str, str]:
    retry_root = _component_root_timestamp_choice(
        records,
        root_kind="retry-root",
        timestamp_getter=_record_retry_root_timestamp,
    )
    if retry_root is not None:
        return retry_root

    workflow_root = _component_root_timestamp_choice(
        records,
        root_kind="workflow-root",
        timestamp_getter=_record_workflow_root_timestamp,
    )
    if workflow_root is not None:
        return workflow_root

    root_record = sorted(
        records,
        key=lambda record: (
            compact_timestamp(record.timestamp),
            record.project_name,
            record.workflow_dir_name,
        ),
    )[0]
    return (
        "artifact",
        compact_timestamp(root_record.timestamp),
        root_record.workflow_dir_name,
    )


def _component_root_timestamp_choice(
    records: list[AgentArtifactRecordWire],
    *,
    root_kind: str,
    timestamp_getter: Callable[[AgentArtifactRecordWire], str | None],
) -> tuple[str, str, str] | None:
    candidates: list[tuple[str, str]] = []
    for record in records:
        timestamp = timestamp_getter(record)
        if timestamp is None:
            continue
        candidates.append(
            (
                timestamp,
                _workflow_for_component_root_timestamp(records, timestamp)
                or record.workflow_dir_name,
            )
        )
    if not candidates:
        return None
    timestamp, workflow = sorted(candidates)[0]
    return root_kind, timestamp, workflow


def _workflow_for_component_root_timestamp(
    records: list[AgentArtifactRecordWire],
    timestamp: str,
) -> str | None:
    workflows = sorted(
        {
            record.workflow_dir_name
            for record in records
            if compact_timestamp(record.timestamp) == timestamp
        }
    )
    return workflows[0] if workflows else None


def _record_retry_root_timestamp(record: AgentArtifactRecordWire) -> str | None:
    trace = read_json_object(Path(record.artifact_dir) / "episode_trace.json")
    for value in (
        trace.get("retry_chain_root_timestamp"),
        record.agent_meta.retry_chain_root_timestamp
        if record.agent_meta is not None
        else None,
        record.done.retry_chain_root_timestamp if record.done is not None else None,
    ):
        if isinstance(value, str) and value:
            return compact_timestamp(value)
    return None


def _record_workflow_root_timestamp(record: AgentArtifactRecordWire) -> str | None:
    trace = read_json_object(Path(record.artifact_dir) / "episode_trace.json")
    value = trace.get("root_timestamp")
    return compact_timestamp(value) if isinstance(value, str) and value else None


def _chat_content_sha256_prefix(path: str) -> str | None:
    chat_path = Path(path)
    if not chat_path.is_file():
        return None
    try:
        return hash_file(chat_path)[:16]
    except OSError:
        return None


def existing_episode_ids_for_members(
    project: str,
    member_keys: set[str],
    *,
    projects_root: Path,
) -> list[str]:
    episode_ids = {
        row.canonical_episode_id
        for row in read_episode_member_rows(project, projects_root=projects_root)
        if row.member_key in member_keys
    }
    aliases = read_episode_alias_rows(project, projects_root=projects_root)
    resolved = {
        resolve_alias_episode_id(episode_id, aliases) for episode_id in episode_ids
    }
    return sorted(resolved)


__all__ = [
    "component_root",
    "existing_episode_ids_for_members",
    "plan_metadata",
]
