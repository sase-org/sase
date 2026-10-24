"""Report-first repair for stale publication-revision outbox rows.

Rows enqueued before the post-commit revision fix name a pre-commit primary
revision that no published run carries, so they never acknowledge and consume
every bounded retry. This repair maps each stale requested revision to the
agent's committed revision (or to linked scope) without dropping any request:

- ``unchanged``: the requested revision is already among the agent's run
  commits, or the row already carries linked scope.
- ``linked``: the requested revision is a linked-repo commit; the row takes
  linked scope and fulfills when the required page exists.
- ``repaired``: the earliest recorded run commit descending from the
  requested revision replaces the row's key. The original revision is
  preserved on the row and stays visible in doctor and JSON output.
- ``unresolved``: no evidence, so the row is kept exactly as it is.

Report mode (the default) writes nothing. Apply mode rewrites the outbox
through the outbox mutation APIs only, keeps lifecycle, attempts, and prior
errors, merges logical-key collisions deterministically, and appends every
applied change to an audit JSONL beside the outbox.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
import json
import subprocess
import time

from sase.agents_sync import _commit_publication_support as publication_support
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_sync import ensure_agents_clone
from sase.agents_sync.git_sync_ops import (
    agents_git_dir,
    bounded_agents_lock,
    configured_agents_lock_timeout,
)
from sase.agents_sync.inventory import build_project_hood_inventory
from sase.agents_sync.models import ProjectTarget, SyncOutcome
from sase.agents_sync.publication_outbox import (
    PUBLICATION_SCOPE_LINKED,
    PUBLICATION_SCOPE_REVISION,
    AgentPublicationOutboxItem,
    list_agent_publications,
)
from sase.agents_sync.publication_outbox_models import publication_sort_key
from sase.agents_sync.publication_outbox_operations import (
    mutate_publication_outbox,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
)
from sase.core.agent_publication_recovery import (
    STALE_REPAIR_ACTION_LINKED,
    STALE_REPAIR_ACTION_REPAIRED,
    STALE_REPAIR_ACTION_UNCHANGED,
    STALE_REPAIR_ACTION_UNRESOLVED,
    StalePublicationRepair,
    classify_stale_publication_request,
)
from sase.core.paths import sase_projects_dir
from sase.core.rust import require_rust_binding
from sase.repo_inventory import collect_repo_inventory
from sase.sase_agent import sase_agent_ref_for_turn

REPAIR_REVISIONS_COMMAND = "sase agent sync --repair-revisions"
REPAIR_REVISIONS_APPLY_COMMAND = "sase agent sync --repair-revisions --apply"
REPAIR_REVISIONS_AUDIT_FILENAME = "agents-publication-repair-audit.jsonl"

_MERGE_BASE_OP = "agents_sync.revision_repair.merge_base"
_CAT_FILE_OP = "agents_sync.revision_repair.cat_file"


@dataclass(frozen=True, slots=True)
class _StaleRevisionRowReport:
    """One row's repair classification for report and audit output."""

    global_agent: str
    local_agent: str
    requested_revision: str
    current_revision: str
    current_scope: str
    action: str
    fulfilling_revision: str | None = None
    new_scope: str | None = None
    evidence_commit: str | None = None
    reason: str = ""
    merged_from: tuple[tuple[str, str], ...] = ()

    @property
    def changed(self) -> bool:
        """Return whether applying this row rewrites the outbox."""

        return self.action in (
            STALE_REPAIR_ACTION_LINKED,
            STALE_REPAIR_ACTION_REPAIRED,
        )

    def diagnostic(self) -> str:
        """Render one stable report line for this row."""

        requested = _short(self.requested_revision)
        if self.action == STALE_REPAIR_ACTION_REPAIRED:
            return (
                f"{self.global_agent}@{requested}: repaired to "
                f"{_short(self.fulfilling_revision or '')} "
                f"({self.reason})"
            )
        if self.action == STALE_REPAIR_ACTION_LINKED:
            return (
                f"{self.global_agent}@{requested}: takes linked scope ({self.reason})"
            )
        if self.action == STALE_REPAIR_ACTION_UNRESOLVED:
            return (
                f"{self.global_agent}@{requested}: unresolved, kept as is "
                f"({self.reason})"
            )
        return f"{self.global_agent}@{requested}: unchanged ({self.reason})"


@dataclass(frozen=True, slots=True)
class _StaleRevisionRepairReport:
    """The complete repair outcome for one project."""

    project_key: str
    project: str
    applied: bool
    rows: tuple[_StaleRevisionRowReport, ...]
    changed: int
    audit_path: str | None = None

    def diagnostics(self) -> tuple[str, ...]:
        """Render the stable report lines for sync outcome output."""

        lines = [row.diagnostic() for row in self.rows]
        lines.append(self._summary())
        return tuple(lines)

    def _summary(self) -> str:
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.action] = counts.get(row.action, 0) + 1
        breakdown = ", ".join(
            f"{counts.get(action, 0)} {action}"
            for action in (
                STALE_REPAIR_ACTION_UNCHANGED,
                STALE_REPAIR_ACTION_LINKED,
                STALE_REPAIR_ACTION_REPAIRED,
                STALE_REPAIR_ACTION_UNRESOLVED,
            )
        )
        if self.applied:
            if self.audit_path is not None:
                return (
                    f"applied {self.changed} stale revision change(s) "
                    f"({breakdown}); audit {self.audit_path}"
                )
            return (
                f"no stale revision changes to apply ({breakdown}); "
                "outbox already consistent"
            )
        return (
            f"report only ({breakdown}); rerun with "
            f"`{REPAIR_REVISIONS_APPLY_COMMAND}` to write"
        )


def repair_stale_publication_revisions(
    projects: tuple[str, ...] = (),
    *,
    apply: bool = False,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> tuple[SyncOutcome, ...]:
    """Classify stale publication revisions for selected projects.

    Report mode (``apply=False``) writes nothing. Apply mode rewrites the
    outbox through the outbox mutation APIs and appends an audit JSONL.
    """

    selection = publication_support.resolve_sync_targets(projects)
    outcomes = list(selection.outcomes)
    try:
        owner = publication_support.require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        outcomes.extend(
            SyncOutcome(
                target.project_key,
                target.project,
                error=f"owner identity is not configured: {exc}",
            )
            for target in selection.targets
        )
        return tuple(sorted(outcomes, key=lambda item: item.project_key))

    for target in selection.targets:
        try:
            outcomes.append(
                _repair_project_revisions(
                    target,
                    owner,
                    apply=apply,
                    git_runner=git_runner,
                    lock_timeout_seconds=lock_timeout_seconds,
                )
            )
        except Exception as exc:  # noqa: BLE001 - per-project isolation contract
            outcomes.append(
                SyncOutcome(
                    target.project_key,
                    target.project,
                    error=f"agents revision repair failed: {exc}",
                )
            )
    return tuple(sorted(outcomes, key=lambda item: item.project_key))


def _repair_project_revisions(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    apply: bool,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> SyncOutcome:
    """Repair one project's stale outbox revisions under the agents lock."""

    timeout = (
        configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    if not target.primary_checkout.is_dir():
        return SyncOutcome(
            target.project_key,
            target.project,
            error="primary checkout does not exist",
        )
    clone_error = ensure_agents_clone(
        target, git_runner=git_runner, lock_timeout_seconds=timeout
    )
    if clone_error is not None:
        if clone_error == "agents sync clone lock is busy":
            return SyncOutcome(
                target.project_key, target.project, skip_reason=clone_error
            )
        return SyncOutcome(target.project_key, target.project, error=clone_error)

    lock_path = (
        agents_git_dir(target.sidecar_path, git_runner) / "sase-agents-sync.lock"
    )
    with bounded_agents_lock(lock_path, timeout) as acquired:
        if not acquired:
            return SyncOutcome(
                target.project_key,
                target.project,
                skip_reason="agents sync lock is busy",
            )
        report = _classify_project_revisions(target, owner, git_runner=git_runner)
        if apply:
            report = _apply_project_revisions(target, report)
        return SyncOutcome(
            target.project_key, target.project, diagnostics=report.diagnostics()
        )


def _classify_project_revisions(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    git_runner: GitRunner,
) -> _StaleRevisionRepairReport:
    """Classify every queued row without writing anything."""

    items = list_agent_publications(target.project_key)
    if not items:
        return _StaleRevisionRepairReport(
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
    return _StaleRevisionRepairReport(
        target.project_key,
        target.project,
        False,
        rows,
        sum(1 for row in rows if _row_changes_outbox(row, items)),
    )


def _row_changes_outbox(
    row: _StaleRevisionRowReport,
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
) -> _StaleRevisionRowReport:
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
    return _StaleRevisionRowReport(
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


def _apply_project_revisions(
    target: ProjectTarget,
    report: _StaleRevisionRepairReport,
) -> _StaleRevisionRepairReport:
    """Rewrite the outbox for changed rows and audit every applied change."""

    if report.changed == 0:
        return replace(report, applied=True)
    now = time.time()
    applied_rows: list[_StaleRevisionRowReport] = []
    by_request = {
        (row.global_agent, row.requested_revision): row for row in report.rows
    }

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        rewritten: list[AgentPublicationOutboxItem] = []
        for item in items:
            revised = _apply_row_report(item, report, now)
            rewritten.append(revised)
            if revised is not item:
                applied = by_request.get(
                    (revised.global_agent, revised.original_revision)
                )
                if applied is not None:
                    applied_rows.append(applied)
        grouped: dict[tuple[str, str], list[AgentPublicationOutboxItem]] = {}
        for item in rewritten:
            grouped.setdefault(item.logical_key, []).append(item)
        merged: list[AgentPublicationOutboxItem] = []
        for group in grouped.values():
            if len(group) == 1:
                merged.append(group[0])
            else:
                merged_item, merge_note = _merge_collision(group, now)
                merged.append(merged_item)
                applied_rows.append(merge_note)
        return tuple(sorted(merged, key=publication_sort_key))

    mutate_publication_outbox(target.project_key, update)
    audit_path: str | None = None
    if applied_rows:
        audit_path = _append_repair_audit(target.project_key, applied_rows, now)
    rows = tuple(_with_merge_notes(row, applied_rows) for row in report.rows)
    return replace(report, applied=True, rows=rows, audit_path=audit_path)


def _apply_row_report(
    item: AgentPublicationOutboxItem,
    report: _StaleRevisionRepairReport,
    now: float,
) -> AgentPublicationOutboxItem:
    """Rekey or re-scope one row when its report row still matches."""

    row = next(
        (
            candidate
            for candidate in report.rows
            if candidate.global_agent == item.global_agent
            and candidate.requested_revision == item.original_revision
        ),
        None,
    )
    if row is None or not row.changed:
        return item
    if row.action == STALE_REPAIR_ACTION_REPAIRED:
        if (
            item.primary_revision == row.fulfilling_revision
            and item.scope == PUBLICATION_SCOPE_REVISION
        ):
            return item
        return replace(
            item,
            primary_revision=row.fulfilling_revision or item.primary_revision,
            requested_revision=row.requested_revision,
            scope=PUBLICATION_SCOPE_REVISION,
            updated_at=now,
        )
    if item.scope == PUBLICATION_SCOPE_LINKED:
        return item
    return replace(
        item,
        scope=PUBLICATION_SCOPE_LINKED,
        updated_at=now,
    )


def _merge_collision(
    group: list[AgentPublicationOutboxItem],
    now: float,
) -> tuple[AgentPublicationOutboxItem, _StaleRevisionRowReport]:
    """Merge rows sharing a logical key after rekeying, deterministically."""

    ordered = sorted(group, key=lambda item: (item.created_at, item.id))
    survivor = ordered[0]
    latest = max(group, key=lambda item: (item.updated_at, item.id))
    digest = survivor.hood_digest
    if digest == "pending":
        for candidate in ordered[1:]:
            if candidate.hood_digest != "pending":
                digest = candidate.hood_digest
                break
    merged = replace(
        survivor,
        hood_digest=digest,
        scope=(
            PUBLICATION_SCOPE_REVISION
            if any(item.scope == PUBLICATION_SCOPE_REVISION for item in ordered)
            else PUBLICATION_SCOPE_LINKED
        ),
        attempts=max(item.attempts for item in ordered),
        last_error=latest.last_error,
        quarantined=any(item.quarantined for item in ordered),
        quarantined_at=(
            latest.quarantined_at if any(item.quarantined for item in ordered) else None
        ),
        terminal=any(item.terminal for item in ordered),
        terminal_reason=_merged_terminal_reason(ordered),
        updated_at=now,
    )
    note = _StaleRevisionRowReport(
        global_agent=merged.global_agent,
        local_agent=merged.local_agent,
        requested_revision=merged.original_revision,
        current_revision=merged.primary_revision,
        current_scope=merged.scope,
        action="merged",
        reason="logical-key collision merged deterministically",
        merged_from=tuple((item.global_agent, item.primary_revision) for item in group),
    )
    return merged, note


def _merged_terminal_reason(
    ordered: list[AgentPublicationOutboxItem],
) -> str | None:
    """Return the latest terminal reason among merged rows, if any."""

    terminal_rows = [item for item in ordered if item.terminal]
    if not terminal_rows:
        return None
    latest = max(terminal_rows, key=lambda item: (item.updated_at, item.id))
    return latest.terminal_reason


def _with_merge_notes(
    row: _StaleRevisionRowReport,
    applied_rows: list[_StaleRevisionRowReport],
) -> _StaleRevisionRowReport:
    """Attach merge records to their surviving report row."""

    for applied in applied_rows:
        if (
            applied.action == "merged"
            and applied.global_agent == row.global_agent
            and applied.requested_revision == row.requested_revision
        ):
            return replace(row, merged_from=applied.merged_from)
    return row


def _append_repair_audit(
    project_key: str,
    applied_rows: list[_StaleRevisionRowReport],
    now: float,
) -> str:
    """Append one audit JSON object per applied change beside the outbox."""

    path = sase_projects_dir() / project_key / REPAIR_REVISIONS_AUDIT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    applied_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    with path.open("a", encoding="utf-8") as handle:
        for row in applied_rows:
            handle.write(
                json.dumps(
                    {
                        "applied_at": applied_at,
                        "project_key": project_key,
                        "action": row.action,
                        "global_agent": row.global_agent,
                        "local_agent": row.local_agent,
                        "original_revision": row.requested_revision,
                        "current_revision": row.current_revision,
                        "fulfilling_revision": row.fulfilling_revision,
                        "new_scope": row.new_scope,
                        "evidence_commit": row.evidence_commit,
                        "merged_from": [
                            {
                                "global_agent": key[0],
                                "primary_revision": key[1],
                            }
                            for key in row.merged_from
                        ],
                        "reason": row.reason,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return str(path)


def _short(revision: str) -> str:
    """Return a stable abbreviated revision for report lines."""

    return revision[:12] if len(revision) > 12 else revision


__all__ = [
    "REPAIR_REVISIONS_APPLY_COMMAND",
    "REPAIR_REVISIONS_AUDIT_FILENAME",
    "REPAIR_REVISIONS_COMMAND",
    "repair_stale_publication_revisions",
]
