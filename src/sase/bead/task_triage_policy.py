"""The shared suppression and staleness predicates for task-bead gate triage.

A ready task bead earns a `TaskTriage` gate only once independent reporters
have corroborated it with at least its effective `+1` bar (see the epic
plan's "Why" for the noise this bar removes): a typed bead uses its task
type's own `triage.min_plus_ones`, and an untyped bead -- or one whose type
this machine does not have registered -- falls back to the configured
`bead.task_triage.min_plus_ones`, resolved through
:func:`effective_min_plus_ones`. Every surface that decides whether a ready
task bead is withheld from triage, or whether a withheld bead is old enough
to sweep, derives it through :func:`task_gate_suppressed` and
:func:`stale_task_bead` rather than recompute the comparison itself --
mirroring :mod:`sase.bead.flag_due`.

All three are pure functions of their arguments: callers own the clock, the
registry, and the configured threshold, so no test needs to freeze time
globally and no consumer can disagree with another about what "suppressed"
or "stale" means.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.bead.model import Issue, IssueType, Status
from sase.task_types.registry import TaskTypeRegistry


def effective_min_plus_ones(
    issue: Issue, *, registry: TaskTypeRegistry, global_default: int
) -> int:
    """The +1 bar *issue* needs: its task type's own bar, else *global_default*.

    A task bead with a `task_type` known to *registry* uses that type's
    `triage.min_plus_ones` (spec default `0`). An untyped bead, or one whose
    type this machine does not have registered, uses *global_default* --
    the configured `bead.task_triage.min_plus_ones`.
    """
    task_type = issue.task_type
    record = registry.by_slug.get(task_type) if task_type else None
    if record is None:
        return global_default
    return record.min_plus_ones


def task_gate_suppressed(issue: Issue, *, min_plus_ones: int) -> bool:
    """Whether a ready task bead is withheld from triage for want of +1 reports."""
    return (
        issue.issue_type == IssueType.TASK
        and issue.status == Status.READY
        and issue.plus_one_count < min_plus_ones
    )


def stale_task_bead(
    issue: Issue, *, min_plus_ones: int, stale_after_days: int, now: datetime
) -> bool:
    """Whether a suppressed ready task bead has sat below the bar long enough to sweep."""
    if not task_gate_suppressed(issue, min_plus_ones=min_plus_ones):
        return False
    created_at = _parse_created_at(issue.created_at)
    if created_at is None:
        return False
    return created_at <= now - timedelta(days=stale_after_days)


def _parse_created_at(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


__all__ = [
    "effective_min_plus_ones",
    "stale_task_bead",
    "task_gate_suppressed",
]
