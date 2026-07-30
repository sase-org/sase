"""Build the reusable, rendering-ready plan association index."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from sase.agents_sync.git import GitRunner, run_git
from sase.association_agents import (
    AgentAssociationRef,
    merge_agent_associations,
    resolve_agent_association_url,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.sdd.hosted_links import HostedLinkResolver, hosted_link_resolver
from sase.sdd.store import SddStore

from ._artifacts import artifact_associations, load_artifact_records
from ._history import HistoricalCommit, read_history_associations
from ._normalization import PlanReferenceNormalizer
from ._plans import roll_up_epics, scan_plan_tree
from .models import (
    PlanAgentAssociation,
    PlanAssociationIndex,
    PlanAssociations,
    PlanCommitAssociation,
)


class _LinkResolver(Protocol):
    def agent_url(self, agent_name: str) -> str | None: ...

    def commit_url(self, sha: str) -> str | None: ...


def build_plan_association_index(
    store: SddStore,
    *,
    primary_root: Path | str | None = None,
    project: str | None = None,
    git_runner: GitRunner = run_git,
    link_resolver: _LinkResolver | None = None,
    artifact_records: Iterable[AgentArtifactRecordWire] | None = None,
    identity: AgentIdentitySnapshot | None = None,
) -> PlanAssociationIndex:
    """Derive all plan agents and commits in one reusable pass."""

    primary = Path(primary_root or Path.cwd()).resolve(strict=False)
    normalizer = PlanReferenceNormalizer(store, primary)
    snapshot = identity or AgentIdentitySnapshot.current()
    selected_project = project or _current_project()
    history = read_history_associations(primary, normalizer, snapshot, git_runner)
    agents = {key: dict(values) for key, values in history.agents.items()}
    commits = {key: dict(values) for key, values in history.commits.items()}
    diagnostics = list(history.diagnostics)

    try:
        records = (
            tuple(artifact_records)
            if artifact_records is not None
            else load_artifact_records(selected_project)
        )
        for plan_ref, names in artifact_associations(
            records,
            normalizer,
            snapshot,
        ).items():
            target = agents.setdefault(plan_ref, {})
            for label, association in names.items():
                target[label] = merge_agent_associations(
                    target.get(label),
                    association,
                )
    except Exception as exc:  # noqa: BLE001 - best-effort artifact projection.
        diagnostics.append(f"could not read agent artifacts: {exc}")

    nodes = scan_plan_tree(normalizer)
    roll_up_epics(agents, commits, nodes)
    resolver = link_resolver or hosted_link_resolver(
        store,
        project=selected_project,
        primary_root=primary,
    )
    keys = set(nodes) | set(agents) | set(commits)
    by_plan = {
        plan_ref: _rendering_records(
            agents.get(plan_ref, {}),
            commits.get(plan_ref, {}),
            resolver,
        )
        for plan_ref in sorted(keys)
    }
    return PlanAssociationIndex(
        MappingProxyType(by_plan),
        tuple(diagnostics),
    )


def _rendering_records(
    agents: Mapping[str, AgentAssociationRef],
    commits: Mapping[str, HistoricalCommit],
    resolver: _LinkResolver,
) -> PlanAssociations:
    agent_rows = tuple(
        PlanAgentAssociation(
            label=name,
            target=resolve_agent_association_url(agents[name], resolver),
            sort_key=name,
        )
        for name in sorted(agents)
    )
    commit_rows = tuple(
        PlanCommitAssociation(
            label=commit.sha[:7],
            target=resolver.commit_url(commit.sha),
            trailing_text=commit.subject,
            sort_key=(commit.committed_at, commit.sha),
            sha=commit.sha,
        )
        for commit in sorted(
            commits.values(),
            key=lambda item: (item.committed_at, item.sha),
        )
    )
    return PlanAssociations(agent_rows, commit_rows)


def _current_project() -> str | None:
    try:
        from sase.workflows.utils import get_project_from_workspace

        return get_project_from_workspace()
    except Exception:
        return None


__all__ = ["HostedLinkResolver", "build_plan_association_index"]
