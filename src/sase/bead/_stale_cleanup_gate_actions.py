"""Host effects a human's BeadStaleCleanup decision authorizes.

The gate offers only one action, so the check this module re-runs is that a
decision names at least one selected bead rather than an action id — an
adapter wired to the wrong effect still fails loudly instead of closing
nothing silently. Every mutation goes through the CLI's locked commit/push
semantics rather than touching a store directly, one commit per project.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.bead._stale_cleanup_gate_response import BeadStaleCleanupResponse
from sase.bead._stale_cleanup_gate_spec import BEAD_STALE_CLEANUP_CLOSE_REASON
from sase.notification_gates.models import GateError


def close_bead_stale_cleanup(decision: BeadStaleCleanupResponse) -> None:
    """Close the reviewer-selected stale beads, grouped per project.

    Projects are processed in sorted order so a partial failure is
    deterministic: a project whose mutation raises leaves the already
    committed projects closed and propagates the error. Closing never
    cascades, so a bead with an unclosed descendant is refused by the store
    rather than forced through.
    """
    if not decision.beads:
        raise GateError(
            "invalid_stale_cleanup_action",
            "beads",
            "bead stale cleanup close helper requires at least one selected bead",
        )
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import close_mutation_commit_message

    reason = decision.feedback or BEAD_STALE_CLEANUP_CLOSE_REASON
    by_project: dict[str, list[str]] = {}
    for project, bead_id in decision.beads:
        by_project.setdefault(project, []).append(bead_id)

    for project in sorted(by_project):
        bead_ids = by_project[project]
        cwd = _resolve_stale_cleanup_project_cwd(project)
        with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
            mutation.project.close(bead_ids, reason=reason, resolution="canceled")
            outcome = mutation.project.last_mutation_outcome
            commit_message = close_mutation_commit_message(
                closed_ids=_outcome_ids(outcome, "closed_ids"),
                cascade_closed_ids=_outcome_ids(outcome, "cascade_closed_ids"),
                noted_ids=_outcome_ids(outcome, "noted_ids"),
            )
            if commit_message is not None:
                mutation.commit(commit_message)


def _resolve_stale_cleanup_project_cwd(project: str) -> Path:
    """Resolve a stale-cleanup project key to its primary checkout.

    Stale-cleanup gate actions apply an explicit user answer and commit with
    the default user mutation origin, so they are foreground user actions
    rather than background bead writers.
    """
    from sase.bead.task_launch import resolve_task_launch_cwd_for_project

    try:
        return resolve_task_launch_cwd_for_project(project)
    except (FileNotFoundError, ValueError) as exc:
        raise GateError(
            "invalid_stale_cleanup_project",
            "payload.project",
            str(exc),
        ) from exc


def _outcome_ids(outcome: Mapping[str, Any], field: str) -> list[str]:
    raw = outcome.get(field)
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw]
