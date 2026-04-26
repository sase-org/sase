"""Query language for filtering Agents on the agents tab.

This package provides a structured query language that parallels
:mod:`sase.ace.query` (used for ChangeSpecs) but with a closed property-key
allowlist appropriate for ``Agent`` objects, plus an ``age`` comparison
operator family.

Phase 1 ships only the syntax layer (types, tokenizer, parser); semantics
live in :mod:`sase.ace.agent_query.evaluator` (Phase 2) and TUI wiring lives
in :mod:`sase.ace.tui.actions.agents._loading` (Phase 3).
"""

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
    "AgentQueryParseError",
    "AndExpr",
    "DurationCompare",
    "NotExpr",
    "OrExpr",
    "PropertyMatch",
    "QueryExpr",
    "StringMatch",
    "parse_agent_query",
    "to_canonical_string",
]
