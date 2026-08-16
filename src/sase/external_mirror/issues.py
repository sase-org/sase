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

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sase.workspace_provider.ownership import OperationContext

from sase.bead.store_locator import canonical_beads_dir_for_project
from sase.bug_links import normalize_external_ref
from sase.core import bead_read_facade
from sase.vcs_provider import IssueWire, get_vcs_provider, supports_issue_listing

from ._issue_apply import apply_issue_mirror
from ._issue_models import (
    ApplyOutcome,
    CreateCandidate,
    MirrorBudget,
    MirrorReport,
    TransitionCandidate,
)
from ._issue_planning import (
    build_create_candidate,
    build_identity_index,
    issue_identity,
    plan_transitions,
    preview_transition_refs,
    unclosed_ancestor_ids,
    unmirrored_count,
)
from .auth import classify_provider_error, record_tracker_probe
from .config import issue_filters
from .state import (
    is_backed_off,
    iso_utc,
    mirror_state_document_path,
    next_backoff,
    read_mirror_state,
    write_mirror_state,
)

MIRROR_KIND = "issues"


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


DEFAULT_BUDGET = MirrorBudget()


def run_issue_mirror_for_project(
    *,
    project_key: str,
    display_name: str,
    workspace_dir: str,
    dry_run: bool = False,
    full: bool = False,
    source: Literal["chop", "cli"] = "chop",
    budget: MirrorBudget = DEFAULT_BUDGET,
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
    provider_ids = frozenset(issue_identity(issue) for issue in issues)

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
            unmirrored=unmirrored_count(issues, filters),
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
    covered = build_identity_index(local_beads, project=project_key)

    current_refs: dict[str, IssueWire] = {}
    for issue in issues:
        ref = normalize_external_ref(issue.number, project=project_key)
        if ref:
            current_refs[ref] = issue

    transition_candidates = plan_transitions(
        current_refs=current_refs,
        covered=covered,
        upstream_states=state.upstream_states,
        display_name=display_name,
        current_time=current_time,
    )

    create_candidates: list[CreateCandidate] = []
    for issue in mirrorable:
        ref = normalize_external_ref(issue.number, project=project_key)
        if not ref or ref in covered:
            continue
        create_candidates.append(
            build_create_candidate(issue, ref=ref, display_name=display_name)
        )
    create_candidates.sort(key=lambda candidate: candidate.sort_key)

    if dry_run:
        closed_refs, reopened_refs = preview_transition_refs(
            transition_candidates,
            covered=covered,
            blocked_ids=unclosed_ancestor_ids(local_beads),
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

    outcome = _apply_issue_mirror_for_source(
        source=source,
        project_key=project_key,
        workspace_dir=workspace_dir,
        planning_beads_dir=beads_dir,
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


def _apply_issue_mirror_for_source(
    *,
    source: Literal["chop", "cli"],
    project_key: str,
    workspace_dir: str,
    planning_beads_dir: Path,
    create_candidates: list[CreateCandidate],
    transition_candidates: list[TransitionCandidate],
    budget: MirrorBudget,
) -> ApplyOutcome:
    """Apply planned mirror writes through a source-appropriate store."""

    if source == "cli":
        beads_dir, context, origin = _cli_writable_mirror_store(
            project_key, workspace_dir, planning_beads_dir
        )
        return apply_issue_mirror(
            beads_dir=beads_dir,
            project_key=project_key,
            create_candidates=create_candidates,
            transition_candidates=transition_candidates,
            budget=budget,
            mutation_origin=origin,
            operation_context=context,
        )

    from sase.bead.background_store import writable_bead_store_for_machine

    with writable_bead_store_for_machine(
        project_key,
        workflow="chop:external_issue_mirror",
        holder=f"external_issue_mirror:{project_key}",
    ) as store:
        from sase.bead.sync import refresh_bead_store

        try:
            refresh_bead_store(store.beads_dir)
        except Exception:
            pass
        return apply_issue_mirror(
            beads_dir=store.beads_dir,
            project_key=project_key,
            create_candidates=create_candidates,
            transition_candidates=transition_candidates,
            budget=budget,
            mutation_origin="machine",
            operation_context=store.context,
        )


def _cli_writable_mirror_store(
    project_key: str,
    workspace_dir: str,
    planning_beads_dir: Path,
) -> tuple[Path, OperationContext | None, str]:
    """Foreground CLI may mutate the user-directed store; never lease away."""

    try:
        from sase.workspace_provider.ownership import (
            user_directed_context,
            writable_beads_dir,
        )

        context = user_directed_context(cwd=workspace_dir, project=project_key)
        return writable_beads_dir(context), context, "user"
    except Exception:
        return planning_beads_dir, None, "user"


__all__ = [
    "DEFAULT_BUDGET",
    "MIRROR_KIND",
    "MirrorReport",
    "run_issue_mirror_for_project",
    "summary_counters",
]
