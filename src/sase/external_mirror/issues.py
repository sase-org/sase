"""Reconcile one project's external tracker issues into task beads.

:func:`run_issue_mirror_for_project` is the single code path both the
``external_issue_mirror`` AXE chop and ``sase bead sync-external`` run.

There is no page cursor, offset, ``since``, or ordering guarantee in the
issue-listing seam (``vcs_list_issues``), so each pass performs one full
listing (``state="all"``, ``limit=0``) rather than a windowed one — a
windowed listing would silently skip issues on at least one provider, which
breaks the "the bead list is a superset of the issue list" promise this
mirror exists to keep. The per-pass bound instead applies to local writes
(a creation cap and a wall-clock work budget), which is where the expensive,
contended work — the store lock, the git commit, and publication — actually
lives.

Mirrored beads get an explicit ``PhaseSize.SMALL``, not a null size. The
original design wanted null, on the theory that a chop cannot honestly
estimate and that NULL would make "needs triage" mechanically visible via a
``size:none`` filter token. Neither half holds against the current tree:
``sase-core``'s ``create_issue`` unconditionally rejects a sizeless task at
creation (``"new task issue creation requires an explicit size"``,
``mutation.rs:197-200``) — not a CLI-only gate, as the design assumed — and
``size:none`` was never wired into ``filter_query.py`` either. ``open``
status (never ``ready``) already keeps a mirrored bead out of the
``TaskTriage`` gate queue, which was the load-bearing half of the triage
story.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sase.bead.close_gate_settle import settle_closed_task_bead_gates
from sase.bead.model import Issue, IssueType, PhaseSize, Resolution, Status
from sase.bead.store_locator import (
    canonical_beads_dir_for_project,
    open_bead_project_for_beads_dir,
)
from sase.bead.sync import (
    bead_store_write_lock,
    commit_external_issue_mirror,
    publish_bead_claim,
)
from sase.bug_links import normalize_external_ref
from sase.core import bead_read_facade
from sase.vcs_provider import IssueWire, get_vcs_provider, supports_issue_listing

from .auth import classify_provider_error, record_tracker_probe
from .budget import LANE_CHOP_TIMEOUT_SECONDS
from .config import issue_filters
from .filters import IssueFilters
from .state import (
    is_backed_off,
    iso_utc,
    mirror_state_document_path,
    next_backoff,
    read_mirror_state,
    write_mirror_state,
)

MIRROR_KIND = "issues"


@dataclass(frozen=True)
class MirrorReport:
    """Outcome of one issue-mirror reconciliation pass for one project."""

    project: str
    display_name: str
    issues_seen: int = 0
    beads_created: int = 0
    beads_closed: int = 0
    beads_reopened: int = 0
    notes_appended: int = 0
    #: Already covered under the lock; a real duplicate was avoided.
    conflicts: int = 0
    #: Skipped by ``external_mirror.issues.filters`` (or its deprecated
    #: ``exclude_labels`` alias).
    unmirrored: int = 0
    #: Planned creations or notes the pass budget could not apply this pass.
    deferred: int = 0
    provider_calls: int = 0
    checkpoint_advanced: bool = False
    #: Dry-run detail: the refs that would be (or were) created, in apply order.
    created_refs: tuple[str, ...] = ()
    #: Dry-run/apply detail: mirrored refs whose beads would be (or were) closed.
    closed_refs: tuple[str, ...] = ()
    #: Dry-run/apply detail: mirrored refs whose beads would be (or were) reopened.
    reopened_refs: tuple[str, ...] = ()
    #: Non-empty reason when the pass was degraded (backoff, auth failure, ...).
    degraded: str = ""


def summary_counters(report: MirrorReport) -> dict[str, int]:
    """Return integer counters for a chop's ``emit_summary`` fields.

    ``parse_summary`` only keeps int-valued tokens, so the boolean
    ``checkpoint_advanced`` is marshalled to ``0``/``1`` here rather than at
    each call site.
    """
    return {
        "issues_seen": report.issues_seen,
        "beads_created": report.beads_created,
        "beads_closed": report.beads_closed,
        "beads_reopened": report.beads_reopened,
        "notes_appended": report.notes_appended,
        "conflicts": report.conflicts,
        "unmirrored": report.unmirrored,
        "deferred": report.deferred,
        "provider_calls": report.provider_calls,
        "checkpoint_advanced": int(report.checkpoint_advanced),
    }


@dataclass(frozen=True)
class _MirrorBudget:
    """Per-pass bounds shared by the chop and the CLI so both converge alike.

    Unlike ``bead_store_refresh``/``bead_claim_checks``, this reconciler
    handles exactly one project per invocation (the ``for_each`` fan-out
    already isolates projects into separate script runs), so there is no
    shared lock-wait budget to slice across competing projects in one pass.
    """

    #: Derived from ``LANE_CHOP_TIMEOUT_SECONDS``, the ``external_mirror``
    #: lane's configured ``chop_timeout``.
    work_seconds: float = 0.75 * LANE_CHOP_TIMEOUT_SECONDS
    max_creations: int = 25
    max_notes: int = 50


DEFAULT_BUDGET = _MirrorBudget()


@dataclass(frozen=True)
class _CreateCandidate:
    ref: str
    display_ref: str
    title: str
    description: str
    sort_key: tuple[str, str]


@dataclass(frozen=True)
class _CoveredBead:
    bead: Issue
    mirrored: bool


@dataclass(frozen=True)
class _TransitionCandidate:
    bead_id: str
    ref: str
    new_upstream_state: str
    action: Literal["close", "reopen", "none"]
    observation: str


@dataclass(frozen=True)
class _ApplyOutcome:
    beads_created: int = 0
    beads_closed: int = 0
    beads_reopened: int = 0
    notes_appended: int = 0
    conflicts: int = 0
    deferred: int = 0
    created_refs: tuple[str, ...] = ()
    closed_refs: tuple[str, ...] = ()
    reopened_refs: tuple[str, ...] = ()
    applied_note_refs: dict[str, str] = field(default_factory=dict)


def run_issue_mirror_for_project(
    *,
    project_key: str,
    display_name: str,
    workspace_dir: str,
    dry_run: bool = False,
    full: bool = False,
    source: Literal["chop", "cli"] = "chop",
    budget: _MirrorBudget = DEFAULT_BUDGET,
    now: datetime | None = None,
) -> MirrorReport:
    """Diff *project_key*'s tracker against its beads and reconcile drift."""
    current_time = now or datetime.now(UTC)
    state_path = mirror_state_document_path(MIRROR_KIND, project_key)
    state = read_mirror_state(state_path, project=project_key)

    if not full and is_backed_off(state, now=current_time):
        return MirrorReport(
            project=project_key, display_name=display_name, degraded="backoff"
        )

    if not supports_issue_listing(workspace_dir):
        record_tracker_probe(
            project_key, outcome="unsupported", source=source, now=current_time
        )
        return MirrorReport(
            project=project_key,
            display_name=display_name,
            degraded="unsupported_provider",
        )

    try:
        provider = get_vcs_provider(workspace_dir)
        issues = provider.list_issues(workspace_dir, state="all", limit=0)
    except Exception as error:  # noqa: BLE001 - classified and reported below.
        classification = classify_provider_error(error)
        record_tracker_probe(
            project_key,
            outcome=classification,
            source=source,
            detail=str(error),
            now=current_time,
        )
        if not dry_run:
            failures, next_attempt_at = next_backoff(state.failures, now=current_time)
            state.failures = failures
            state.next_attempt_at = next_attempt_at
            write_mirror_state(state_path, state)
        return MirrorReport(
            project=project_key,
            display_name=display_name,
            provider_calls=1,
            degraded=classification,
        )

    record_tracker_probe(project_key, outcome="ok", source=source, now=current_time)

    filters = issue_filters()
    filters_fingerprint = filters.fingerprint()
    max_updated_at = max((issue.updated_at for issue in issues), default="")
    provider_ids = frozenset(_issue_identity(issue) for issue in issues)

    if (
        not full
        and state.backfill_complete
        and max_updated_at
        and max_updated_at <= state.watermark_updated_at
        and provider_ids == frozenset(state.watermark_provider_ids)
        and filters_fingerprint == state.filters_fingerprint
    ):
        return MirrorReport(
            project=project_key,
            display_name=display_name,
            issues_seen=len(issues),
            unmirrored=_unmirrored_count(issues, filters),
            provider_calls=1,
            checkpoint_advanced=True,
        )

    mirrorable = [issue for issue in issues if filters.matches(issue)]
    unmirrored = len(issues) - len(mirrorable)

    beads_dir = canonical_beads_dir_for_project(project_key)
    if beads_dir is None:
        return MirrorReport(
            project=project_key,
            display_name=display_name,
            issues_seen=len(issues),
            unmirrored=unmirrored,
            provider_calls=1,
            degraded="no_canonical_bead_store",
        )

    local_beads = bead_read_facade.list_issues(beads_dir)
    covered = _build_identity_index(local_beads, project=project_key)

    current_refs: dict[str, IssueWire] = {}
    for issue in issues:
        ref = normalize_external_ref(issue.number, project=project_key)
        if ref:
            current_refs[ref] = issue

    transition_candidates = _plan_transitions(
        current_refs=current_refs,
        covered=covered,
        upstream_states=state.upstream_states,
        display_name=display_name,
        current_time=current_time,
    )

    create_candidates: list[_CreateCandidate] = []
    for issue in mirrorable:
        ref = normalize_external_ref(issue.number, project=project_key)
        if not ref or ref in covered:
            continue
        create_candidates.append(
            _build_create_candidate(issue, ref=ref, display_name=display_name)
        )
    create_candidates.sort(key=lambda candidate: candidate.sort_key)

    if dry_run:
        closed_refs, reopened_refs = _preview_transition_refs(
            transition_candidates,
            covered=covered,
            blocked_ids=_unclosed_ancestor_ids(local_beads),
        )
        return MirrorReport(
            project=project_key,
            display_name=display_name,
            issues_seen=len(issues),
            unmirrored=unmirrored,
            provider_calls=1,
            created_refs=tuple(candidate.ref for candidate in create_candidates),
            closed_refs=closed_refs,
            reopened_refs=reopened_refs,
        )

    outcome = _apply(
        beads_dir=beads_dir,
        project_key=project_key,
        create_candidates=create_candidates,
        transition_candidates=transition_candidates,
        budget=budget,
    )

    if outcome.deferred == 0:
        covered_after = set(covered) | set(outcome.created_refs)
        upstream_states = dict(state.upstream_states)
        upstream_states.update(outcome.applied_note_refs)
        for ref, issue in current_refs.items():
            if ref in covered_after and ref not in upstream_states:
                upstream_states[ref] = issue.state
        state.upstream_states = {
            ref: value for ref, value in upstream_states.items() if ref in covered_after
        }
        state.backfill_complete = True
        if max_updated_at:
            state.watermark_updated_at = max_updated_at
            state.watermark_provider_ids = tuple(sorted(provider_ids))
        state.filters_fingerprint = filters_fingerprint
        state.last_full_scan_at = iso_utc(current_time)
        state.last_success_at = iso_utc(current_time)
        state.failures = 0
        state.next_attempt_at = ""
        write_mirror_state(state_path, state)
    elif outcome.applied_note_refs:
        upstream_states = dict(state.upstream_states)
        upstream_states.update(outcome.applied_note_refs)
        state.upstream_states = upstream_states
        write_mirror_state(state_path, state)

    return MirrorReport(
        project=project_key,
        display_name=display_name,
        issues_seen=len(issues),
        unmirrored=unmirrored,
        provider_calls=1,
        beads_created=outcome.beads_created,
        beads_closed=outcome.beads_closed,
        beads_reopened=outcome.beads_reopened,
        notes_appended=outcome.notes_appended,
        conflicts=outcome.conflicts,
        deferred=outcome.deferred,
        checkpoint_advanced=outcome.deferred == 0,
        created_refs=outcome.created_refs,
        closed_refs=outcome.closed_refs,
        reopened_refs=outcome.reopened_refs,
    )


def _apply(
    *,
    beads_dir: Path,
    project_key: str,
    create_candidates: list[_CreateCandidate],
    transition_candidates: list[_TransitionCandidate],
    budget: _MirrorBudget,
) -> _ApplyOutcome:
    """Apply planned creates and transitions under one lock, one commit, one publish."""
    if not create_candidates and not transition_candidates:
        return _ApplyOutcome()

    beads_created = 0
    beads_closed = 0
    beads_reopened = 0
    notes_appended = 0
    conflicts = 0
    deferred = 0
    created_refs: list[str] = []
    closed_refs: list[str] = []
    reopened_refs: list[str] = []
    closed_task_ids: list[str] = []
    applied_note_refs: dict[str, str] = {}
    changed = False
    committed = False
    work_deadline = time.monotonic() + budget.work_seconds

    with bead_store_write_lock(beads_dir) as already_locked:
        with open_bead_project_for_beads_dir(beads_dir) as project:
            live_beads = project.list_issues()
            live_index = _build_identity_index(live_beads, project=project_key)
            blocked_ids = _unclosed_ancestor_ids(live_beads)
            for candidate in create_candidates:
                if (
                    beads_created >= budget.max_creations
                    or time.monotonic() >= work_deadline
                ):
                    deferred += 1
                    continue
                if candidate.ref in live_index:
                    conflicts += 1
                    continue
                issue = project.create(
                    candidate.title,
                    IssueType.TASK,
                    description=candidate.description,
                    refs=[candidate.display_ref],
                    external_ref=candidate.ref,
                    size=PhaseSize.SMALL,
                )
                live_index[candidate.ref] = _CoveredBead(issue, mirrored=True)
                beads_created += 1
                changed = True
                created_refs.append(candidate.ref)

            for transition in transition_candidates:
                if (
                    notes_appended >= budget.max_notes
                    or time.monotonic() >= work_deadline
                ):
                    deferred += 1
                    continue
                covered = live_index.get(transition.ref)
                if covered is None or covered.bead.id != transition.bead_id:
                    continue
                bead = covered.bead
                action = _transition_action(
                    mirrored=covered.mirrored,
                    new_upstream_state=transition.new_upstream_state,
                )
                reason = (
                    _blocked_reason(bead, action=action, blocked_ids=blocked_ids)
                    if action != "none"
                    else ""
                )
                if action == "close" and not reason:
                    project.close(
                        [bead.id],
                        resolution=Resolution.DONE,
                        note=_transition_note(
                            transition,
                            action=action,
                            reason="",
                            applied=True,
                        ),
                        author="external_issue_mirror",
                    )
                    beads_closed += 1
                    closed_refs.append(transition.ref)
                    if bead.issue_type is IssueType.TASK:
                        closed_task_ids.append(bead.id)
                elif action == "reopen" and not reason:
                    project.open(bead.id)
                    project.append_note(
                        bead.id,
                        _transition_note(
                            transition,
                            action=action,
                            reason="",
                            applied=True,
                        ),
                        author="external_issue_mirror",
                    )
                    beads_reopened += 1
                    reopened_refs.append(transition.ref)
                else:
                    project.append_note(
                        bead.id,
                        _transition_note(
                            transition,
                            action=action,
                            reason=reason,
                            applied=False,
                        ),
                        author="external_issue_mirror",
                    )
                notes_appended += 1
                changed = True
                applied_note_refs[transition.ref] = transition.new_upstream_state

        if changed:
            committed = commit_external_issue_mirror(
                beads_dir,
                project_key,
                already_locked=already_locked,
            )

    if committed:
        publish_bead_claim(beads_dir, "external_issue_mirror", project_key)
    settle_closed_task_bead_gates(project_key, closed_task_ids, source="chop")

    return _ApplyOutcome(
        beads_created=beads_created,
        beads_closed=beads_closed,
        beads_reopened=beads_reopened,
        notes_appended=notes_appended,
        conflicts=conflicts,
        deferred=deferred,
        created_refs=tuple(created_refs),
        closed_refs=tuple(closed_refs),
        reopened_refs=tuple(reopened_refs),
        applied_note_refs=applied_note_refs,
    )


def _plan_transitions(
    *,
    current_refs: dict[str, IssueWire],
    covered: dict[str, _CoveredBead],
    upstream_states: dict[str, str],
    display_name: str,
    current_time: datetime,
) -> list[_TransitionCandidate]:
    transitions: list[_TransitionCandidate] = []
    for ref in sorted(current_refs):
        issue = current_refs[ref]
        covered_bead = covered.get(ref)
        if covered_bead is None:
            continue
        previous_state = upstream_states.get(ref)
        if previous_state is None or previous_state == issue.state:
            continue
        transitions.append(
            _TransitionCandidate(
                bead_id=covered_bead.bead.id,
                ref=ref,
                new_upstream_state=issue.state,
                action=_transition_action(
                    mirrored=covered_bead.mirrored,
                    new_upstream_state=issue.state,
                ),
                observation=(
                    f"Upstream issue {display_name}#{issue.number} changed state: "
                    f"{previous_state} -> {issue.state} (observed "
                    f"{iso_utc(current_time)} by external_issue_mirror)."
                ),
            )
        )

    for ref in sorted(upstream_states):
        previous_state = upstream_states[ref]
        if ref in current_refs or previous_state == "absent":
            continue
        covered_bead = covered.get(ref)
        if covered_bead is None:
            continue
        issue_id = ref.rsplit("#", 1)[-1]
        transitions.append(
            _TransitionCandidate(
                bead_id=covered_bead.bead.id,
                ref=ref,
                new_upstream_state="absent",
                action="none",
                observation=(
                    f"Upstream issue {display_name}#{issue_id} is no longer present "
                    "in the tracker listing (deleted or transferred), observed "
                    f"{iso_utc(current_time)} by external_issue_mirror."
                ),
            )
        )
    return transitions


def _build_create_candidate(
    issue: IssueWire, *, ref: str, display_name: str
) -> _CreateCandidate:
    display_ref = f"bug:{display_name}#{issue.number}"
    title = issue.title.strip() or f"Issue #{issue.number}"
    body = issue.body.strip()
    provenance = (
        f"---\nMirrored from {issue.url} by SASE's `external_issue_mirror` chop.\n"
        f"Upstream state when mirrored: {issue.state}."
    )
    description = f"{body}\n\n{provenance}" if body else provenance
    return _CreateCandidate(
        ref=ref,
        display_ref=display_ref,
        title=title,
        description=description,
        sort_key=(issue.updated_at, _issue_identity(issue)),
    )


def _preview_transition_refs(
    candidates: list[_TransitionCandidate],
    *,
    covered: dict[str, _CoveredBead],
    blocked_ids: frozenset[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    closed_refs: list[str] = []
    reopened_refs: list[str] = []
    for candidate in candidates:
        covered_bead = covered.get(candidate.ref)
        if covered_bead is None or covered_bead.bead.id != candidate.bead_id:
            continue
        if candidate.action == "close" and not _blocked_reason(
            covered_bead.bead,
            action=candidate.action,
            blocked_ids=blocked_ids,
        ):
            closed_refs.append(candidate.ref)
        elif candidate.action == "reopen" and not _blocked_reason(
            covered_bead.bead,
            action=candidate.action,
            blocked_ids=blocked_ids,
        ):
            reopened_refs.append(candidate.ref)
    return tuple(closed_refs), tuple(reopened_refs)


def _transition_action(
    *,
    mirrored: bool,
    new_upstream_state: str,
) -> Literal["close", "reopen", "none"]:
    if not mirrored:
        return "none"
    if new_upstream_state == "closed":
        return "close"
    if new_upstream_state == "open":
        return "reopen"
    return "none"


def _transition_note(
    candidate: _TransitionCandidate,
    *,
    action: Literal["close", "reopen", "none"],
    reason: str,
    applied: bool,
) -> str:
    if candidate.new_upstream_state == "absent":
        return f"{candidate.observation} The external link is stale."
    if applied and action == "close":
        return f"{candidate.observation} Closed this mirrored bead to match."
    if applied and action == "reopen":
        return f"{candidate.observation} Reopened this mirrored bead to match."
    if reason:
        return (
            f"{candidate.observation} This bead's status is unchanged ({reason}); "
            "reconcile deliberately."
        )
    return (
        f"{candidate.observation} This bead's status is unchanged; "
        "reconcile deliberately."
    )


def _unclosed_ancestor_ids(beads: list[Issue]) -> frozenset[str]:
    by_id = {bead.id: bead for bead in beads}
    blocked: set[str] = set()
    for bead in beads:
        if bead.status is Status.CLOSED:
            continue
        parent_id = bead.parent_id
        seen: set[str] = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            blocked.add(parent_id)
            parent = by_id.get(parent_id)
            parent_id = parent.parent_id if parent is not None else None
    return frozenset(blocked)


def _blocked_reason(
    bead: Issue,
    *,
    action: Literal["close", "reopen"],
    blocked_ids: frozenset[str],
) -> str:
    if action == "close":
        if bead.status is Status.CLOSED:
            return "the bead is already closed"
        if bead.status in {Status.CLAIMED, Status.IN_PROGRESS}:
            return "an agent is working this bead"
        if bead.id in blocked_ids:
            return "the bead has unclosed descendants"
        return ""
    if bead.status is Status.CLOSED:
        return ""
    return "the bead is already open"


def _build_identity_index(
    beads: list[Issue], *, project: str
) -> dict[str, _CoveredBead]:
    index: dict[str, _CoveredBead] = {}
    for bead in beads:
        normalized = normalize_external_ref(bead.external_ref, project=project)
        if normalized and normalized not in index:
            index[normalized] = _CoveredBead(bead, mirrored=True)
    for bead in beads:
        for raw_ref in bead.refs:
            if not raw_ref.strip().casefold().startswith("bug:"):
                continue
            normalized = normalize_external_ref(raw_ref, project=project)
            if normalized and normalized not in index:
                index[normalized] = _CoveredBead(bead, mirrored=False)
    return index


def _unmirrored_count(issues: list[IssueWire], filters: IssueFilters) -> int:
    return sum(1 for issue in issues if not filters.matches(issue))


def _issue_identity(issue: IssueWire) -> str:
    return issue.provider_id or str(issue.number)


__all__ = [
    "DEFAULT_BUDGET",
    "MIRROR_KIND",
    "MirrorReport",
    "run_issue_mirror_for_project",
    "summary_counters",
]
