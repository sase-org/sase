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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sase.bead.model import Issue, IssueType, PhaseSize
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
from .config import excluded_issue_labels
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
    notes_appended: int = 0
    #: Already covered under the lock; a real duplicate was avoided.
    conflicts: int = 0
    #: Skipped by ``external_mirror.exclude_labels``.
    unmirrored: int = 0
    #: Planned creations or notes the pass budget could not apply this pass.
    deferred: int = 0
    provider_calls: int = 0
    checkpoint_advanced: bool = False
    #: Dry-run detail: the refs that would be (or were) created, in apply order.
    created_refs: tuple[str, ...] = ()
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

    #: Tied to the chop's ``timeout: "2m"`` in ``default_config.yml``.
    work_seconds: float = 90.0
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
class _NoteCandidate:
    bead_id: str
    text: str
    ref: str
    new_upstream_state: str


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

    max_updated_at = max((issue.updated_at for issue in issues), default="")
    provider_ids = frozenset(_issue_identity(issue) for issue in issues)

    if (
        not full
        and state.backfill_complete
        and max_updated_at
        and max_updated_at <= state.watermark_updated_at
        and provider_ids == frozenset(state.watermark_provider_ids)
    ):
        return MirrorReport(
            project=project_key,
            display_name=display_name,
            issues_seen=len(issues),
            unmirrored=_excluded_count(issues),
            provider_calls=1,
            checkpoint_advanced=True,
        )

    excluded = excluded_issue_labels()
    mirrorable = [issue for issue in issues if not _is_excluded(issue, excluded)]
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

    note_candidates = _plan_notes(
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
        return MirrorReport(
            project=project_key,
            display_name=display_name,
            issues_seen=len(issues),
            unmirrored=unmirrored,
            provider_calls=1,
            created_refs=tuple(candidate.ref for candidate in create_candidates),
        )

    (
        beads_created,
        notes_appended,
        conflicts,
        deferred,
        created_refs,
        applied_note_refs,
    ) = _apply(
        beads_dir=beads_dir,
        project_key=project_key,
        create_candidates=create_candidates,
        note_candidates=note_candidates,
        budget=budget,
    )

    if deferred == 0:
        covered_after = set(covered) | set(created_refs)
        upstream_states = dict(state.upstream_states)
        upstream_states.update(applied_note_refs)
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
        state.last_full_scan_at = iso_utc(current_time)
        state.last_success_at = iso_utc(current_time)
        state.failures = 0
        state.next_attempt_at = ""
        write_mirror_state(state_path, state)

    return MirrorReport(
        project=project_key,
        display_name=display_name,
        issues_seen=len(issues),
        unmirrored=unmirrored,
        provider_calls=1,
        beads_created=beads_created,
        notes_appended=notes_appended,
        conflicts=conflicts,
        deferred=deferred,
        checkpoint_advanced=deferred == 0,
        created_refs=tuple(created_refs),
    )


def _apply(
    *,
    beads_dir: Path,
    project_key: str,
    create_candidates: list[_CreateCandidate],
    note_candidates: list[_NoteCandidate],
    budget: _MirrorBudget,
) -> tuple[int, int, int, int, list[str], dict[str, str]]:
    """Apply planned creates and notes under one lock, one commit, one publish."""
    if not create_candidates and not note_candidates:
        return 0, 0, 0, 0, [], {}

    beads_created = 0
    notes_appended = 0
    conflicts = 0
    deferred = 0
    created_refs: list[str] = []
    applied_note_refs: dict[str, str] = {}
    changed = False
    committed = False
    work_deadline = time.monotonic() + budget.work_seconds

    with bead_store_write_lock(beads_dir) as already_locked:
        with open_bead_project_for_beads_dir(beads_dir) as project:
            live_index = _build_identity_index(
                project.list_issues(), project=project_key
            )
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
                live_index[candidate.ref] = issue
                beads_created += 1
                changed = True
                created_refs.append(candidate.ref)

            for note in note_candidates:
                if (
                    notes_appended >= budget.max_notes
                    or time.monotonic() >= work_deadline
                ):
                    deferred += 1
                    continue
                project.append_note(
                    note.bead_id, note.text, author="external_issue_mirror"
                )
                notes_appended += 1
                changed = True
                applied_note_refs[note.ref] = note.new_upstream_state

        if changed:
            committed = commit_external_issue_mirror(
                beads_dir,
                project_key,
                already_locked=already_locked,
            )

    if committed:
        publish_bead_claim(beads_dir, "external_issue_mirror", project_key)

    return (
        beads_created,
        notes_appended,
        conflicts,
        deferred,
        created_refs,
        applied_note_refs,
    )


def _plan_notes(
    *,
    current_refs: dict[str, IssueWire],
    covered: dict[str, Issue],
    upstream_states: dict[str, str],
    display_name: str,
    current_time: datetime,
) -> list[_NoteCandidate]:
    notes: list[_NoteCandidate] = []
    for ref in sorted(current_refs):
        issue = current_refs[ref]
        bead = covered.get(ref)
        if bead is None:
            continue
        previous_state = upstream_states.get(ref)
        if previous_state is None or previous_state == issue.state:
            continue
        notes.append(
            _NoteCandidate(
                bead_id=bead.id,
                text=(
                    f"Upstream issue {display_name}#{issue.number} changed state: "
                    f"{previous_state} -> {issue.state} (observed "
                    f"{iso_utc(current_time)} by external_issue_mirror). This "
                    "bead's status is unchanged; reconcile deliberately."
                ),
                ref=ref,
                new_upstream_state=issue.state,
            )
        )

    for ref in sorted(upstream_states):
        previous_state = upstream_states[ref]
        if ref in current_refs or previous_state == "absent":
            continue
        bead = covered.get(ref)
        if bead is None:
            continue
        issue_id = ref.rsplit("#", 1)[-1]
        notes.append(
            _NoteCandidate(
                bead_id=bead.id,
                text=(
                    f"Upstream issue {display_name}#{issue_id} is no longer present "
                    "in the tracker listing (deleted or transferred), observed "
                    f"{iso_utc(current_time)} by external_issue_mirror. The external "
                    "link is stale."
                ),
                ref=ref,
                new_upstream_state="absent",
            )
        )
    return notes


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


def _build_identity_index(beads: list[Issue], *, project: str) -> dict[str, Issue]:
    index: dict[str, Issue] = {}
    for bead in beads:
        candidates = [bead.external_ref]
        candidates.extend(
            ref for ref in bead.refs if ref.strip().casefold().startswith("bug:")
        )
        for raw_ref in candidates:
            normalized = normalize_external_ref(raw_ref, project=project)
            if normalized and normalized not in index:
                index[normalized] = bead
    return index


def _is_excluded(issue: IssueWire, excluded_labels: frozenset[str]) -> bool:
    if not excluded_labels:
        return False
    return any(label.casefold() in excluded_labels for label in issue.labels)


def _excluded_count(issues: list[IssueWire]) -> int:
    excluded = excluded_issue_labels()
    if not excluded:
        return 0
    return sum(1 for issue in issues if _is_excluded(issue, excluded))


def _issue_identity(issue: IssueWire) -> str:
    return issue.provider_id or str(issue.number)


__all__ = [
    "DEFAULT_BUDGET",
    "MIRROR_KIND",
    "MirrorReport",
    "run_issue_mirror_for_project",
    "summary_counters",
]
