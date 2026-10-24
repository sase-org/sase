"""Read-only classification for stale publication revision repair."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import subprocess

from sase.agents_sync.inventory import build_project_hood_inventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    PUBLICATION_SCOPE_LINKED,
    PUBLICATION_SCOPE_REVISION,
    AgentPublicationOutboxItem,
    list_agent_publications,
)
from sase.agents_sync._publication_revision_repair_models import (
    StaleRevisionRepairReport,
    StaleRevisionRowReport,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_publication_recovery import (
    STALE_REPAIR_ACTION_LINKED,
    STALE_REPAIR_ACTION_REPAIRED,
    StalePublicationRepair,
    classify_stale_publication_request,
)
from sase.core.rust import require_rust_binding
from sase.repo_inventory import collect_repo_inventory
from sase.sase_agent import sase_agent_ref_for_turn
from sase.agents_sync.git import GitRunner

_MERGE_BASE_OP = "agents_sync.revision_repair.merge_base"
_CAT_FILE_OP = "agents_sync.revision_repair.cat_file"


def classify_project_revisions(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    git_runner: GitRunner,
) -> StaleRevisionRepairReport:
    """Classify every queued row without writing anything."""

    items = list_agent_publications(target.project_key)
    if not items:
        return StaleRevisionRepairReport(
            target.project_key, target.project, False, (), 0
        )
    identity = AgentIdentitySnapshot(owner)
    inventory = build_project_hood_inventory(
        target,
        identity,
        git_runner=git_runner,
        requested_hoods=frozenset(item.local_hood for item in items),
    )
    commits = _run_commits_by_agent(inventory.runs, identity)
    git_facts = _GitFacts(target, git_runner=git_runner)
    rows = tuple(_classify_row(item, commits, git_facts) for item in items)
    return StaleRevisionRepairReport(
        target.project_key,
        target.project,
        False,
        rows,
        sum(1 for row in rows if _row_changes_outbox(row, items)),
    )


def _row_changes_outbox(
    row: StaleRevisionRowReport,
    items: tuple[AgentPublicationOutboxItem, ...],
) -> bool:
    """Return whether applying *row* rewrites the outbox on current state."""

    if not row.changed:
        return False
    current = next(
        (
            item
            for item in items
            if (item.global_agent, item.original_revision)
            == (row.global_agent, row.requested_revision)
        ),
        None,
    )
    if current is None:
        return False
    if row.action == STALE_REPAIR_ACTION_REPAIRED:
        return (
            current.primary_revision != row.fulfilling_revision
            or current.scope != PUBLICATION_SCOPE_REVISION
        )
    return current.scope != PUBLICATION_SCOPE_LINKED


def _run_commits_by_agent(
    runs: Sequence[object],
    identity: AgentIdentitySnapshot,
) -> dict[tuple[str, str], list[str]]:
    """Index recorded primary commit SHAs by agent identity, earliest first."""

    commits: dict[tuple[str, str], list[str]] = {}
    for run in runs:
        local_name = getattr(run, "local_name", None)
        global_name = getattr(run, "global_name", None)
        if not isinstance(local_name, str) or not isinstance(global_name, str):
            continue
        projected = sase_agent_ref_for_turn(local_name, identity).local_name
        shas: list[str] = []
        for commit in getattr(run, "commits", ()):
            sha = getattr(commit, "sha", None)
            if isinstance(sha, str) and sha:
                shas.append(sha)
        if not shas:
            continue
        for key in {(projected, global_name), (local_name, global_name)}:
            commits.setdefault(key, []).extend(shas)
    return commits


def _row_commit_shas(
    item: AgentPublicationOutboxItem,
    commits: Mapping[tuple[str, str], list[str]],
) -> list[str]:
    """Return the recorded run commits for one row's agent, earliest first."""

    shas: list[str] = []
    for key in (
        (item.local_agent, item.global_agent),
        (item.global_agent, item.global_agent),
    ):
        shas.extend(commits.get(key, ()))
    return list(dict.fromkeys(shas))


def _commit_shas_equivalent(left: str, right: str) -> bool:
    """Return whether two SHAs identify the same commit via the Rust core."""

    binding = require_rust_binding("commit_shas_equivalent")
    return bool(binding(left, right))


class _GitFacts:
    """Cached read-only revision facts from the primary and linked checkouts."""

    def __init__(
        self,
        target: ProjectTarget,
        *,
        git_runner: GitRunner,
        linked_dirs: tuple[Path, ...] | None = None,
    ) -> None:
        self._target = target
        self._git_runner = git_runner
        self._primary_objects: dict[str, bool] = {}
        self._ancestors: dict[tuple[str, str], bool] = {}
        self._linked_objects: dict[str, bool] = {}
        self._linked_dirs = linked_dirs

    def object_in_primary(self, revision: str) -> bool:
        """Return whether *revision* resolves in the primary checkout."""

        if revision not in self._primary_objects:
            self._primary_objects[revision] = (
                self._run_primary("cat-file", "-e", revision).returncode == 0
            )
        return self._primary_objects[revision]

    def is_primary_ancestor(self, revision: str, candidate: str) -> bool:
        """Return whether *revision* is an ancestor of *candidate*."""

        key = (revision, candidate)
        if key not in self._ancestors:
            if _commit_shas_equivalent(revision, candidate):
                self._ancestors[key] = True
            elif not self.object_in_primary(revision):
                self._ancestors[key] = False
            else:
                self._ancestors[key] = (
                    self._run_primary(
                        "merge-base", "--is-ancestor", revision, candidate
                    ).returncode
                    == 0
                )
        return self._ancestors[key]

    def object_in_linked(self, revision: str) -> bool:
        """Return whether *revision* resolves in a linked checkout."""

        if revision not in self._linked_objects:
            found = False
            for clone_dir in self._linked_dirs_for_target():
                result = self._git_runner(
                    clone_dir,
                    ["cat-file", "-e", revision],
                    network=False,
                    op=_CAT_FILE_OP,
                )
                if result.returncode == 0:
                    found = True
                    break
            self._linked_objects[revision] = found
        return self._linked_objects[revision]

    def _linked_dirs_for_target(self) -> tuple[Path, ...]:
        if self._linked_dirs is None:
            dirs: list[Path] = []
            try:
                inventory = collect_repo_inventory()
            except Exception:  # noqa: BLE001 - inventory failure degrades facts
                inventory = None
            if inventory is not None:
                for record in inventory.records:
                    if (
                        record.kind != "linked"
                        or record.project_key != self._target.project_key
                    ):
                        continue
                    for raw in (record.path, *(clone.path for clone in record.clones)):
                        if not raw:
                            continue
                        candidate = Path(raw).expanduser()
                        if candidate.is_dir():
                            dirs.append(candidate)
            self._linked_dirs = tuple(dict.fromkeys(dirs))
        return self._linked_dirs

    def _run_primary(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run one read-only git command in the primary checkout."""

        return self._git_runner(
            self._target.primary_checkout,
            list(args),
            network=False,
            op=_MERGE_BASE_OP,
        )


def _classify_row(
    item: AgentPublicationOutboxItem,
    commits: Mapping[tuple[str, str], list[str]],
    git_facts: _GitFacts,
) -> StaleRevisionRowReport:
    """Classify one outbox row through the Rust core decision."""

    requested = item.original_revision
    run_shas = _row_commit_shas(item, commits)
    ancestors = [
        sha for sha in run_shas if git_facts.is_primary_ancestor(requested, sha)
    ]
    decision: StalePublicationRepair = classify_stale_publication_request(
        requested_revision=requested,
        scope=item.scope,
        run_commit_shas=run_shas,
        ancestor_commit_shas=ancestors,
        linked_revision=git_facts.object_in_linked(requested),
    )
    fulfilling = decision.fulfilling_revision
    new_scope = (
        PUBLICATION_SCOPE_LINKED
        if decision.action == STALE_REPAIR_ACTION_LINKED
        else None
    )
    return StaleRevisionRowReport(
        global_agent=item.global_agent,
        local_agent=item.local_agent,
        requested_revision=requested,
        current_revision=item.primary_revision,
        current_scope=item.scope,
        action=decision.action,
        fulfilling_revision=fulfilling,
        new_scope=new_scope,
        evidence_commit=decision.evidence_commit,
        reason=decision.reason,
    )
