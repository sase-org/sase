"""Host effects a human's TaskTriage decision authorizes.

Each helper re-checks the action it implements, so an adapter that routes a
decision to the wrong effect fails loudly instead of launching a bead someone
asked to close. Every mutation goes through the CLI's locked
commit/push semantics rather than touching a store directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead._task_gate_response import TaskTriageResponse
from sase.bead._task_gate_spec import (
    TASK_TRIAGE_CLOSE_OPTION_ID,
    TASK_TRIAGE_KIND,
    TASK_TRIAGE_LAUNCH_OPTION_ID,
    TASK_TRIAGE_SNOOZE_OPTION_ID,
    TASK_TRIAGE_SNOOZE_REASON,
)
from sase.notification_gates.models import GateError

if TYPE_CHECKING:
    from sase.bead.task_launch import TaskLaunchOrigin
    from sase.procs.models import Proc


def cancel_task_triage(
    project: str,
    bead_id: str,
    *,
    reason: str,
    source: str = "ace",
) -> bool:
    """Cancel a pending task triage and settle its notification."""
    request_id = _find_pending_task_triage(project, bead_id)
    if request_id is None:
        return False
    from sase.notification_gates.executor import cancel_gate
    from sase.notification_gates.paths import bundle_paths

    try:
        cancel_gate(
            bundle_paths(TASK_TRIAGE_KIND, request_id).root,
            reason=reason,
            source=source,
        )
    except GateError as exc:
        if exc.code == "already_answered":
            return False
        raise
    return True


def launch_task_triage(
    decision: TaskTriageResponse,
    *,
    origin: TaskLaunchOrigin | None = None,
) -> Proc:
    """Submit or reuse the detached task launch selected by a human."""
    if decision.action != TASK_TRIAGE_LAUNCH_OPTION_ID:
        raise GateError(
            "invalid_task_action",
            decision.action,
            "task triage launch helper requires the launch action",
        )
    from sase.bead.task_launch import (
        submit_task_launch_task,
        task_launch_origin_from_gate_source,
    )

    return submit_task_launch_task(
        decision.bead_id,
        project=decision.project,
        feedback=decision.feedback,
        origin=(
            origin
            if origin is not None
            else task_launch_origin_from_gate_source(decision.source)
        ),
    )


def close_task_triage(decision: TaskTriageResponse) -> None:
    """Cancel the selected task using the CLI's locked commit/push semantics."""
    if decision.action != TASK_TRIAGE_CLOSE_OPTION_ID or decision.feedback is None:
        raise GateError(
            "invalid_task_action",
            decision.action,
            "task triage close helper requires close with a reason",
        )
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import close_mutation_commit_message

    cwd = _resolve_task_triage_project_cwd(decision.project)
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


def snooze_task_triage(decision: TaskTriageResponse) -> None:
    """Defer the triaged task, using the duration and +1 target a human chose.

    The wake time arrives as the command's own validated result, so the only
    way this parse fails is a forged response; the note, when there is one,
    records why the task was deferred.

    The ``BeadSnooze`` gate is deliberately not raised here: the bead task-gate
    reconciliation owns which gate a task bead has, and raising one directly
    would give the bead two.
    """
    if decision.action != TASK_TRIAGE_SNOOZE_OPTION_ID or decision.duration is None:
        raise GateError(
            "invalid_task_action",
            decision.action,
            "task triage snooze helper requires snooze with a wake time",
        )
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import require_mutation_commit_message
    from sase.bead.snooze_time import SnoozeTimeError, parse_snooze_request

    try:
        request = parse_snooze_request(decision.duration)
    except SnoozeTimeError as exc:
        raise GateError("invalid_snooze_duration", "duration", str(exc)) from exc
    cwd = _resolve_task_triage_project_cwd(decision.project)
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        mutation.project.snooze(
            decision.bead_id,
            until=request.until,
            actor=bead_gate_actor(mutation.project),
            plus_ones=request.plus_ones,
            reason=decision.feedback or TASK_TRIAGE_SNOOZE_REASON,
        )
        mutation.commit(require_mutation_commit_message("snooze", [decision.bead_id]))


def bead_gate_actor(project: Any) -> str:
    """Attribute a bead gate's mutation to the answerer, else the store owner."""
    from sase.agent.identity import discover_agent_identity

    identity = discover_agent_identity()
    return identity.name if identity is not None else str(project.owner)


def _resolve_task_triage_project_cwd(project: str) -> Path:
    """Resolve a user-answered task-triage gate to the primary checkout.

    Task-triage gate actions apply an explicit user answer and commit with the
    default user mutation origin, so they are foreground user actions rather
    than background bead writers.
    """
    from sase.bead.task_launch import resolve_task_launch_cwd_for_project

    try:
        return resolve_task_launch_cwd_for_project(project)
    except (FileNotFoundError, ValueError) as exc:
        raise GateError(
            "invalid_task_project",
            "payload.project",
            str(exc),
        ) from exc


def _find_pending_task_triage(project: str, bead_id: str) -> str | None:
    """Return the pending TaskTriage request matching trusted payload fields."""
    from sase.bead.gate_lookup import find_pending_bead_gates

    for gate in find_pending_bead_gates((TASK_TRIAGE_KIND,)):
        if gate.project == project and gate.bead_id == bead_id:
            return gate.request_id
    return None


def _outcome_ids(outcome: Mapping[str, Any], field: str) -> list[str]:
    raw = outcome.get(field)
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw]
