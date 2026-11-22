"""Failure causes derived from the already-loaded Agents tab model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sase.agent.status_buckets import agent_status_bucket

if TYPE_CHECKING:
    from .agent import Agent


@dataclass(frozen=True, slots=True)
class _FailureRowFocus:
    """The failed turn selected as a session or clan's failure frontier."""

    name: str
    stop_time: datetime | None


@dataclass(frozen=True, slots=True)
class _NotAdoptedHandoffFocus:
    """A held monitor proposal and the starter accepted by ``readopt``."""

    name: str
    kind: str
    starter_name: str | None


@dataclass(frozen=True, slots=True)
class FailureFocus:
    """Compact, render-ready causes attached to failed model rows."""

    member_label: str | None
    failed_row: _FailureRowFocus
    finalizer_chip: str | None
    not_adopted: _NotAdoptedHandoffFocus | None
    blocked: tuple[str, ...] = ()
    extra_failed: int = 0


def failure_focus_for_agent(
    agent: Agent,
    *,
    member_label: str | None = None,
    blocked: tuple[str, ...] = (),
    extra_failed: int | None = None,
) -> FailureFocus | None:
    """Build failure context from one failed row and its loaded descendants.

    This is a pure projection: the only inputs are the Agent objects already
    in memory. In particular, renderers do not need to open artifact files to
    discover finalizer or staged-handoff causes.
    """
    from ._agent_status_agent_session import child_launch_time
    from .agent_session_members import row_is_not_adopted_handoff
    from .finalizer_row_state import glance_finalizer_state

    descendants = _descendants(agent)
    failed_rows = [
        row
        for row in descendants
        if agent_status_bucket(row) == "Failed"
        and row.retried_as_timestamp is None
        and not row_is_not_adopted_handoff(row)
    ]
    if not failed_rows and agent_status_bucket(agent) == "Failed":
        failed_rows = [agent]
    if not failed_rows:
        return None

    failed_row = max(failed_rows, key=child_launch_time)
    finalizer_chip = glance_finalizer_state(failed_row).chip_text

    held_rows = [row for row in descendants if row_is_not_adopted_handoff(row)]
    held_row = max(held_rows, key=child_launch_time) if held_rows else None
    not_adopted = None
    if held_row is not None:
        by_suffix = {
            row.raw_suffix: row for row in (agent, *descendants) if row.raw_suffix
        }
        starter = by_suffix.get(held_row.parent_timestamp or "")
        not_adopted = _NotAdoptedHandoffFocus(
            name=_row_name(held_row),
            kind=(
                "monitor"
                if held_row.is_monitor
                else "gate"
                if held_row.is_gate
                else "agent"
            ),
            starter_name=_row_name(starter) if starter is not None else None,
        )

    return FailureFocus(
        member_label=member_label,
        failed_row=_FailureRowFocus(
            name=_row_name(failed_row),
            stop_time=failed_row.stop_time,
        ),
        finalizer_chip=finalizer_chip,
        not_adopted=not_adopted,
        blocked=blocked,
        extra_failed=(len(failed_rows) - 1 if extra_failed is None else extra_failed),
    )


def _descendants(agent: Agent) -> tuple[Agent, ...]:
    rows: list[Agent] = []
    seen_ids: set[int] = set()
    seen_identities: set[tuple[object, str, str | None]] = set()
    pending = list(reversed((*agent.runtime_children, *agent.followup_agents)))
    while pending:
        row = pending.pop()
        if id(row) in seen_ids or row.identity in seen_identities:
            continue
        seen_ids.add(id(row))
        seen_identities.add(row.identity)
        rows.append(row)
        pending.extend(reversed((*row.runtime_children, *row.followup_agents)))
    return tuple(rows)


def _row_name(agent: Agent) -> str:
    return agent.presented_agent_name or agent.agent_name or agent.display_name


__all__ = [
    "FailureFocus",
    "failure_focus_for_agent",
]
