"""Targeted and full v2 owner-sharded hood publication."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.inventory import (
    InventoryRun,
    ProjectHoodInventory,
    build_project_hood_inventory,
)
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.rendering import render_browsing_payload
from sase.agents_sync.v2_io import (
    apply_payload_atomic,
    content_digest,
    file_reference,
    owner_manifest_path,
    read_all_owner_manifests,
    read_hood_snapshot,
    read_owner_manifest,
    v2_json_bytes,
    v2_schema_document,
    validate_snapshot,
)
from sase.agents_sync.v2_run_io import (
    run_commits_from_json,
    run_metadata_from_json,
    run_state_from_json,
)
from sase.agents_sync.v2_models import (
    ContainerKind,
    RelationshipKind,
    RunState,
    V2ContainerRecord,
    V2FileReference,
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
    V2RelationshipRecord,
    V2RelationshipTarget,
    V2RunCommitsPayload,
    V2RunMetadataPayload,
    V2RunRecord,
    V2RunStatePayload,
)
from sase.core.agent_identity_facade import (
    AgentFamilyNameKind,
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    agent_local_hood,
    agent_name_ancestors,
    globalize_agent_name,
    normalize_agent_archive_name,
    normalize_owned_agent_name,
    parse_agent_family_name,
)


def publish_agent_hood(
    target: ProjectTarget,
    repo_root: Path,
    committing_agent: str,
    *,
    identity: AgentIdentitySnapshot | None = None,
    inventory: ProjectHoodInventory | None = None,
    git_runner: GitRunner = run_git,
) -> V2PublicationCounts:
    """Refresh exactly the committing agent's complete top-level local hood."""

    snapshot = identity or AgentIdentitySnapshot.current()
    owner = _owner(snapshot)
    local_name = normalize_agent_archive_name(
        normalize_owned_agent_name(committing_agent, snapshot)
    )
    project_inventory = inventory or build_project_hood_inventory(
        target, snapshot, git_runner=git_runner
    )
    if not any(run.local_name == local_name for run in project_inventory.runs):
        raise AgentsSyncFormatError(
            f"committing agent {committing_agent!r} is absent from project inventory"
        )
    hood = agent_local_hood(local_name)
    return _publish_hoods(
        target,
        repo_root,
        snapshot,
        project_inventory,
        (hood,),
        owner,
    )


def reconcile_agent_hoods(
    target: ProjectTarget,
    repo_root: Path,
    *,
    identity: AgentIdentitySnapshot | None = None,
    inventory: ProjectHoodInventory | None = None,
    git_runner: GitRunner = run_git,
) -> V2PublicationCounts:
    """Publish every locally owned hood with a primary-repository commit."""

    snapshot = identity or AgentIdentitySnapshot.current()
    owner = _owner(snapshot)
    project_inventory = inventory or build_project_hood_inventory(
        target, snapshot, git_runner=git_runner
    )
    return _publish_hoods(
        target,
        repo_root,
        snapshot,
        project_inventory,
        project_inventory.eligible_hoods(),
        owner,
    )


def _publish_hoods(
    target: ProjectTarget,
    repo_root: Path,
    identity: AgentIdentitySnapshot,
    inventory: ProjectHoodInventory,
    hoods: tuple[str, ...],
    owner: AgentOwnerIdentity,
) -> V2PublicationCounts:
    project = V2ProjectIdentity(target.project_key, target.project)
    previous_manifest = read_owner_manifest(repo_root, owner, project)
    entries = previous_manifest.by_hood()
    payload: dict[str, bytes] = {
        "schema.json": v2_json_bytes(v2_schema_document()),
        "agents/.gitkeep": b"",
        "families/.gitkeep": b"",
    }
    current_snapshots: dict[tuple[str, str, str], V2HoodSnapshot] = {}
    published = refreshed = unchanged = families = runs = 0

    for hood in sorted(set(hoods)):
        previous = _previous_snapshot(repo_root, owner, hood, entries.get(hood))
        hood_snapshot, hood_payload = _build_hood_snapshot(
            repo_root,
            project,
            owner,
            hood,
            inventory,
            previous,
        )
        snapshot_path = _snapshot_path(owner, hood)
        snapshot_bytes = v2_json_bytes(hood_snapshot.to_json_dict())
        hood_payload[snapshot_path] = snapshot_bytes
        files = _hood_file_set(hood_snapshot)
        entry = V2OwnerHoodEntry(
            content_digest(snapshot_bytes),
            files,
            len(hood_snapshot.runs),
            sum(item.kind == "family" for item in hood_snapshot.containers),
        )
        existing = entries.get(hood)
        if existing is None:
            published += 1
        elif existing.digest == entry.digest:
            unchanged += 1
        else:
            refreshed += 1
        if existing is None or existing.digest != entry.digest:
            families += entry.family_count
            runs += entry.run_count
        entries[hood] = entry
        payload.update(hood_payload)
        current_snapshots[(owner.username, owner.machine_name, hood)] = hood_snapshot

    manifest = V2OwnerManifest(owner, project, tuple(sorted(entries.items())))
    payload[owner_manifest_path(owner)] = v2_json_bytes(manifest.to_json_dict())
    manifests, snapshots = _load_validated_publication(
        repo_root,
        override_manifest=manifest,
        override_snapshots=current_snapshots,
        override_payload=payload,
    )
    payload.update(render_browsing_payload(manifests, snapshots))
    apply_payload_atomic(repo_root, payload)
    return V2PublicationCounts(
        hoods_published=published,
        hoods_refreshed=refreshed,
        hoods_unchanged=unchanged,
        families_published=families,
        runs_published=runs,
        diagnostics=inventory.diagnostics,
    )


def _build_hood_snapshot(
    repo_root: Path,
    project: V2ProjectIdentity,
    owner: AgentOwnerIdentity,
    hood: str,
    inventory: ProjectHoodInventory,
    previous: V2HoodSnapshot | None,
) -> tuple[V2HoodSnapshot, dict[str, bytes]]:
    current = inventory.hood_runs(hood)
    if not current and previous is None:
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
        _verify_run_files(repo_root, run)
    combined = tuple(
        sorted((*prior_records, *current_records), key=lambda item: item.source_run_id)
    )
    containers = _build_containers(combined, owner)
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
    )


def _build_containers(
    runs: tuple[V2RunRecord, ...],
    owner: AgentOwnerIdentity,
) -> tuple[V2ContainerRecord, ...]:
    families: dict[str, set[str]] = {}
    clans: dict[str, set[str]] = {}
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
    containers = [
        V2ContainerRecord(
            cast(ContainerKind, kind),
            globalize_agent_name(name, owner),
            tuple(sorted(members)),
        )
        for kind, groups in (("family", families), ("clan", clans))
        for name, members in sorted(groups.items())
    ]
    return tuple(sorted(containers, key=lambda item: (item.kind, item.global_name)))


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
            if target_run is None:
                continue
            if target_run.source_run_id == run.source_run_id:
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


def _previous_snapshot(
    repo_root: Path,
    owner: AgentOwnerIdentity,
    hood: str,
    entry: V2OwnerHoodEntry | None,
) -> V2HoodSnapshot | None:
    if entry is None:
        return None
    path = repo_root / _snapshot_path(owner, hood)
    payload = path.read_bytes()
    if content_digest(payload) != entry.digest:
        raise AgentsSyncFormatError(
            f"existing snapshot digest mismatch for hood {hood!r}"
        )
    snapshot = read_hood_snapshot(path)
    if snapshot.owner != owner or snapshot.local_hood != hood:
        raise AgentsSyncFormatError(
            f"existing snapshot identity mismatch for hood {hood!r}"
        )
    return snapshot


def _load_validated_publication(
    repo_root: Path,
    *,
    override_manifest: V2OwnerManifest | None = None,
    override_snapshots: dict[tuple[str, str, str], V2HoodSnapshot] | None = None,
    override_payload: dict[str, bytes] | None = None,
) -> tuple[
    tuple[V2OwnerManifest, ...],
    dict[tuple[str, str, str], V2HoodSnapshot],
]:
    manifests = {
        (item.owner.username, item.owner.machine_name): item
        for item in read_all_owner_manifests(repo_root)
    }
    if override_manifest is not None:
        manifests[
            (
                override_manifest.owner.username,
                override_manifest.owner.machine_name,
            )
        ] = override_manifest
    snapshots: dict[tuple[str, str, str], V2HoodSnapshot] = {}
    overrides = override_snapshots or {}
    payload = override_payload or {}
    for manifest in manifests.values():
        for hood, entry in manifest.hoods:
            key = (manifest.owner.username, manifest.owner.machine_name, hood)
            snapshot = overrides.get(key)
            path = _snapshot_path(manifest.owner, hood)
            raw = (
                v2_json_bytes(snapshot.to_json_dict())
                if snapshot is not None
                else _payload_bytes(repo_root, payload, path)
            )
            if content_digest(raw) != entry.digest:
                raise AgentsSyncFormatError(
                    f"snapshot digest mismatch for {'.'.join(key)!r}"
                )
            if snapshot is None:
                snapshot = read_hood_snapshot(repo_root / path)
            if (
                snapshot.owner != manifest.owner
                or snapshot.project != manifest.project
                or snapshot.local_hood != hood
            ):
                raise AgentsSyncFormatError(
                    f"snapshot identity mismatch for {'.'.join(key)!r}"
                )
            expected = _hood_file_set(snapshot)
            if expected != entry.files:
                raise AgentsSyncFormatError(
                    f"manifest file set mismatch for {'.'.join(key)!r}"
                )
            for run in snapshot.runs:
                _verify_run_files(repo_root, run, payload)
            snapshots[key] = snapshot
    return (
        tuple(
            sorted(
                manifests.values(),
                key=lambda item: (
                    item.owner.username,
                    item.owner.machine_name,
                ),
            )
        ),
        snapshots,
    )


def _verify_run_files(
    repo_root: Path,
    run: V2RunRecord,
    payload: dict[str, bytes] | None = None,
) -> None:
    for _kind, reference in run.files:
        content = _payload_bytes(repo_root, payload or {}, reference.path)
        if (
            len(content) != reference.size_bytes
            or content_digest(content) != reference.digest
        ):
            raise AgentsSyncFormatError(f"file digest mismatch for {reference.path!r}")


def _payload_bytes(repo_root: Path, payload: dict[str, bytes], path: str) -> bytes:
    if path in payload:
        return payload[path]
    try:
        return (repo_root / path).read_bytes()
    except OSError as exc:
        raise AgentsSyncFormatError(f"could not read referenced file {path!r}") from exc


def _hood_file_set(snapshot: V2HoodSnapshot) -> tuple[str, ...]:
    files = {
        _snapshot_path(snapshot.owner, snapshot.local_hood),
        _hood_readme_path(snapshot.owner, snapshot.local_hood),
    }
    for run in snapshot.runs:
        files.update(reference.path for _kind, reference in run.files)
        files.add(f"agents/{run.global_name}/README.md")
    files.update(
        f"families/{container.global_name}.md"
        for container in snapshot.containers
        if container.kind == "family"
    )
    return tuple(sorted(files))


def _snapshot_path(owner: AgentOwnerIdentity, hood: str) -> str:
    return (
        f"users/{owner.username}/machines/{owner.machine_name}/"
        f"hoods/{hood}/snapshot.json"
    )


def _hood_readme_path(owner: AgentOwnerIdentity, hood: str) -> str:
    return (
        f"users/{owner.username}/machines/{owner.machine_name}/hoods/{hood}/README.md"
    )


def _owner(identity: AgentIdentitySnapshot) -> AgentOwnerIdentity:
    if identity.owner is None:
        raise AgentsSyncFormatError("v2 publication requires an owner identity")
    return identity.owner


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


# Explicit aliases for callers that prefer the plan's terminology.
publish_targeted_hood = publish_agent_hood
reconcile_all_hoods = reconcile_agent_hoods


__all__ = [
    "publish_agent_hood",
    "publish_targeted_hood",
    "reconcile_agent_hoods",
    "reconcile_all_hoods",
]
