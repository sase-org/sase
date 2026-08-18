"""Apply planned external issue reconciliation under the bead-store lock."""

from __future__ import annotations

import time
from pathlib import Path

from sase.bead.close_gate_settle import settle_closed_task_bead_gates
from sase.bead.model import IssueType, PhaseSize, Resolution
from sase.bead.store_locator import open_bead_project_for_beads_dir
from sase.bead.sync import (
    bead_store_write_lock,
    commit_external_issue_mirror,
    publish_bead_claim,
)
from sase.plugins.required import missing_required_plugin_message
from sase.task_types import get_task_type_registry
from sase.workspace_provider.ownership import OperationContext

from ._issue_models import (
    ApplyOutcome,
    CoveredBead,
    CreateCandidate,
    MirrorBudget,
    TransitionCandidate,
)
from ._issue_planning import (
    blocked_reason,
    build_identity_index,
    transition_action,
    transition_note,
    unclosed_ancestor_ids,
)

_MIRRORED_ISSUE_TASK_TYPE = "github"
_MIRRORED_ISSUE_TASK_TYPE_PLUGIN = "sase-github"


def _require_github_task_type() -> None:
    """Fail closed when the ``github`` task type is not in the live catalog.

    The mirror only creates beads when sase-github is installed, so the type
    is normally present. If it is somehow absent, refuse to create an untyped
    bead and surface the same ``plugins.required`` install message.
    """
    if _MIRRORED_ISSUE_TASK_TYPE in get_task_type_registry().by_slug:
        return
    raise RuntimeError(
        missing_required_plugin_message(_MIRRORED_ISSUE_TASK_TYPE_PLUGIN)
    )


def apply_issue_mirror(
    *,
    beads_dir: Path,
    project_key: str,
    create_candidates: list[CreateCandidate],
    transition_candidates: list[TransitionCandidate],
    budget: MirrorBudget,
    mutation_origin: str = "user",
    operation_context: OperationContext | None = None,
) -> ApplyOutcome:
    """Apply planned creates and transitions under one lock, one commit, one publish."""
    if not create_candidates and not transition_candidates:
        return ApplyOutcome()
    if create_candidates:
        _require_github_task_type()

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
            live_index = build_identity_index(live_beads, project=project_key)
            blocked_ids = unclosed_ancestor_ids(live_beads)
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
                    task_type=_MIRRORED_ISSUE_TASK_TYPE,
                )
                live_index[candidate.ref] = CoveredBead(issue, mirrored=True)
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
                action = transition_action(
                    mirrored=covered.mirrored,
                    new_upstream_state=transition.new_upstream_state,
                )
                reason = (
                    blocked_reason(bead, action=action, blocked_ids=blocked_ids)
                    if action != "none"
                    else ""
                )
                if action == "close" and not reason:
                    project.close(
                        [bead.id],
                        resolution=Resolution.DONE,
                        note=transition_note(
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
                        transition_note(
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
                        transition_note(
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
                mutation_origin=mutation_origin,
                operation_context=operation_context,
            )

    if committed:
        publish_bead_claim(beads_dir, "external_issue_mirror", project_key)
        from sase.bead.background_store import schedule_beads_sidecar_convergence

        schedule_beads_sidecar_convergence(project_key)
    settle_closed_task_bead_gates(project_key, closed_task_ids, source="chop")

    return ApplyOutcome(
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
