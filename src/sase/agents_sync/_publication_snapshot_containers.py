"""Container and relationship assembly for hood snapshots."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from sase.plan_chain import agent_session_value
from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.inventory_models import InventoryLaneCommitHistory
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.v2_models import (
    ContainerKind,
    RelationshipKind,
    V2ContainerRecord,
    V2HoodSnapshot,
    V2RelationshipRecord,
    V2RelationshipTarget,
    V2RunRecord,
    canonical_container_kind,
)
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    AgentSessionNameKind,
    agent_name_ancestors,
    globalize_agent_name,
    parse_agent_session_name,
)


def build_containers(
    runs: tuple[V2RunRecord, ...],
    owner: AgentOwnerIdentity,
    lane_commits: tuple[InventoryLaneCommitHistory, ...] = (),
    previous: tuple[V2ContainerRecord, ...] = (),
) -> tuple[V2ContainerRecord, ...]:
    agent_sessions: dict[str, set[str]] = {}
    clans: dict[str, set[str]] = {}
    agent_session_commits: dict[str, dict[str, CommitRecord]] = {}
    for run in runs:
        metadata = dict(run.metadata)
        parsed = parse_agent_session_name(run.local_name)
        agent_session = (
            parsed.agent_session_name
            if parsed.kind is AgentSessionNameKind.MEMBER
            else _text(agent_session_value(metadata))
        )
        if agent_session:
            agent_sessions.setdefault(agent_session, set()).add(run.source_run_id)
        clan = _text(metadata.get("agent_clan"))
        if clan:
            clans.setdefault(clan, set()).add(run.source_run_id)
    for history in lane_commits:
        if history.local_name not in agent_sessions:
            # Containers require at least one member; retain but do not fabricate
            # a run merely to carry session-lane history.
            continue
        agent_sessions.setdefault(history.local_name, set())
        commits = agent_session_commits.setdefault(history.local_name, {})
        commits.update({commit.sha: commit for commit in history.commits})
    containers = [
        V2ContainerRecord(
            cast(ContainerKind, kind),
            globalize_agent_name(name, owner),
            tuple(sorted(members)),
            (
                tuple(
                    sorted(
                        agent_session_commits.get(name, {}).values(),
                        key=lambda item: (item.committed_at, item.sha),
                    )
                )
                if kind == "session"
                else ()
            ),
        )
        for kind, groups in (("session", agent_sessions), ("clan", clans))
        for name, members in sorted(groups.items())
    ]
    by_key = {
        (canonical_container_kind(item.kind), item.global_name): item
        for item in containers
    }
    member_ids = {run.source_run_id for run in runs}
    for item in previous:
        if any(member not in member_ids for member in item.member_source_run_ids):
            # A withheld run left this retained container pointing at absent
            # members; session pages render every member, so the stale
            # container is dropped instead of rendering broken member links.
            continue
        key = (canonical_container_kind(item.kind), item.global_name)
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


def build_relationships(
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
