"""In-memory scoping of question-gate rows for the questions summary lane.

Everything here is pure and does zero I/O: it walks the already-loaded
agent session roster to find ``gate_kind == "question"`` rows, mirroring
:func:`concrete_agent_session_turn_rows
<sase.ace.tui.models.agent_session_members.concrete_agent_session_turn_rows>`
so the lane resolver and the first-paint stubs agree on scope. Disk reads
(question bundles) happen later, on the lane worker, through
:func:`load_question_round
<sase.question_gate_turn.projection.load_question_round>`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .agent import Agent
from .agent_session_members import (
    agent_session_roster_container,
    concrete_agent_session_turn_rows,
)

#: Defensive cap on in-scope question rounds. A session cannot ask this many
#: question rounds in practice; the cap keeps a corrupt roster from pinning
#: the lane worker. When exceeded, the newest rounds win.
_QUESTION_ROUND_SCOPE_LIMIT = 50


@dataclass(frozen=True)
class QuestionRoundStub:
    """Zero-I/O first-paint data for one in-scope question round."""

    gate_id: str
    member_label: str
    gate_state: str | None
    gate_label: str | None
    asked_at_unix: float | None
    deadline_unix: float | None


def question_member_label(row: Agent) -> str:
    """Return the gate member suffix (``gate``, ``gate-0``, ...) for a row."""
    role_suffix = row.role_suffix or ""
    stripped = role_suffix.lstrip("-")
    if stripped:
        return stripped
    name = row.agent_name or row.cl_name or ""
    if "--" in name:
        candidate = name.rsplit("--", 1)[-1].lstrip("-")
        if candidate:
            return candidate
    return name or "gate"


def _asked_at_unix(row: Agent) -> float | None:
    start = row.run_start_time or row.start_time
    if start is None:
        return None
    return start.timestamp()


def _deadline_unix(row: Agent) -> float | None:
    if row.gate_timeout_seconds is None:
        return None
    asked_at = _asked_at_unix(row)
    if asked_at is None:
        return None
    return asked_at + row.gate_timeout_seconds


def _is_question_gate_row(row: Agent) -> bool:
    return bool(row.is_gate and row.gate_kind == "question")


def _walk_own_turns(agent: Agent) -> tuple[Agent, ...]:
    """Return ``agent`` plus its turn descendants in causal order.

    Fallback for rows with no session container: a depth-first walk over the
    already-loaded ``runtime_children`` / ``followup_agents`` links,
    cycle-guarded on object identity and deduped on row identity.
    """
    ordered: list[Agent] = []
    seen_identities: set[object] = set()
    visited_ids: set[int] = set()

    def visit(row: Agent) -> None:
        if id(row) in visited_ids:
            return
        visited_ids.add(id(row))
        if row.identity not in seen_identities:
            seen_identities.add(row.identity)
            ordered.append(row)
        for child in (*row.runtime_children, *row.followup_agents):
            visit(child)

    visit(agent)
    return tuple(ordered)


def session_question_gate_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return every question gate row of ``agent``'s session, in causal order.

    The session container is the row itself for container rows, else the
    roster container, else (a row with no container) the row's own subtree.
    Rows dedupe by ``gate_id`` (falling back to row identity) and cap at
    :data:`_QUESTION_ROUND_SCOPE_LIMIT`, keeping the newest.
    """
    if agent.is_agent_session_container_row:
        container: Agent | None = agent
    else:
        container = agent_session_roster_container(agent)
    if container is not None:
        candidates = concrete_agent_session_turn_rows(container)
    else:
        candidates = _walk_own_turns(agent)
    rows = [row for row in candidates if _is_question_gate_row(row)]
    deduped: list[Agent] = []
    seen_gate_ids: set[str] = set()
    seen_identities: set[object] = set()
    for row in rows:
        gate_id = row.gate_id
        if gate_id:
            if gate_id in seen_gate_ids:
                continue
            seen_gate_ids.add(gate_id)
        elif row.identity in seen_identities:
            continue
        seen_identities.add(row.identity)
        deduped.append(row)
    if len(deduped) > _QUESTION_ROUND_SCOPE_LIMIT:
        deduped = deduped[-_QUESTION_ROUND_SCOPE_LIMIT:]
    return tuple(deduped)


def question_rows_in_scope(agent: Agent) -> tuple[Agent, ...]:
    """Return the session question rows visible from ``agent``'s selection.

    A container sees every session question row; a question gate row sees
    itself; any other turn sees the rows it asked (matching
    ``gate_creator_agent``) or that nest directly under its
    ``runtime_children``. Session causal order is preserved.
    """
    session_rows = session_question_gate_rows(agent)
    if agent.is_agent_session_container_row:
        return session_rows
    if _is_question_gate_row(agent):
        for row in session_rows:
            if row.identity == agent.identity:
                return (row,)
        return (agent,)
    name = agent.agent_name
    child_identities = {child.identity for child in agent.runtime_children}
    child_ids = {id(child) for child in agent.runtime_children}
    return tuple(
        row
        for row in session_rows
        if (name is not None and row.gate_creator_agent == name)
        or row.identity in child_identities
        or id(row) in child_ids
    )


def question_round_stubs(agent: Agent) -> tuple[QuestionRoundStub, ...]:
    """Return first-paint stubs for every in-scope question round.

    Zero I/O: every field comes from the already-loaded row.
    """
    return tuple(
        QuestionRoundStub(
            gate_id=row.gate_id or "",
            member_label=question_member_label(row),
            gate_state=row.gate_state,
            gate_label=row.gate_label,
            asked_at_unix=_asked_at_unix(row),
            deadline_unix=_deadline_unix(row),
        )
        for row in question_rows_in_scope(agent)
    )


def questions_cache_key(agent: Agent) -> tuple[tuple[str, str | None], ...]:
    """Return the invalidation key for ``agent``'s session question rows.

    One ``(gate_id, gate_state)`` pair per session question row. A settling
    answer rewrites the row with a new ``gate_state``, so the next
    revalidation notices the mismatch through the existing refresh path.
    """
    return tuple(
        (row.gate_id or repr(row.identity), row.gate_state)
        for row in session_question_gate_rows(agent)
    )


__all__ = [
    "QuestionRoundStub",
    "question_member_label",
    "question_round_stubs",
    "question_rows_in_scope",
    "questions_cache_key",
    "session_question_gate_rows",
]
