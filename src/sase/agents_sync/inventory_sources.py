"""Load live and dismissed agent records for inventory publication."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sase.agents_sync.bundles import (
    commit_markers,
    commit_record,
    is_primary_root,
    repository_root,
)
from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory_history import HistoricalAssociations
from sase.agents_sync.inventory_io import (
    canonical_local_name as _canonical_local_name,
    canonical_optional_name as _canonical_optional_name,
    dedupe_relationships as _dedupe_relationships,
    embedded_workflows_payload as _embedded_workflows_payload,
    inline_text as _inline_text,
    is_imported as _is_imported,
    portable_metadata as _portable_metadata,
    prompt_steps_payload as _prompt_steps_payload,
    read_json_object as _read_json_object,
    read_referenced_text as _read_referenced_text,
    read_text_bytes as _read_text_bytes,
    require_owner as _require_owner,
    source_run_id as _source_run_id,
    text as _text,
    time_text as _time_text,
)
from sase.agents_sync.inventory_models import InventoryRelationship, InventoryRun
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    globalize_agent_name,
)
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.dismissed_agents_facade import load_dismissed_bundle_summaries
from sase.core.paths import sase_projects_dir


def indexed_records(
    target: ProjectTarget,
) -> tuple[tuple[AgentArtifactRecordWire, ...], list[str]]:
    """Select project artifacts from the persistent index or a direct scan."""

    projects_root = sase_projects_dir()
    options = AgentArtifactScanOptionsWire(
        include_prompt_step_markers=True,
        include_raw_prompt_snippets=False,
        only_workflow_dirs=("ace-run",),
        max_records=None,
        newest_first=False,
        include_done_markers=True,
        include_workflow_state=True,
        include_waiting=True,
        only_projects=(target.project_key,),
        include_project_states=("all",),
    )
    diagnostics: list[str] = []
    index = default_agent_artifact_index_path()
    try:
        if index.is_file():
            snapshot = query_agent_artifact_index(
                index,
                projects_root,
                AgentArtifactIndexQueryWire(
                    include_active=True,
                    include_recent_completed=False,
                    include_full_history=True,
                    active_limit=None,
                    recent_completed_limit=None,
                    include_hidden=True,
                ),
                options,
            )
        else:
            snapshot = scan_agent_artifacts(projects_root, options)
    except (OSError, RuntimeError, ValueError, ImportError, AttributeError) as exc:
        raise AgentsSyncFormatError(
            f"could not query the agent artifact index: {exc}"
        ) from exc
    if snapshot.stats.json_decode_errors or snapshot.stats.os_errors:
        diagnostics.append(
            "artifact index scan reported "
            f"{snapshot.stats.json_decode_errors} JSON and "
            f"{snapshot.stats.os_errors} filesystem errors"
        )
    return tuple(snapshot.records), diagnostics


def run_from_artifact(
    target: ProjectTarget,
    record: AgentArtifactRecordWire,
    identity: AgentIdentitySnapshot,
    history: HistoricalAssociations,
    root_cache: dict[str, Path | None],
    git_runner: GitRunner,
) -> InventoryRun | None:
    """Build an inventory run from one indexed artifact."""

    artifact = Path(record.artifact_dir)
    projects_root = sase_projects_dir().resolve(strict=False)
    if not artifact.resolve(strict=False).is_relative_to(projects_root):
        raise AgentsSyncFormatError("indexed artifact path escapes the projects root")
    meta = _read_json_object(artifact / "agent_meta.json")
    done = _read_json_object(artifact / "done.json", required=False)
    if meta is None:
        return None
    if _is_imported(meta, done):
        return None
    raw_name = _text(meta.get("name")) or _text((done or {}).get("name"))
    if raw_name is None:
        return None
    local_name = _canonical_local_name(raw_name, identity)
    owner = _require_owner(identity)
    timestamp = record.timestamp
    source_run_id = _source_run_id(
        target.project_key,
        record.workflow_dir_name,
        _text(meta.get("artifact_agent_id")) or timestamp,
    )
    commits = {item.sha: item for item in history.run_commits.get(local_name, ())}
    for marker in commit_markers(artifact):
        sha = _text(marker.get("result")) or _text(marker.get("commit_result"))
        cwd = _text(marker.get("cwd"))
        if sha is None or cwd is None:
            continue
        root = repository_root(Path(cwd), git_runner, root_cache)
        if root is None or not is_primary_root(root, target):
            continue
        commit = commit_record(root, sha, git_runner)
        if commit is not None:
            commits[commit.sha] = commit
    prompt = _read_text_bytes(artifact / "raw_xprompt.md")
    chat = _read_referenced_text(
        meta.get("chat_path"),
        (done or {}).get("response_path"),
    )
    embedded_workflows = _embedded_workflows_payload(
        artifact / "embedded_workflows.json"
    )
    prompt_steps = _prompt_steps_payload(artifact)
    state = _artifact_state(record, done)
    metadata = _portable_metadata(meta)
    family = _canonical_optional_name(meta.get("agent_family"), identity)
    clan = _canonical_optional_name(meta.get("agent_clan"), identity)
    relationships = artifact_relationships(meta, record, identity)
    return InventoryRun(
        source_run_id,
        local_name,
        globalize_agent_name(local_name, owner),
        state,
        _time_text(meta.get("run_started_at")) or timestamp,
        _time_text((done or {}).get("finished_at")),
        None,
        metadata,
        tuple(sorted(commits.values(), key=lambda item: (item.committed_at, item.sha))),
        prompt,
        chat,
        family,
        clan,
        relationships,
        timestamp,
        embedded_workflows,
        prompt_steps,
        source_label=str(artifact),
    )


def dismissed_records(
    target: ProjectTarget,
) -> tuple[tuple[dict[str, Any], str], ...]:
    """Load archived local runs which are no longer in the live index."""

    try:
        summaries = load_dismissed_bundle_summaries(
            project_name=target.project_key,
            limit=None,
        )
    except (OSError, RuntimeError, ValueError, ImportError):
        return ()
    selected: list[tuple[dict[str, Any], str]] = []
    for summary in summaries:
        path = Path(str(summary.bundle_path))
        raw = _read_json_object(path, required=False)
        if raw is not None:
            selected.append((raw, str(path)))
    return tuple(selected)


def run_from_dismissed(
    raw: dict[str, Any],
    source_label: str,
    project_key: str,
    identity: AgentIdentitySnapshot,
    history: HistoricalAssociations,
) -> InventoryRun | None:
    """Build an inventory run from one dismissed-run bundle."""

    if _is_imported(raw, raw):
        return None
    step_output = raw.get("step_output")
    if (
        isinstance(step_output, dict)
        and step_output.get("imported_source_run_id") is not None
    ):
        return None
    raw_name = (
        _text(raw.get("agent_name"))
        or _text(raw.get("patch_name"))
        or _text(raw.get("cl_name"))
    )
    if raw_name is None:
        return None
    local_name = _canonical_local_name(raw_name, identity)
    owner = _require_owner(identity)
    raw_suffix = _text(raw.get("raw_suffix")) or _text(raw.get("start_time"))
    if raw_suffix is None:
        raw_suffix = hashlib.sha256(source_label.encode()).hexdigest()[:24]
    source_run_id = _source_run_id(project_key, "ace-run", raw_suffix)
    metadata = _portable_metadata(raw)
    prompt = _inline_text(raw, ("raw_xprompt", "raw_prompt", "prompt"))
    chat = _read_referenced_text(raw.get("response_path"), raw.get("chat_path"))
    family = _canonical_optional_name(raw.get("agent_family"), identity)
    clan = _canonical_optional_name(raw.get("agent_clan"), identity)
    relationships = dismissed_relationships(raw, identity)
    return InventoryRun(
        source_run_id,
        local_name,
        globalize_agent_name(local_name, owner),
        "dismissed",
        _time_text(raw.get("run_start_time") or raw.get("start_time")),
        _time_text(raw.get("stop_time")),
        _time_text(raw.get("stop_time")),
        metadata,
        history.run_commits.get(local_name, ()),
        prompt,
        chat,
        family,
        clan,
        relationships,
        raw_suffix,
        source_label=source_label,
    )


def artifact_relationships(
    meta: dict[str, Any],
    record: AgentArtifactRecordWire,
    identity: AgentIdentitySnapshot,
) -> tuple[InventoryRelationship, ...]:
    """Extract portable relationships from a live artifact."""

    rows: list[InventoryRelationship] = []
    parent_name = _text(meta.get("parent_agent_name"))
    if parent_name:
        rows.append(
            InventoryRelationship(
                "parent", _canonical_local_name(parent_name, identity), "name"
            )
        )
    parent_timestamp = _text(meta.get("parent_agent_timestamp"))
    if parent_timestamp:
        rows.append(InventoryRelationship("parent", parent_timestamp, "timestamp"))
    workflow_parent = _text(meta.get("parent_timestamp"))
    if workflow_parent:
        rows.append(
            InventoryRelationship("workflow_parent", workflow_parent, "timestamp")
        )
    retry = _text(meta.get("retry_of_timestamp"))
    if retry:
        rows.append(InventoryRelationship("retry", retry, "timestamp"))
    waiting = (
        record.waiting.waiting_for
        if record.waiting is not None
        else meta.get("wait_for") or ()
    )
    rows.extend(_wait_relationships(waiting, identity))
    return _dedupe_relationships(rows)


def _wait_relationships(
    waiting: object,
    identity: AgentIdentitySnapshot,
) -> list[InventoryRelationship]:
    if not isinstance(waiting, list):
        return []
    return [
        InventoryRelationship(
            "wait",
            _canonical_local_name(name, identity),
            "name",
        )
        for name in waiting
        if isinstance(name, str) and name and not name.startswith("@")
    ]


def dismissed_relationships(
    raw: dict[str, Any], identity: AgentIdentitySnapshot
) -> tuple[InventoryRelationship, ...]:
    """Extract portable relationships from a dismissed-run bundle."""

    rows: list[InventoryRelationship] = []
    for kind, key in (
        ("workflow_parent", "parent_timestamp"),
        ("retry", "retry_of_timestamp"),
    ):
        target = _text(raw.get(key))
        if target:
            rows.append(InventoryRelationship(kind, target, "timestamp"))
    waiting = raw.get("waiting_for") or ()
    rows.extend(_wait_relationships(waiting, identity))
    return _dedupe_relationships(rows)


def _artifact_state(
    record: AgentArtifactRecordWire, done: dict[str, Any] | None
) -> str:
    if record.waiting is not None or record.pending_question is not None:
        return "waiting"
    if done is None:
        return "active"
    outcome = _text(done.get("outcome")) or "failed"
    if outcome == "completed":
        return "stopped" if done.get("repeat_stopped") is True else "completed"
    return "failed"
