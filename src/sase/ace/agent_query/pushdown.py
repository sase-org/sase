"""Compile safe Agents-tab query predicates for artifact-index candidates."""

from __future__ import annotations

from dataclasses import dataclass

from sase.project_display_names import project_display_name_map_signature

from .parser import AgentQueryParseError, parse_agent_query
from .types import AndExpr, NotExpr, OrExpr, PropertyMatch, QueryExpr

CandidateFilterWire = dict[str, object]


@dataclass(frozen=True)
class AgentQueryPushdownPlan:
    """Safe candidate-filter plan for a raw Agents-tab query string."""

    raw_query: str
    parsed_query: QueryExpr | None
    candidate_filter: CandidateFilterWire | None
    window_safe: bool
    unsupported_reason: str | None = None


def compile_agent_query_pushdown(raw_query: str | None) -> AgentQueryPushdownPlan:
    """Return an exact indexed-candidate filter for *raw_query* when possible."""

    raw = (raw_query or "").strip()
    if not raw:
        return AgentQueryPushdownPlan(
            raw_query="",
            parsed_query=None,
            candidate_filter=None,
            window_safe=True,
        )
    try:
        parsed = parse_agent_query(raw)
    except AgentQueryParseError as exc:
        return AgentQueryPushdownPlan(
            raw_query=raw,
            parsed_query=None,
            candidate_filter=None,
            window_safe=False,
            unsupported_reason=f"parse_error:{exc}",
        )

    candidate_filter = _candidate_filter_for_expr(parsed)
    if candidate_filter is None:
        return AgentQueryPushdownPlan(
            raw_query=raw,
            parsed_query=parsed,
            candidate_filter=None,
            window_safe=False,
            unsupported_reason="unsupported_query",
        )
    return AgentQueryPushdownPlan(
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
    return None


def _candidate_filter_for_property(prop: PropertyMatch) -> CandidateFilterWire | None:
    if prop.key == "cl":
        return _contains("cl", prop.value)
    if prop.key == "model":
        return _contains("model", prop.value)
    if prop.key == "provider":
        return _contains("provider", prop.value)
    if prop.key == "project":
        return _project_filter(prop.value)
    if prop.key == "type":
        value = "workflow" if prop.value == "workflow" else "agent"
        return {"kind": "equals", "field": "type", "value": value}
    return None


def _contains(field: str, value: str) -> CandidateFilterWire:
    return {"kind": "contains", "field": field, "value": value}


def _project_filter(value: str) -> CandidateFilterWire:
    filters: list[CandidateFilterWire] = [_contains("project", value)]
    needle = value.casefold()
    for project_key, display_name in project_display_name_map_signature():
        if needle in display_name.casefold():
            filters.append({"kind": "equals", "field": "project", "value": project_key})
    if len(filters) == 1:
        return filters[0]
    return {"kind": "any", "filters": filters}


__all__ = [
    "AgentQueryPushdownPlan",
    "CandidateFilterWire",
    "compile_agent_query_pushdown",
]
