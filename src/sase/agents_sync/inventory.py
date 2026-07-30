"""Indexed, project-scoped inventory for owner-sharded v2 publication."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.inventory_history import (
    HistoricalAssociations,
    historical_associations,
    primary_remote_url,
)
from sase.agents_sync.inventory_io import (
    source_run_id as _source_run_id,
    time_text as _time_text,
)
from sase.agents_sync.inventory_models import (
    InventoryLaneCommitHistory,
    InventoryRelationship,
    InventoryRun,
    ProjectHoodInventory,
)
from sase.agents_sync.inventory_sources import (
    artifact_relationships,
    dismissed_records,
    dismissed_relationships,
    indexed_records,
    run_from_artifact,
    run_from_dismissed,
)
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    globalize_agent_name,
    parse_agent_family_name,
)

# Preserve existing private test/support imports and monkeypatch points while
# keeping each implementation in its focused module.
_HistoricalAssociations = HistoricalAssociations
_InventoryRelationship = InventoryRelationship
_artifact_relationships = artifact_relationships
_dismissed_records = dismissed_records
_dismissed_relationships = dismissed_relationships
_historical_associations = historical_associations
_indexed_records = indexed_records
_primary_remote_url = primary_remote_url
_run_from_artifact = run_from_artifact
_run_from_dismissed = run_from_dismissed


def build_project_hood_inventory(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    *,
    git_runner: GitRunner = run_git,
) -> ProjectHoodInventory:
    """Load all locally owned process records selected by persistent indexes."""

    if identity.owner is None:
        raise AgentsSyncFormatError("v2 publication requires an owner identity")
    owner = identity.owner
    history = _historical_associations(target, identity, git_runner)
    primary_remote_url = _primary_remote_url(target, git_runner)
    records, diagnostics = _indexed_records(target)
    runs: list[InventoryRun] = []
    root_cache: dict[str, Path | None] = {}
    for record in records:
        try:
            run = _run_from_artifact(
                target,
                record,
                identity,
                history,
                root_cache,
                git_runner,
            )
        except AgentsSyncFormatError as exc:
            diagnostics.append(f"{record.artifact_dir}: {exc}")
            continue
        if run is not None:
            runs.append(run)

    for raw, source_label in _dismissed_records(target):
        try:
            run = _run_from_dismissed(
                raw,
                source_label,
                target.project_key,
                identity,
                history,
            )
        except AgentsSyncFormatError as exc:
            diagnostics.append(f"{source_label}: {exc}")
            continue
        if run is not None:
            runs.append(run)

    # A canonical global name identifies one durable run. Prefer live/indexed
    # state over its dismissed archive copy, then the most informative/newest
    # record, while unioning commit associations.
    by_global: dict[str, InventoryRun] = {}
    for run in sorted(runs, key=_run_preference):
        existing = by_global.get(run.global_name)
        if existing is None:
            by_global[run.global_name] = run
            continue
        commits = {commit.sha: commit for commit in (*existing.commits, *run.commits)}
        preferred = run
        by_global[run.global_name] = replace(
            preferred,
            commits=tuple(
                sorted(commits.values(), key=lambda item: (item.committed_at, item.sha))
            ),
            prompt_bytes=preferred.prompt_bytes or existing.prompt_bytes,
            chat_bytes=preferred.chat_bytes or existing.chat_bytes,
            embedded_workflows_bytes=(
                preferred.embedded_workflows_bytes or existing.embedded_workflows_bytes
            ),
            prompt_steps_bytes=(
                preferred.prompt_steps_bytes or existing.prompt_steps_bytes
            ),
        )
    _add_commit_only_runs(
        by_global,
        history.run_commits,
        target.project_key,
        owner,
        diagnostics,
    )
    normalized_runs = tuple(
        _normalize_historical_family_metadata(run, diagnostics)
        for run in by_global.values()
    )
    unique_runs = _disambiguate_source_run_ids(
        normalized_runs,
        target.project_key,
        diagnostics,
    )
    _diagnose_unrepresented_family_history(
        unique_runs,
        history.lane_commits,
        owner,
        diagnostics,
    )
    return ProjectHoodInventory(
        owner=owner,
        project_key=target.project_key,
        runs=tuple(sorted(unique_runs, key=lambda item: item.source_run_id)),
        diagnostics=tuple(diagnostics),
        primary_remote_url=primary_remote_url,
        primary_repo_name=target.primary_repo_name,
        lane_commits=history.lane_commits,
    )


def _run_preference(run: InventoryRun) -> tuple[int, int, str]:
    return (
        run.state != "dismissed",
        sum(
            (
                bool(run.commits),
                run.prompt_bytes is not None,
                run.chat_bytes is not None,
                run.finished_at is not None,
            )
        ),
        run.timestamp,
    )


def _add_commit_only_runs(
    by_global: dict[str, InventoryRun],
    history: dict[str, tuple[CommitRecord, ...]],
    project_key: str,
    owner: AgentOwnerIdentity,
    diagnostics: list[str],
) -> None:
    """Represent linked primary commits even after their local artifact is gone."""

    for local_name, commits in sorted(history.items()):
        global_name = globalize_agent_name(local_name, owner)
        if global_name in by_global:
            continue
        source_label = f"primary commit history for {global_name}"
        started_at = _time_text(commits[0].committed_at)
        finished_at = _time_text(commits[-1].committed_at)
        by_global[global_name] = InventoryRun(
            _source_run_id(project_key, "primary-commit-history", local_name),
            local_name,
            global_name,
            "completed",
            started_at,
            finished_at,
            None,
            (),
            commits,
            None,
            None,
            None,
            None,
            (),
            str(commits[-1].committed_at),
            source_label=source_label,
        )
        diagnostics.append(
            f"{source_label}: synthesized publication record because no local "
            "artifact remains"
        )


def _normalize_historical_family_metadata(
    run: InventoryRun,
    diagnostics: list[str],
) -> InventoryRun:
    """Make stale family metadata agree with canonical name classification."""

    try:
        parsed = parse_agent_family_name(run.local_name)
    except Exception as exc:  # noqa: BLE001 - defensive history boundary.
        source = run.source_label or run.source_run_id
        diagnostics.append(
            f"{source}: could not normalize historical family metadata: {exc}"
        )
        return run
    raw_family = run.family_name
    canonical_family = (
        parsed.family_name
        if parsed.member_role is not None
        else raw_family
        if raw_family == parsed.family_name
        else None
    )
    metadata = dict(run.metadata)
    if canonical_family is None:
        metadata.pop("agent_family", None)
        metadata.pop("agent_family_role", None)
        metadata.pop("role_suffix", None)
    else:
        metadata["agent_family"] = canonical_family
        if parsed.member_role is not None:
            metadata["agent_family_role"] = parsed.member_role
            metadata["role_suffix"] = parsed.member_role
    if raw_family is not None and raw_family != canonical_family:
        source = run.source_label or run.source_run_id
        diagnostics.append(
            f"{source}: historical agent_family {raw_family!r} disagrees with "
            f"canonical name {run.local_name!r}; using "
            f"{canonical_family or 'solo classification'!r}"
        )
    return replace(
        run,
        family_name=canonical_family,
        metadata=tuple(sorted(metadata.items())),
    )


def _diagnose_unrepresented_family_history(
    runs: tuple[InventoryRun, ...],
    lane_commits: tuple[InventoryLaneCommitHistory, ...],
    owner: AgentOwnerIdentity,
    diagnostics: list[str],
) -> None:
    member_families: set[str] = set()
    for run in runs:
        try:
            parsed = parse_agent_family_name(run.local_name)
        except Exception:
            continue
        if parsed.member_role is not None:
            member_families.add(parsed.family_name)
    for history in lane_commits:
        if (
            not history.is_family
            or not history.commits
            or history.local_name in member_families
        ):
            continue
        global_name = globalize_agent_name(history.local_name, owner)
        diagnostics.append(
            f"primary commit history for family lane {global_name}: retained "
            f"{len(history.commits)} commit(s), but no family member run remains "
            "and v2 family containers require at least one member"
        )


def _disambiguate_source_run_ids(
    runs: tuple[InventoryRun, ...],
    project_key: str,
    diagnostics: list[str],
) -> tuple[InventoryRun, ...]:
    """Give distinct historical runs unique stable IDs when old timestamps collide."""

    grouped: dict[str, list[InventoryRun]] = defaultdict(list)
    for run in runs:
        grouped[run.source_run_id].append(run)
    used = {
        source_run_id
        for source_run_id, candidates in grouped.items()
        if len(candidates) == 1
    }
    replacements: dict[str, str] = {}
    for source_run_id, candidates in sorted(grouped.items()):
        if len(candidates) == 1:
            continue
        labels = tuple(
            sorted(
                candidate.source_label or candidate.global_name
                for candidate in candidates
            )
        )
        diagnostics.append(
            f"historical source run ID {source_run_id!r} was shared by "
            f"{len(candidates)} records and was deterministically disambiguated: "
            + ", ".join(labels)
        )
        for candidate in sorted(candidates, key=lambda item: item.global_name):
            salt = 0
            while True:
                replacement = _source_run_id(
                    project_key,
                    "historical-source-collision",
                    f"{source_run_id}\0{candidate.global_name}\0{salt}",
                )
                if replacement not in used:
                    break
                salt += 1
            replacements[candidate.global_name] = replacement
            used.add(replacement)
    return tuple(
        replace(run, source_run_id=replacements[run.global_name])
        if run.global_name in replacements
        else run
        for run in runs
    )


__all__ = [
    "InventoryRun",
    "ProjectHoodInventory",
    "build_project_hood_inventory",
]
