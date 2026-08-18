"""Host effects a human's BeadSnooze decision authorizes.

Each helper re-checks the action it was wired to, so an adapter pointed at the
wrong effect fails loudly instead of closing a bead the reviewer meant to
wake. Every mutation goes through the CLI's locked commit/push semantics
rather than touching a store directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.bead._snooze_gate_preview import bead_snooze_close_reason
from sase.bead._snooze_gate_response import BeadSnoozeResponse
from sase.bead._snooze_gate_spec import (
    BEAD_SNOOZE_CLOSE_OPTION_ID,
    BEAD_SNOOZE_READY_NOTE,
    BEAD_SNOOZE_READY_OPTION_ID,
    BEAD_SNOOZE_SNOOZE_OPTION_ID,
    BeadSnoozeAction,
)
from sase.bead.snooze_time import SnoozeTimeError, parse_snooze_request
from sase.bead.task_gate import bead_gate_actor
from sase.notification_gates.models import GateError


def close_bead_snooze(decision: BeadSnoozeResponse) -> None:
    """Close the woken task, defaulting to the preset stale-snooze reason."""
    _require_action(decision, BEAD_SNOOZE_CLOSE_OPTION_ID)
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import close_mutation_commit_message

    reason = decision.feedback or bead_snooze_close_reason(decision.snooze.until)
    cwd = _resolve_bead_snooze_project_cwd(decision.project)
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        mutation.project.close(
            [decision.bead_id],
            reason=reason,
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


def ready_bead_snooze(decision: BeadSnoozeResponse) -> None:
    """Return the woken task to triage, clearing its snooze record.

    The ``TaskTriage`` gate is deliberately not raised here: the bead task-gate
    reconciliation owns which gate a task bead has, and raising one directly
    would give the bead two.
    """
    _require_action(decision, BEAD_SNOOZE_READY_OPTION_ID)
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import require_mutation_commit_message

    cwd = _resolve_bead_snooze_project_cwd(decision.project)
    note = BEAD_SNOOZE_READY_NOTE
    if decision.feedback:
        note = f"{note} {decision.feedback}"
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        actor = bead_gate_actor(mutation.project)
        mutation.project.cancel_snooze(decision.bead_id, actor=actor)
        mutation.project.append_note(decision.bead_id, note, author=actor)
        mutation.commit(
            require_mutation_commit_message("snooze_cancel", [decision.bead_id])
        )


def resnooze_bead_snooze(decision: BeadSnoozeResponse) -> None:
    """Defer the woken task again, using the duration the reviewer declared.

    The wake time arrives as the command's own validated result, so the only
    way this parse fails is a forged response; the note, when there is one,
    replaces the reason the original deferral recorded.
    """
    _require_action(decision, BEAD_SNOOZE_SNOOZE_OPTION_ID)
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import require_mutation_commit_message

    try:
        request = parse_snooze_request(decision.duration or "")
    except SnoozeTimeError as exc:
        raise GateError("invalid_snooze_duration", "duration", str(exc)) from exc
    cwd = _resolve_bead_snooze_project_cwd(decision.project)
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        mutation.project.snooze(
            decision.bead_id,
            until=request.until,
            actor=bead_gate_actor(mutation.project),
            plus_ones=request.plus_ones,
            reason=decision.feedback or decision.snooze.reason,
        )
        mutation.commit(require_mutation_commit_message("snooze", [decision.bead_id]))


def _require_action(decision: BeadSnoozeResponse, action: BeadSnoozeAction) -> None:
    if decision.action != action:
        raise GateError(
            "invalid_task_action",
            decision.action,
            f"bead snooze {action} helper requires the {action} action",
        )


def _resolve_bead_snooze_project_cwd(project: str) -> Path:
    """Resolve a user-answered bead-snooze gate to the primary checkout.

    Snooze gate actions apply an explicit user answer and commit with the
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


def _outcome_ids(outcome: Mapping[str, Any], field: str) -> list[str]:
    raw = outcome.get(field)
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw]
