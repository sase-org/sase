"""Evaluator for the agent query language.

Lifts the Phase-1 AST (see :mod:`sase.ace.agent_query.types` /
:mod:`sase.ace.agent_query.parser`) into a per-:class:`Agent` predicate.

The evaluator is pure: no I/O, no global state, no TUI imports. The
caller supplies ``now`` (for ``age`` comparisons) and an optional
:class:`_ContentCache` (for searching prompt/reply content).
The :class:`Agent` import is ``TYPE_CHECKING``-only so this module
remains import-safe from a future ``sase agents search`` CLI.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .types import (
    AndExpr,
    DurationCompare,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
)

if TYPE_CHECKING:
    from ..tui.models.agent import Agent


class _ContentCache(Protocol):
    """Structural type for the content cache argument.

    Matches :class:`sase.ace.tui.models.agent_content_search._ContentCache`
    but kept as a Protocol so the evaluator stays import-decoupled from
    the TUI and tests can pass lightweight fakes.
    """

    def get_haystack(self, agent: Agent) -> str: ...


def _metadata_fields(agent: Agent) -> list[str]:
    """Return the metadata strings used by bare-string / ``text:`` matches."""
    out: list[str] = []
    for field in ("cl_name", "display_name", "agent_name", "status"):
        value = getattr(agent, field, "") or ""
        if value:
            out.append(value)
    return out


def _haystack_for(agent: Agent, content_cache: _ContentCache | None) -> str:
    """Return the lowercased text used for case-insensitive substring matches.

    Mirrors the legacy ``_matches()`` body in ``actions/agents/_loading.py``:
    metadata fields (``cl_name``, ``display_name``, ``agent_name``,
    ``status``) joined with the agent's cached prompt/reply content when
    a cache is supplied. All lowercased so the caller can do a single
    case-insensitive ``in`` test.
    """
    parts: list[str] = [v.lower() for v in _metadata_fields(agent)]
    if content_cache is not None:
        cached = content_cache.get_haystack(agent)
        if cached:
            parts.append(cached)
    return "\n".join(parts)


def _match_string(haystack: str, expr: StringMatch, agent: Agent) -> bool:
    """Substring test, honoring ``c"..."`` case-sensitive flag.

    Case-sensitive matches search metadata fields only — the
    :class:`_ContentCache` stores already-lowercased content,
    so it cannot be reused as a case-sensitive haystack. The Phase-3
    plan accepts this limitation; users who need case-sensitive content
    search can fall back to the case-insensitive form.
    """
    if expr.case_sensitive:
        sensitive_haystack = "\n".join(_metadata_fields(agent))
        return expr.value in sensitive_haystack
    return expr.value.lower() in haystack


def _project_basename(agent: Agent) -> str:
    """Return the basename of ``agent.project_file`` (no extension stripped)."""
    if not agent.project_file:
        return ""
    return Path(agent.project_file).parent.name


def _match_substring_property(prop: PropertyMatch, agent: Agent) -> bool:
    """Substring (case-insensitive) match for the substring-shaped keys."""
    needle = prop.value.lower()
    if prop.key == "status":
        return needle in (agent.status or "").lower()
    if prop.key == "cl":
        return needle in (agent.cl_name or "").lower()
    if prop.key == "project":
        return needle in _project_basename(agent).lower()
    if prop.key == "name":
        # agent_name first, fall back to display_name (the property table).
        if agent.agent_name and needle in agent.agent_name.lower():
            return True
        return needle in (agent.display_name or "").lower()
    if prop.key == "model":
        return needle in (agent.model or "").lower()
    if prop.key == "provider":
        return needle in (agent.llm_provider or "").lower()
    return False  # pragma: no cover — keys policed by tokenizer


def _match_tag(prop: PropertyMatch, agent: Agent) -> bool:
    """Exact (case-insensitive) tag match.

    ``tag:foo`` ⇔ ``agent.tag == "foo"``. Bare ``tag:`` (empty value) means
    "any tagged agent" — match any non-empty tag.
    """
    agent_tag = (agent.tag or "").lower()
    if not prop.value:
        return bool(agent_tag)
    return agent_tag == prop.value.lower()


def _match_bool_property(prop: PropertyMatch, agent: Agent) -> bool:
    """Match a boolean-shaped key (``pinned``/``hidden``/``attention``)."""
    from ..tui.models.agent_groups import _NEEDS_ATTENTION_STATUSES
    from ..tui.models.agent_pin import is_pinned

    want_true = prop.value == "true"
    if prop.key == "pinned":
        actual = is_pinned(agent)
    elif prop.key == "hidden":
        actual = bool(agent.hidden)
    elif prop.key == "attention":
        actual = (agent.status or "") in _NEEDS_ATTENTION_STATUSES
    else:
        return False  # pragma: no cover
    return actual is want_true


def _match_type(prop: PropertyMatch, agent: Agent) -> bool:
    """Match the ``type:`` enum (``workflow`` / ``run`` / ``running``)."""
    from ..tui.models.agent import AgentType

    if prop.value == "workflow":
        return agent.agent_type is AgentType.WORKFLOW
    # ``run`` and ``running`` both alias the RUNNING bucket.
    return agent.agent_type is AgentType.RUNNING


def _match_source(prop: PropertyMatch, agent: Agent) -> bool:
    """Match the ``source:`` enum (``axe`` / ``manual``)."""
    from ..tui.models.agent import agent_source

    return agent_source(agent) == prop.value


def _match_needs(prop: PropertyMatch, agent: Agent) -> bool:
    """Match the ``needs:`` enum (only ``input`` in Phase 1)."""
    from ..tui.models.agent_groups import _NEEDS_INPUT_STATUSES

    if prop.value != "input":
        return False  # pragma: no cover — tokenizer rejects other values
    return (agent.status or "") in _NEEDS_INPUT_STATUSES


def _match_text(prop: PropertyMatch, haystack: str) -> bool:
    """Match the ``text:`` key — equivalent to a bare-word substring match."""
    return prop.value.lower() in haystack


def _match_property(
    prop: PropertyMatch,
    agent: Agent,
    haystack: str,
) -> bool:
    """Dispatch a ``key:value`` match to the per-key helper."""
    key = prop.key
    if key in ("status", "cl", "project", "name", "model", "provider"):
        return _match_substring_property(prop, agent)
    if key == "tag":
        return _match_tag(prop, agent)
    if key in ("pinned", "hidden", "attention"):
        return _match_bool_property(prop, agent)
    if key == "type":
        return _match_type(prop, agent)
    if key == "source":
        return _match_source(prop, agent)
    if key == "needs":
        return _match_needs(prop, agent)
    if key == "text":
        return _match_text(prop, haystack)
    return False  # pragma: no cover — tokenizer policed


def _match_duration(expr: DurationCompare, agent: Agent, now: datetime) -> bool:
    """Compare ``now - agent.start_time`` against ``expr.seconds``.

    Returns ``False`` when ``start_time`` is missing — agents without a
    start time cannot be reasoned about for ``age`` comparisons.
    """
    if agent.start_time is None:
        return False
    if expr.key != "age":
        return False  # pragma: no cover — tokenizer only allows "age"
    elapsed = (now - agent.start_time).total_seconds()
    op = expr.op
    target = expr.seconds
    if op == "<":
        return elapsed < target
    if op == "<=":
        return elapsed <= target
    if op == ">":
        return elapsed > target
    if op == ">=":
        return elapsed >= target
    if op == "=":
        return elapsed == target
    return False  # pragma: no cover


def _evaluate(
    expr: QueryExpr,
    agent: Agent,
    haystack: str,
    now: datetime,
) -> bool:
    """Recursively evaluate *expr* against *agent*."""
    if isinstance(expr, StringMatch):
        return _match_string(haystack, expr, agent)
    if isinstance(expr, PropertyMatch):
        return _match_property(expr, agent, haystack)
    if isinstance(expr, DurationCompare):
        return _match_duration(expr, agent, now)
    if isinstance(expr, NotExpr):
        return not _evaluate(expr.operand, agent, haystack, now)
    if isinstance(expr, AndExpr):
        return all(_evaluate(op, agent, haystack, now) for op in expr.operands)
    if isinstance(expr, OrExpr):
        return any(_evaluate(op, agent, haystack, now) for op in expr.operands)
    raise TypeError(f"Unknown expression type: {type(expr)}")  # pragma: no cover


def evaluate_agent_query(
    expr: QueryExpr,
    agent: Agent,
    *,
    now: datetime,
    content_cache: _ContentCache | None = None,
) -> bool:
    """Return whether *agent* matches the parsed query *expr*.

    Args:
        expr: Parsed AST from :func:`parse_agent_query`.
        agent: The :class:`Agent` to test.
        now: Reference time for ``age>...`` comparisons. Required so
            tests can pin a deterministic clock and so the TUI can use a
            single render-frame clock across all agents.
        content_cache: Optional cache supplying lowercased prompt/reply
            text for bare-string and ``text:`` matches. ``None`` means
            metadata-only matching.

    Returns:
        ``True`` iff the agent matches.
    """
    haystack = _haystack_for(agent, content_cache)
    return _evaluate(expr, agent, haystack, now)
