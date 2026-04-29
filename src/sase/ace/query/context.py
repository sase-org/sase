"""Cached, context-based query evaluation across a ChangeSpec list."""

from dataclasses import dataclass, field

from ..changespec import ChangeSpec, has_any_status_suffix
from .matchers import evaluate, get_base_status, match_property
from .searchable import (
    RUNNING_AGENT_MARKER,
    RUNNING_PROCESS_MARKER,
    get_searchable_text,
)
from .types import AndExpr, NotExpr, OrExpr, PropertyMatch, QueryExpr, StringMatch


@dataclass
class QueryEvaluationContext:
    """Per-list-version cache of ChangeSpec data used by query evaluation.

    Built once per ChangeSpec-list version via :func:`build_query_context`
    and reused across rows so filter/refresh work is O(N) total instead of
    O(N^2) (rebuilding name maps and searchable text once per row).
    """

    all_changespecs: list[ChangeSpec]
    name_map: dict[str, ChangeSpec] = field(default_factory=dict)
    status_map: dict[str, str] = field(default_factory=dict)
    searchable_text: dict[str, str] = field(default_factory=dict)
    searchable_lower: dict[str, str] = field(default_factory=dict)
    ancestor_memo: dict[tuple[str, str], bool] = field(default_factory=dict)


def build_query_context(
    changespecs: list[ChangeSpec],
) -> QueryEvaluationContext:
    """Build a :class:`QueryEvaluationContext` for the given ChangeSpec list.

    Public entry point — routes through :mod:`sase.core.query`. The default
    backend dispatches back to :func:`build_query_context_python` below.
    """
    from sase.core.query_facade import build_query_context as _facade

    return _facade(changespecs)


def build_query_context_python(
    changespecs: list[ChangeSpec],
) -> QueryEvaluationContext:
    """Python implementation of :func:`build_query_context`.

    Computes name and status maps eagerly (cheap, used by every row).
    Searchable text and ancestor results are filled lazily inside
    :func:`evaluate_query_with_context` so they are only paid for the rows
    actually evaluated.
    """
    name_map: dict[str, ChangeSpec] = {}
    status_map: dict[str, str] = {}
    for cs in changespecs:
        key = cs.name.lower()
        name_map[key] = cs
        status_map[key] = get_base_status(cs.status)
    return QueryEvaluationContext(
        all_changespecs=changespecs,
        name_map=name_map,
        status_map=status_map,
    )


def _ctx_searchable_text(ctx: QueryEvaluationContext, cs: ChangeSpec) -> str:
    key = cs.name.lower()
    text = ctx.searchable_text.get(key)
    if text is None:
        text = get_searchable_text(cs)
        ctx.searchable_text[key] = text
    return text


def _ctx_searchable_lower(ctx: QueryEvaluationContext, cs: ChangeSpec) -> str:
    key = cs.name.lower()
    lower = ctx.searchable_lower.get(key)
    if lower is None:
        lower = _ctx_searchable_text(ctx, cs).lower()
        ctx.searchable_lower[key] = lower
    return lower


def _ctx_match_string(
    ctx: QueryEvaluationContext, cs: ChangeSpec, match: StringMatch
) -> bool:
    if match.case_sensitive:
        return match.value in _ctx_searchable_text(ctx, cs)
    return match.value.lower() in _ctx_searchable_lower(ctx, cs)


def _ctx_match_ancestor(
    prop: PropertyMatch,
    cs: ChangeSpec,
    ctx: QueryEvaluationContext,
) -> bool:
    ancestor_value = prop.value.lower()
    memo = ctx.ancestor_memo
    name_map = ctx.name_map

    cache_key = (cs.name.lower(), ancestor_value)
    cached = memo.get(cache_key)
    if cached is not None:
        return cached

    visited: set[str] = set()
    current: ChangeSpec | None = cs
    found = False
    while current is not None:
        cs_name_lower = current.name.lower()
        if cs_name_lower in visited:
            break
        visited.add(cs_name_lower)

        memo_key = (cs_name_lower, ancestor_value)
        prior = memo.get(memo_key)
        if prior is not None:
            found = prior
            break

        if cs_name_lower == ancestor_value:
            found = True
            break

        if current.parent:
            parent_lower = current.parent.lower()
            if parent_lower == ancestor_value:
                found = True
                break
            current = name_map.get(parent_lower)
            continue
        break

    for v in visited:
        memo.setdefault((v, ancestor_value), found)
    return found


def _ctx_match_property(
    prop: PropertyMatch,
    cs: ChangeSpec,
    ctx: QueryEvaluationContext,
) -> bool:
    if prop.key == "ancestor":
        return _ctx_match_ancestor(prop, cs, ctx)
    return match_property(prop, cs, ctx.all_changespecs)


def _evaluate_with_context(
    expr: QueryExpr,
    cs: ChangeSpec,
    ctx: QueryEvaluationContext,
) -> bool:
    if isinstance(expr, StringMatch):
        if expr.is_error_suffix:
            return has_any_status_suffix(cs)
        text = _ctx_searchable_text(ctx, cs)
        if expr.is_running_agent:
            return RUNNING_AGENT_MARKER in text
        if expr.is_running_process:
            return RUNNING_PROCESS_MARKER in text
        return _ctx_match_string(ctx, cs, expr)
    elif isinstance(expr, PropertyMatch):
        return _ctx_match_property(expr, cs, ctx)
    elif isinstance(expr, NotExpr):
        return not _evaluate_with_context(expr.operand, cs, ctx)
    elif isinstance(expr, AndExpr):
        return all(_evaluate_with_context(op, cs, ctx) for op in expr.operands)
    elif isinstance(expr, OrExpr):
        return any(_evaluate_with_context(op, cs, ctx) for op in expr.operands)
    else:
        raise TypeError(f"Unknown expression type: {type(expr)}")


def evaluate_query_with_context(
    query: QueryExpr,
    changespec: ChangeSpec,
    ctx: QueryEvaluationContext,
) -> bool:
    """Evaluate ``query`` against ``changespec`` using a shared context.

    Public entry point — routes through :mod:`sase.core.query`. The default
    backend dispatches back to :func:`evaluate_query_with_context_python` below.
    """
    from sase.core.query_facade import evaluate_query_with_context as _facade

    return _facade(query, changespec, ctx)


def evaluate_query_with_context_python(
    query: QueryExpr,
    changespec: ChangeSpec,
    ctx: QueryEvaluationContext,
) -> bool:
    """Python implementation of :func:`evaluate_query_with_context`.

    Reuses the cached name map, status map, searchable text, and ancestor
    memo from ``ctx``.
    """
    return _evaluate_with_context(query, changespec, ctx)


def evaluate_query_python(
    query: QueryExpr,
    changespec: ChangeSpec,
    all_changespecs: list[ChangeSpec] | None = None,
) -> bool:
    """Python implementation of :func:`evaluate_query`.

    Args:
        query: The parsed query expression.
        changespec: The ChangeSpec to evaluate against.
        all_changespecs: List of all ChangeSpecs. Required for ancestor:
            property filter matching. If None, ancestor filters return False.

    Returns:
        True if the ChangeSpec matches the query, False otherwise.
    """
    searchable_text = get_searchable_text(changespec)
    return evaluate(query, searchable_text, changespec, all_changespecs)
