"""Query language for filtering Agents on the agents tab.

This package provides a structured query language that parallels
:mod:`sase.ace.query` (used for ChangeSpecs) but with a closed property-key
allowlist appropriate for ``Agent`` objects, plus an ``age`` comparison
operator family.

Phase 1 ships the syntax layer (types, tokenizer, parser); Phase 2 adds
the :func:`evaluate_agent_query` semantics layer; Phase 3 wires it into
:mod:`sase.ace.tui.actions.agents._loading`.
"""

from .evaluator import evaluate_agent_query
from .highlighting import (
    AGENT_QUERY_TOKEN_STYLES,
    tokenize_agent_query_for_display,
)
from .parser import AgentQueryParseError, parse_agent_query
from .types import (
    AndExpr,
    DurationCompare,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
    to_canonical_string,
)

__all__ = [
    "AGENT_QUERY_TOKEN_STYLES",
    "AgentQueryParseError",
    "AndExpr",
    "DurationCompare",
    "NotExpr",
    "OrExpr",
    "PropertyMatch",
    "QueryExpr",
    "StringMatch",
    "evaluate_agent_query",
    "parse_agent_query",
    "to_canonical_string",
    "tokenize_agent_query_for_display",
]
