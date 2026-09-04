"""Build owner-sharded hood snapshots and their run payloads."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.inventory_models import InventoryLaneCommitHistory
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.publication_validation import verify_run_files
from sase.agents_sync.v2_io import file_reference, validate_snapshot, v2_json_bytes
from sase.agents_sync.v2_models import (
    ContainerKind,
    RelationshipKind,
    RunState,
    V2ContainerRecord,
    V2FileReference,
    V2HoodSnapshot,
    V2ProjectIdentity,
    V2RelationshipRecord,
    V2RelationshipTarget,
    V2RunCommitsPayload,
    V2RunMetadataPayload,
    V2RunRecord,
    V2RunStatePayload,
)
from sase.agents_sync.v2_run_io import (
    run_commits_from_json,
    run_metadata_from_json,
    run_state_from_json,
)
from sase.core.agent_archive_facade import capabilities_from_v2_run
from sase.core.agent_identity_facade import (
    AgentFamilyNameKind,
    AgentOwnerIdentity,
    agent_name_ancestors,
    globalize_agent_name,
    parse_agent_family_name,
)


def build_hood_snapshot(
    repo_root: Path,
    project: V2ProjectIdentity,
    owner: AgentOwnerIdentity,
    hood: str,
    inventory: ProjectHoodInventory,
    previous: V2HoodSnapshot | None,
) -> tuple[V2HoodSnapshot, dict[str, bytes]]:
    current = inventory.hood_runs(hood)
    family_history = inventory.family_lane_commits(hood)
    if not current and previous is None:
        from sase.agents_sync.io import AgentsSyncFormatError

        raise AgentsSyncFormatError(f"hood {hood!r} has no publishable runs")
    payload: dict[str, bytes] = {}
    current_records = tuple(
        _published_run(run, owner, project, payload) for run in current
    )
    current_ids = {run.source_run_id for run in current_records}
    current_globals = {run.global_name for run in current_records}
    prior_records = (
        tuple(
            run
            for run in previous.runs
            if run.source_run_id not in current_ids
            and run.global_name not in current_globals
        )
        if previous is not None
        else ()
    )
    for run in prior_records:
        verify_run_files(repo_root, run)
    combined = tuple(
        sorted((*prior_records, *current_records), key=lambda item: item.source_run_id)
    )
    containers = _build_containers(
        combined,
        owner,
        family_history,
        previous.containers if previous is not None else (),
    )
    relationships = _build_relationships(
        current,
        combined,
        inventory,
        owner,
        previous,
        current_ids,
    )
    ancestors = tuple(
        sorted(
            {
                globalize_agent_name(ancestor, owner)
                for run in combined
                for ancestor in agent_name_ancestors(run.local_name)
            }
        )
    )
    snapshot = V2HoodSnapshot(
        owner=owner,
        project=project,
        local_hood=hood,
        global_hood=globalize_agent_name(hood, owner),
        structural_ancestors=ancestors,
        runs=combined,
        containers=containers,
        relationships=relationships,
    )
    validate_snapshot(snapshot)
    return snapshot, payload


def _published_run(
    run: InventoryRun,
    owner: AgentOwnerIdentity,
    project: V2ProjectIdentity,
    payload: dict[str, bytes],
) -> V2RunRecord:
    root = f"agents/{run.global_name}"
    meta = V2RunMetadataPayload(
        owner,
        project,
        run.source_run_id,
        run.local_name,
        run.global_name,
        run.metadata,
    )
    state = V2RunStatePayload(
        run.source_run_id,
        cast(RunState, run.state),
        run.started_at,
        run.finished_at,
        run.dismissed_at,
    )
    commits = V2RunCommitsPayload(run.source_run_id, run.commits)
    run_metadata_from_json(meta.to_json_dict())
    run_state_from_json(state.to_json_dict())
    run_commits_from_json(commits.to_json_dict())
    files: list[tuple[str, V2FileReference]] = []
    for kind, name, content in (
        ("meta", "meta.json", v2_json_bytes(meta.to_json_dict())),
        ("state", "state.json", v2_json_bytes(state.to_json_dict())),
        ("commits", "commits.json", v2_json_bytes(commits.to_json_dict())),
        ("prompt", "prompt.md", run.prompt_bytes),
        ("chat", "chat.md", run.chat_bytes),
        (
            "embedded_workflows",
            "embedded_workflows.json",
            run.embedded_workflows_bytes,
        ),
        ("prompt_steps", "prompt_steps.json", run.prompt_steps_bytes),
    ):
        if content is None:
            continue
        path = f"{root}/{name}"
        payload[path] = content
        files.append((kind, file_reference(path, content)))
    capabilities = capabilities_from_v2_run(
        dict(run.metadata), {kind for kind, _ in files}
    )
    return V2RunRecord(
        source_run_id=run.source_run_id,
        local_name=run.local_name,
        global_name=run.global_name,
        state=cast(RunState, run.state),
        started_at=run.started_at,
        finished_at=run.finished_at,
        dismissed_at=run.dismissed_at,
        metadata=run.metadata,
        commits=run.commits,
        files=tuple(files),
        capabilities=capabilities,
    )


def _build_containers(
    runs: tuple[V2RunRecord, ...],
    owner: AgentOwnerIdentity,
    lane_commits: tuple[InventoryLaneCommitHistory, ...] = (),
    previous: tuple[V2ContainerRecord, ...] = (),
) -> tuple[V2ContainerRecord, ...]:
    families: dict[str, set[str]] = {}
    clans: dict[str, set[str]] = {}
    family_commits: dict[str, dict[str, CommitRecord]] = {}
    for run in runs:
        metadata = dict(run.metadata)
        parsed = parse_agent_family_name(run.local_name)
        family = (
            parsed.family_name
            if parsed.kind is AgentFamilyNameKind.MEMBER
            else _text(metadata.get("agent_family"))
        )
        if family:
            families.setdefault(family, set()).add(run.source_run_id)
        clan = _text(metadata.get("agent_clan"))
        if clan:
            clans.setdefault(clan, set()).add(run.source_run_id)
    for history in lane_commits:
        if history.local_name not in families:
            # Containers require at least one member; retain but do not fabricate
            # a run merely to carry family-lane history.
            continue
        families.setdefault(history.local_name, set())
        commits = family_commits.setdefault(history.local_name, {})
        commits.update({commit.sha: commit for commit in history.commits})
    containers = [
        V2ContainerRecord(
            cast(ContainerKind, kind),
            globalize_agent_name(name, owner),
            tuple(sorted(members)),
            (
                tuple(
                    sorted(
                        family_commits.get(name, {}).values(),
                        key=lambda item: (item.committed_at, item.sha),
                    )
                )
                if kind == "family"
                else ()
            ),
        )
        for kind, groups in (("family", families), ("clan", clans))
        for name, members in sorted(groups.items())
    ]
    by_key = {(item.kind, item.global_name): item for item in containers}
    for item in previous:
        key = (item.kind, item.global_name)
        current = by_key.get(key)
        if current is None:
            by_key[key] = item
            continue
        commits = {commit.sha: commit for commit in (*item.commits, *current.commits)}
        by_key[key] = replace(
            current,
            commits=tuple(
                sorted(commits.values(), key=lambda row: (row.committed_at, row.sha))
            ),
        )
    return tuple(
        sorted(by_key.values(), key=lambda item: (item.kind, item.global_name))
    )


def _build_relationships(
    current: tuple[InventoryRun, ...],
    combined: tuple[V2RunRecord, ...],
    inventory: ProjectHoodInventory,
    owner: AgentOwnerIdentity,
    previous: V2HoodSnapshot | None,
    current_ids: set[str],
) -> tuple[V2RelationshipRecord, ...]:
    by_local = {run.local_name: run for run in inventory.runs}
    by_timestamp = {run.timestamp: run for run in inventory.runs}
    inside_ids = {run.source_run_id for run in combined}
    rows: list[V2RelationshipRecord] = []
    one_to_one: set[tuple[str, str]] = set()
    for run in current:
        for relation in run.relationships:
            key = (relation.kind, run.source_run_id)
            if relation.kind != "wait" and key in one_to_one:
                continue
            target_run = (
                by_local.get(relation.target)
                if relation.target_kind == "name"
                else by_timestamp.get(relation.target)
            )
            if target_run is None or target_run.source_run_id == run.source_run_id:
                continue
            if target_run.source_run_id in inside_ids:
                target = V2RelationshipTarget(
                    "source_run_id", source_run_id=target_run.source_run_id
                )
                required = True
            else:
                target = V2RelationshipTarget(
                    "global_name",
                    global_name=target_run.global_name,
                    owner=owner,
                )
                required = False
            rows.append(
                V2RelationshipRecord(
                    cast(RelationshipKind, relation.kind),
                    run.source_run_id,
                    target,
                    required,
                )
            )
            one_to_one.add(key)
    if previous is not None:
        rows.extend(
            relation
            for relation in previous.relationships
            if relation.source_run_id not in current_ids
            and relation.source_run_id in inside_ids
            and _target_is_retained(relation, inside_ids)
        )
    unique = {
        (
            item.kind,
            item.source_run_id,
            item.target.kind,
            item.target.source_run_id,
            item.target.global_name,
        ): item
        for item in rows
    }
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.kind,
                item.source_run_id,
                item.target.kind,
                item.target.source_run_id or item.target.global_name or "",
            ),
        )
    )


def _target_is_retained(relation: V2RelationshipRecord, inside_ids: set[str]) -> bool:
    return (
        relation.target.kind == "global_name"
        or relation.target.source_run_id in inside_ids
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
