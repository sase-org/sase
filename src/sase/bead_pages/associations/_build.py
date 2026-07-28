"""Build the reusable, rendering-ready bead association index."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from sase.agents_sync.git import GitRunner, run_git
from sase.bead.model import Issue
from sase.bead.store_locator import open_bead_project_for_beads_dir
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.sdd.hosted_links import hosted_link_resolver
from sase.sdd.store import SddStore

from ._artifacts import artifact_associations, load_artifact_records
from ._history import HistoricalBeadCommit, read_history_associations
from ._lineage import association_source_beads
from .models import (
    BeadAgentAssociation,
    BeadAssociationIndex,
    BeadAssociations,
    BeadCommitAssociation,
)


class _LinkResolver(Protocol):
    def agent_url(self, agent_name: str) -> str | None: ...

    def commit_url(self, sha: str) -> str | None: ...


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

    primary = Path(primary_root or Path.cwd()).resolve(strict=False)
    snapshot = identity or AgentIdentitySnapshot.current()
    selected_project = project or _current_project()
    diagnostics: list[str] = []
    issues = _read_issues(store, bead_issues, diagnostics)
    known_bead_ids = frozenset(issue.id for issue in issues)
    history = read_history_associations(
        primary,
        known_bead_ids,
        snapshot,
        git_runner,
    )
    diagnostics.extend(history.diagnostics)
    direct_agents = {key: set(values) for key, values in history.agents.items()}

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
        ).items():
            direct_agents.setdefault(bead_id, set()).update(names)
    except Exception as exc:  # noqa: BLE001 - best-effort artifact projection.
        diagnostics.append(f"could not read agent artifacts: {exc}")

    resolver = link_resolver or hosted_link_resolver(
        store,
        project=selected_project,
        primary_root=primary,
    )
    source_beads = association_source_beads(issues)
    by_bead = {
        bead_id: _rendering_records(
            source_beads[bead_id],
            direct_agents,
            history.agent_commits,
            history.commits,
            resolver,
        )
        for bead_id in sorted(source_beads)
    }
    return BeadAssociationIndex(
        MappingProxyType(by_bead),
        tuple(diagnostics),
    )


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
    agents: Mapping[str, set[str]],
    agent_commits: Mapping[str, Mapping[str, set[str]]],
    commits: Mapping[str, Mapping[str, HistoricalBeadCommit]],
    resolver: _LinkResolver,
) -> BeadAssociations:
    agent_rows = tuple(
        BeadAgentAssociation(
            label=name,
            target=resolver.agent_url(name),
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
            label=commit.sha[:7],
            target=resolver.commit_url(commit.sha),
            bead_id=bead_id,
            subject=commit.subject,
            committed_at=commit.committed_at,
            sort_key=(commit.committed_at, commit.sha),
            sha=commit.sha,
        )
        for commit, bead_id in sorted(
            (
                (commit, bead_id)
                for bead_id in source_beads
                for commit in commits.get(bead_id, {}).values()
            ),
            key=lambda item: (item[0].committed_at, item[0].sha),
        )
    )
    return BeadAssociations(agent_rows, commit_rows)


def _current_project() -> str | None:
    try:
        from sase.workflows.utils import get_project_from_workspace

        return get_project_from_workspace()
    except Exception:
        return None


__all__ = ["build_bead_association_index"]
