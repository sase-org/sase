"""Build the reusable, rendering-ready bead association index."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from sase.agents_sync.git import GitRunner, run_git
from sase.association_agents import (
    AgentAssociationRef,
    merge_agent_associations,
    resolve_agent_association_url,
    snapshot_agent_name_registry,
)
from sase.bead.model import Issue
from sase.bead.store_locator import open_bead_project_for_beads_dir
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.repo_inventory import collect_repo_inventory, repo_display_name
from sase.sdd.hosted_links import hosted_link_resolver
from sase.sdd.plan_refs import workspace_context_for_plan_resolution
from sase.sdd.store import SddStore

from ._artifacts import artifact_associations, load_artifact_records
from ._history import HistoricalBeadCommit, read_history_associations
from ._lineage import association_source_beads
from .models import (
    BeadAgentAssociation,
    BeadAssociationIndex,
    BeadAssociations,
    BeadCommitAssociation,
    BeadCommitRepository,
)


class _LinkResolver(Protocol):
    def agent_url(self, agent_name: str) -> str | None: ...

    def commit_url(self, sha: str) -> str | None: ...

    def commit_url_for_repository(
        self,
        repository_root: Path | str,
        sha: str,
    ) -> str | None: ...


def build_bead_association_index(
    store: SddStore,
    *,
    primary_root: Path | str | None = None,
    project: str | None = None,
    git_runner: GitRunner = run_git,
    link_resolver: _LinkResolver | None = None,
    artifact_records: Iterable[AgentArtifactRecordWire] | None = None,
    bead_issues: Iterable[Issue] | None = None,
    identity: AgentIdentitySnapshot | None = None,
) -> BeadAssociationIndex:
    """Derive every bead's agents and commits in one reusable pass."""

    from sase.sdd.checkout_anchor import resolve_checkout_anchor

    anchor = resolve_checkout_anchor(primary_root or Path.cwd())
    primary = anchor.primary_root
    snapshot = identity or AgentIdentitySnapshot.current()
    inventory_project = project or anchor.project_name
    selected_project = inventory_project or _current_project()
    diagnostics: list[str] = []
    issues = _read_issues(store, bead_issues, diagnostics)
    known_bead_ids = frozenset(issue.id for issue in issues)
    from sase.bead_pages.links import bead_id_aliases_for_store

    id_aliases = bead_id_aliases_for_store(store)
    repositories = _history_repositories(
        primary,
        inventory_project,
        diagnostics,
    )
    direct_agents: defaultdict[str, dict[str, AgentAssociationRef]] = defaultdict(dict)
    agent_commits: defaultdict[str, dict[str, set[tuple[str, str]]]] = defaultdict(dict)
    commits: defaultdict[str, dict[tuple[str, str], HistoricalBeadCommit]] = (
        defaultdict(dict)
    )
    for repository in repositories:
        history = read_history_associations(
            repository,
            known_bead_ids,
            snapshot,
            git_runner,
            id_aliases,
        )
        diagnostics.extend(history.diagnostics)
        _merge_history(
            history.agents,
            history.agent_commits,
            history.commits,
            direct_agents,
            agent_commits,
            commits,
        )

    try:
        records = (
            tuple(artifact_records)
            if artifact_records is not None
            else load_artifact_records(selected_project)
        )
        for bead_id, names in artifact_associations(
            records,
            known_bead_ids,
            snapshot,
            id_aliases,
        ).items():
            target = direct_agents[bead_id]
            for label, association in names.items():
                target[label] = merge_agent_associations(
                    target.get(label),
                    association,
                )
    except Exception as exc:  # noqa: BLE001 - best-effort artifact projection.
        diagnostics.append(f"could not read agent artifacts: {exc}")

    resolver = link_resolver or hosted_link_resolver(
        store,
        project=selected_project,
        primary_root=primary,
    )
    snapshot_agent_name_registry(resolver, diagnostics)
    source_beads = association_source_beads(issues)
    by_bead = {
        bead_id: _rendering_records(
            source_beads[bead_id],
            direct_agents,
            agent_commits,
            commits,
            resolver,
        )
        for bead_id in sorted(source_beads)
    }
    return BeadAssociationIndex(
        MappingProxyType(by_bead),
        tuple(diagnostics),
    )


def _history_repositories(
    primary_root: Path,
    project: str | None,
    diagnostics: list[str],
) -> tuple[BeadCommitRepository, ...]:
    """Return existing project-owned clones for this workspace."""

    fallback = BeadCommitRepository(
        primary_root.name,
        primary_root,
        "primary",
        True,
    )
    if not project:
        return (fallback,)

    try:
        inventory = collect_repo_inventory(project=project)
    except Exception as exc:  # noqa: BLE001 - best-effort inventory boundary.
        diagnostics.append(f"could not collect repository inventory: {exc}")
        return (fallback,)

    diagnostics.extend(
        f"repository inventory for {issue.project}: {issue.message}"
        for issue in inventory.issues
    )
    try:
        _workspace_root, workspace_num = workspace_context_for_plan_resolution(
            primary_root
        )
    except Exception:
        workspace_num = 1

    primary_record = next(
        (record for record in inventory.records if record.kind == "primary"),
        None,
    )
    primary_name = (
        repo_display_name(primary_record)
        if primary_record is not None
        else fallback.name
    )
    repositories = [BeadCommitRepository(primary_name, primary_root, "primary", True)]
    seen = {primary_root.resolve(strict=False)}
    for record in inventory.records:
        if record.kind not in {"sidecar", "linked"}:
            continue
        clone = record.clone_for_workspace(workspace_num)
        raw_path = clone.path if clone is not None else record.path
        if not raw_path:
            continue
        root = Path(raw_path).expanduser().resolve(strict=False)
        if root in seen:
            continue
        expected_to_exist = clone.exists if clone is not None else record.exists
        if not root.is_dir():
            if expected_to_exist:
                diagnostics.append(
                    f"repository clone for {repo_display_name(record)} "
                    f"is missing: {root}"
                )
            continue
        seen.add(root)
        repositories.append(
            BeadCommitRepository(
                repo_display_name(record),
                root,
                record.kind,
                False,
            )
        )
    return tuple(repositories)


def _merge_history(
    agents: Mapping[str, Mapping[str, AgentAssociationRef]],
    source_agent_commits: Mapping[str, Mapping[str, set[tuple[str, str]]]],
    source_commits: Mapping[str, Mapping[tuple[str, str], HistoricalBeadCommit]],
    target_agents: defaultdict[str, dict[str, AgentAssociationRef]],
    target_agent_commits: defaultdict[str, dict[str, set[tuple[str, str]]]],
    target_commits: defaultdict[str, dict[tuple[str, str], HistoricalBeadCommit]],
) -> None:
    for bead_id, associations in agents.items():
        target = target_agents[bead_id]
        for label, association in associations.items():
            target[label] = merge_agent_associations(
                target.get(label),
                association,
            )
    for bead_id, by_agent in source_agent_commits.items():
        target_commits_by_agent = target_agent_commits[bead_id]
        for agent_name, commit_keys in by_agent.items():
            target_commits_by_agent.setdefault(agent_name, set()).update(commit_keys)
    for bead_id, by_commit in source_commits.items():
        target_commits[bead_id].update(by_commit)


def _read_issues(
    store: SddStore,
    supplied: Iterable[Issue] | None,
    diagnostics: list[str],
) -> tuple[Issue, ...]:
    if supplied is not None:
        return tuple(supplied)
    beads_dir = store.kind_root("beads")
    try:
        with open_bead_project_for_beads_dir(beads_dir) as bead_project:
            return tuple(bead_project.list_issues())
    except Exception as exc:  # noqa: BLE001 - best-effort bead projection.
        diagnostics.append(f"could not read bead store: {exc}")
        return ()


def _rendering_records(
    source_beads: tuple[str, ...],
    agents: Mapping[str, Mapping[str, AgentAssociationRef]],
    agent_commits: Mapping[str, Mapping[str, set[tuple[str, str]]]],
    commits: Mapping[str, Mapping[tuple[str, str], HistoricalBeadCommit]],
    resolver: _LinkResolver,
) -> BeadAssociations:
    agent_rows = tuple(
        BeadAgentAssociation(
            label=name,
            target=resolve_agent_association_url(agents[bead_id][name], resolver),
            bead_id=bead_id,
            commit_count=len(agent_commits.get(bead_id, {}).get(name, ())),
            sort_key=(name, bead_id),
        )
        for name, bead_id in sorted(
            (name, bead_id)
            for bead_id in source_beads
            for name in agents.get(bead_id, ())
        )
    )
    commit_rows = tuple(
        BeadCommitAssociation(
            label=_commit_label(commit),
            target=_commit_url(resolver, commit),
            bead_id=bead_id,
            subject=commit.subject,
            committed_at=commit.committed_at,
            sort_key=(
                commit.committed_at,
                commit.repository.name,
                commit.sha,
            ),
            sha=commit.sha,
            repository=commit.repository,
        )
        for commit, bead_id in sorted(
            (
                (commit, bead_id)
                for bead_id in source_beads
                for commit in commits.get(bead_id, {}).values()
            ),
            key=lambda item: (
                item[0].committed_at,
                item[0].repository.name,
                item[0].sha,
            ),
        )
    )
    return BeadAssociations(agent_rows, commit_rows)


def _commit_label(commit: HistoricalBeadCommit) -> str:
    short_sha = commit.sha[:7]
    if commit.repository.is_primary:
        return short_sha
    return f"{commit.repository.name}@{short_sha}"


def _commit_url(
    resolver: _LinkResolver,
    commit: HistoricalBeadCommit,
) -> str | None:
    per_repository = getattr(resolver, "commit_url_for_repository", None)
    if callable(per_repository):
        return per_repository(commit.repository.root, commit.sha)
    if commit.repository.is_primary:
        return resolver.commit_url(commit.sha)
    return None


def _current_project() -> str | None:
    try:
        from sase.workflows.utils import get_project_from_workspace

        return get_project_from_workspace()
    except Exception:
        return None


__all__ = ["build_bead_association_index"]
