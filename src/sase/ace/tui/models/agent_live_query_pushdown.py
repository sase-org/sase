"""Pushdown compiler for the live Agents-tab query profile."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.query.profile_reference import parse_query_for_profile
from sase.ace.query.profile_reference_support import ProfileQueryError
from sase.ace.query.types import (
    AndExpr,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
)
from sase.project_display_names import project_display_name_map_signature

from .agent_live_query_engine import (
    agents_live_query_profile,
    augment_error_with_legacy_hint,
)

CandidateFilterWire = dict[str, object]

_PUSHABLE_TEXT_FIELDS = frozenset({"cl", "model"})
_PUSHABLE_EXACT_FIELDS = frozenset({"provider"})
_PUSHABLE_KIND_VALUES = {
    "agent": "agent",
    "workflow": "workflow",
}


@dataclass(frozen=True)
class _AgentsLiveQueryPushdownPlan:
    """Safe candidate-filter plan for one raw ``agents-live`` query string."""

    raw_query: str
    parsed_query: QueryExpr | None
    candidate_filter: CandidateFilterWire | None
    window_safe: bool
    unsupported_reason: str | None = None


def compile_agents_live_query_pushdown(
    raw_query: str | None,
) -> _AgentsLiveQueryPushdownPlan:
    """Return an exact indexed-candidate filter for ``agents-live`` when possible."""

    raw = (raw_query or "").strip()
    if not raw:
        return _AgentsLiveQueryPushdownPlan(
            raw_query="",
            parsed_query=None,
            candidate_filter=None,
            window_safe=True,
        )

    try:
        parsed = parse_query_for_profile(raw, agents_live_query_profile())
    except ProfileQueryError as exc:
        return _AgentsLiveQueryPushdownPlan(
            raw_query=raw,
            parsed_query=None,
            candidate_filter=None,
            window_safe=False,
            unsupported_reason=(
                f"parse_error:{augment_error_with_legacy_hint(str(exc), raw)}"
            ),
        )

    candidate_filter = _candidate_filter_for_expr(parsed)
    if candidate_filter is None:
        return _AgentsLiveQueryPushdownPlan(
            raw_query=raw,
            parsed_query=parsed,
            candidate_filter=None,
            window_safe=False,
            unsupported_reason="unsupported_query",
        )
    return _AgentsLiveQueryPushdownPlan(
        raw_query=raw,
        parsed_query=parsed,
        candidate_filter=candidate_filter,
        window_safe=True,
    )


def _candidate_filter_for_expr(expr: QueryExpr) -> CandidateFilterWire | None:
    if isinstance(expr, PropertyMatch):
        return _candidate_filter_for_property(expr)
    if isinstance(expr, AndExpr):
        filters = [_candidate_filter_for_expr(operand) for operand in expr.operands]
        if any(candidate is None for candidate in filters):
            return None
        return {"kind": "all", "filters": [f for f in filters if f is not None]}
    if isinstance(expr, OrExpr):
        filters = [_candidate_filter_for_expr(operand) for operand in expr.operands]
        if any(candidate is None for candidate in filters):
            return None
        return {"kind": "any", "filters": [f for f in filters if f is not None]}
    if isinstance(expr, NotExpr):
        inner = _candidate_filter_for_expr(expr.operand)
        if inner is None:
            return None
        return {"kind": "not", "filter": inner}
    if isinstance(expr, StringMatch):
        return None
    return None


def _candidate_filter_for_property(prop: PropertyMatch) -> CandidateFilterWire | None:
    if prop.key in _PUSHABLE_TEXT_FIELDS:
        return _contains(prop.key, prop.value)
    if prop.key in _PUSHABLE_EXACT_FIELDS:
        return _equals(prop.key, prop.value)
    if prop.key == "project":
        return _project_filter(prop.value)
    if prop.key == "kind":
        value = _PUSHABLE_KIND_VALUES.get(prop.value)
        if value is None:
            return None
        return _equals("type", value)
    return None


def _contains(field: str, value: str) -> CandidateFilterWire:
    return {"kind": "contains", "field": field, "value": value}


def _equals(field: str, value: str) -> CandidateFilterWire:
    return {"kind": "equals", "field": field, "value": value}


def _project_filter(value: str) -> CandidateFilterWire:
    filters: list[CandidateFilterWire] = []
    needle = value.casefold()
    seen: set[tuple[str, str]] = set()

    def add(project_key: str) -> None:
        key = ("equals", project_key)
        if key in seen:
            return
        seen.add(key)
        filters.append(_equals("project", project_key))

    add(value)
    for project_key, display_name in project_display_name_map_signature():
        if project_key.casefold() == needle or display_name.casefold() == needle:
            add(project_key)

    if len(filters) == 1:
        return filters[0]
    return {"kind": "any", "filters": filters}


__all__ = [
    "CandidateFilterWire",
    "compile_agents_live_query_pushdown",
]
