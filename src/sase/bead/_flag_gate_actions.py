"""Host effects a human's FlagTriage decision authorizes.

Each helper re-checks the action it implements, so an adapter that routes a
decision to the wrong effect fails loudly instead of, say, extending a flag
someone asked to remove. Every mutation goes through the CLI's locked
commit/push semantics rather than touching a store directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead._flag_gate_response import FlagTriageResponse
from sase.bead._flag_gate_spec import (
    FLAG_TRIAGE_CLOSE_OPTION_ID,
    FLAG_TRIAGE_EXTEND_OPTION_ID,
    FLAG_TRIAGE_KEEP_OPTION_ID,
    FLAG_TRIAGE_REMOVE_OPTION_ID,
)
from sase.bead.task_gate import bead_gate_actor
from sase.notification_gates.models import GateError

if TYPE_CHECKING:
    from sase.bead.task_launch import TaskLaunchOrigin
    from sase.procs.models import Proc


def remove_flag_triage(
    decision: FlagTriageResponse,
    *,
    origin: TaskLaunchOrigin | None = None,
) -> Proc:
    """Record the winning branch and submit the flag's removal launch."""
    if decision.action != FLAG_TRIAGE_REMOVE_OPTION_ID or decision.winner is None:
        raise GateError(
            "invalid_flag_action",
            decision.action,
            "flag triage remove helper requires remove with a winning branch",
        )
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import require_mutation_commit_message
    from sase.bead.task_launch import (
        submit_task_launch_task,
        task_launch_origin_from_gate_source,
    )

    note = f"Flag removal triaged: the {decision.winner} branch wins."
    if decision.feedback:
        note = f"{note} {decision.feedback}"
    cwd = _resolve_flag_triage_project_cwd(decision.project)
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        actor = bead_gate_actor(mutation.project)
        mutation.project.append_note(decision.bead_id, note, author=actor)
        mutation.commit(require_mutation_commit_message("note", [decision.bead_id]))
    brief = (
        f"This is a feature-flag removal bead for the `{decision.key}` flag. "
        f"The `{decision.winner}` branch wins: delete the losing branch and the "
        "registry entry in the same change that closes this bead."
    )
    return submit_task_launch_task(
        decision.bead_id,
        project=decision.project,
        feedback=brief,
        origin=(
            origin
            if origin is not None
            else task_launch_origin_from_gate_source(decision.source)
        ),
    )


def extend_flag_triage(decision: FlagTriageResponse) -> None:
    """Rewrite the flag's removal thresholds and record why."""
    if (
        decision.action != FLAG_TRIAGE_EXTEND_OPTION_ID
        or decision.remove_by_date is None
        or decision.remove_by_release is None
    ):
        raise GateError(
            "invalid_flag_action",
            decision.action,
            "flag triage extend helper requires extend with new thresholds",
        )
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.flag_fields import is_flag_task_bead, replace_flag_thresholds
    from sase.bead.mutation_commit import require_mutation_commit_message

    note = (
        f"Flag removal extended from {decision.old_remove_by_date} "
        f"(v{decision.old_remove_by_release}) to {decision.remove_by_date} "
        f"(v{decision.remove_by_release}): {decision.feedback}"
    )
    cwd = _resolve_flag_triage_project_cwd(decision.project)
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        actor = bead_gate_actor(mutation.project)
        issue = mutation.project.show(decision.bead_id)
        if not is_flag_task_bead(issue):
            raise GateError(
                "invalid_flag_action",
                decision.action,
                f"{decision.bead_id} is not a flag bead",
            )
        mutation.project.update(
            decision.bead_id,
            task_type_fields=replace_flag_thresholds(
                issue.task_type_fields,
                remove_by_date=decision.remove_by_date,
                remove_by_release=decision.remove_by_release,
            ),
        )
        mutation.project.append_note(decision.bead_id, note, author=actor)
        mutation.commit(require_mutation_commit_message("update", [decision.bead_id]))


def keep_flag_triage(
    decision: FlagTriageResponse,
    *,
    origin: TaskLaunchOrigin | None = None,
) -> Proc:
    """Record the permanence rationale and launch a promotion worker."""
    if decision.action != FLAG_TRIAGE_KEEP_OPTION_ID:
        raise GateError(
            "invalid_flag_action",
            decision.action,
            "flag triage keep helper requires the keep action",
        )
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import require_mutation_commit_message
    from sase.bead.task_launch import (
        submit_task_launch_task,
        task_launch_origin_from_gate_source,
    )

    note = f"Flag kept rather than removed: {decision.feedback}"
    cwd = _resolve_flag_triage_project_cwd(decision.project)
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        actor = bead_gate_actor(mutation.project)
        mutation.project.append_note(decision.bead_id, note, author=actor)
        mutation.commit(require_mutation_commit_message("note", [decision.bead_id]))
    brief = (
        f"This is a feature-flag removal bead for the `{decision.key}` flag, "
        "kept rather than removed. The behavior is permanent and belongs in a "
        "config field, not a feature flag: convert it, then close this bead. "
        f"Reviewer rationale: {decision.feedback}"
    )
    return submit_task_launch_task(
        decision.bead_id,
        project=decision.project,
        feedback=brief,
        origin=(
            origin
            if origin is not None
            else task_launch_origin_from_gate_source(decision.source)
        ),
    )


def close_flag_triage(decision: FlagTriageResponse) -> None:
    """Cancel the flag's removal bead using the CLI's locked commit semantics."""
    if decision.action != FLAG_TRIAGE_CLOSE_OPTION_ID or decision.feedback is None:
        raise GateError(
            "invalid_flag_action",
            decision.action,
            "flag triage close helper requires close with a reason",
        )
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import close_mutation_commit_message

    cwd = _resolve_flag_triage_project_cwd(decision.project)
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        mutation.project.close(
            [decision.bead_id],
            reason=decision.feedback,
            resolution="canceled",
        )
        outcome = mutation.project.last_mutation_outcome
        commit_message = close_mutation_commit_message(
            closed_ids=_outcome_ids(outcome, "closed_ids"),
            cascade_closed_ids=_outcome_ids(outcome, "cascade_closed_ids"),
            noted_ids=_outcome_ids(outcome, "noted_ids"),
        )
        if commit_message is not None:
            mutation.commit(commit_message)


def _resolve_flag_triage_project_cwd(project: str) -> Path:
    """Resolve a user-answered flag-triage gate to the primary checkout.

    Flag-triage gate actions apply an explicit user answer and commit with the
    default user mutation origin, so they are foreground user actions rather
    than background bead writers.
    """
    from sase.bead.task_launch import resolve_task_launch_cwd_for_project

    try:
        return resolve_task_launch_cwd_for_project(project)
    except (FileNotFoundError, ValueError) as exc:
        raise GateError(
            "invalid_flag_project",
            "payload.project",
            str(exc),
        ) from exc


def _outcome_ids(outcome: Mapping[str, Any], field: str) -> list[str]:
    raw = outcome.get(field)
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw]
