"""Cached, context-based query evaluation across a Patch list."""

from dataclasses import dataclass, field

from ..patch import Patch, has_any_status_suffix
from .matchers import evaluate, get_base_status, match_property
from .searchable import (
    RUNNING_AGENT_MARKER,
    RUNNING_PROCESS_MARKER,
    get_searchable_text,
)
from .types import AndExpr, NotExpr, OrExpr, PropertyMatch, QueryExpr, StringMatch


@dataclass
class QueryEvaluationContext:
    """Per-list-version cache of Patch data used by query evaluation.

    Built once per Patch-list version via :func:`build_query_context`
    and reused across rows so filter/refresh work is O(N) total instead of
    O(N^2) (rebuilding name maps and searchable text once per row).
    """

    all_patches: list[Patch]
    name_map: dict[str, Patch] = field(default_factory=dict)
    status_map: dict[str, str] = field(default_factory=dict)
    searchable_text: dict[str, str] = field(default_factory=dict)
    searchable_lower: dict[str, str] = field(default_factory=dict)
    ancestor_memo: dict[tuple[str, str], bool] = field(default_factory=dict)


def build_query_context(
    patches: list[Patch],
) -> QueryEvaluationContext:
    """Build a :class:`QueryEvaluationContext` for the given Patch list.

    Public entry point — routes through :mod:`sase.core.query`. The default
    backend dispatches back to :func:`build_query_context_python` below.
    """
    from sase.core.query_facade import build_query_context as _facade

    return _facade(patches)


def build_query_context_python(
    patches: list[Patch],
) -> QueryEvaluationContext:
    """Python implementation of :func:`build_query_context`.

    Computes name and status maps eagerly (cheap, used by every row).
    Searchable text and ancestor results are filled lazily inside
    :func:`evaluate_query_with_context` so they are only paid for the rows
    actually evaluated.
    """
    name_map: dict[str, Patch] = {}
    status_map: dict[str, str] = {}
    for cs in patches:
        key = cs.name.lower()
        name_map[key] = cs
        status_map[key] = get_base_status(cs.status)
    return QueryEvaluationContext(
        all_patches=patches,
        name_map=name_map,
        status_map=status_map,
    )


def _ctx_searchable_text(ctx: QueryEvaluationContext, cs: Patch) -> str:
    key = cs.name.lower()
    text = ctx.searchable_text.get(key)
    if text is None:
        text = get_searchable_text(cs)
        ctx.searchable_text[key] = text
    return text


def _ctx_searchable_lower(ctx: QueryEvaluationContext, cs: Patch) -> str:
    key = cs.name.lower()
    lower = ctx.searchable_lower.get(key)
    if lower is None:
        lower = _ctx_searchable_text(ctx, cs).lower()
        ctx.searchable_lower[key] = lower
    return lower


def _ctx_match_string(
    ctx: QueryEvaluationContext, cs: Patch, match: StringMatch
) -> bool:
    if match.case_sensitive:
        return match.value in _ctx_searchable_text(ctx, cs)
    return match.value.lower() in _ctx_searchable_lower(ctx, cs)


def _ctx_match_ancestor(
    prop: PropertyMatch,
    cs: Patch,
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
    current: Patch | None = cs
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
    cs: Patch,
    ctx: QueryEvaluationContext,
) -> bool:
    if prop.key == "ancestor":
        return _ctx_match_ancestor(prop, cs, ctx)
    return match_property(prop, cs, ctx.all_patches)


def _evaluate_with_context(
    expr: QueryExpr,
    cs: Patch,
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
    patch: Patch,
    ctx: QueryEvaluationContext,
) -> bool:
    """Evaluate ``query`` against ``patch`` using a shared context.

    Public entry point — routes through :mod:`sase.core.query`. The default
    backend dispatches back to :func:`evaluate_query_with_context_python` below.
    """
    from sase.core.query_facade import evaluate_query_with_context as _facade

    return _facade(query, patch, ctx)


def evaluate_query_with_context_python(
    query: QueryExpr,
    patch: Patch,
    ctx: QueryEvaluationContext,
) -> bool:
    """Python implementation of :func:`evaluate_query_with_context`.

    Reuses the cached name map, status map, searchable text, and ancestor
    memo from ``ctx``.
    """
    return _evaluate_with_context(query, patch, ctx)


def evaluate_query_python(
    query: QueryExpr,
    patch: Patch,
    all_patches: list[Patch] | None = None,
) -> bool:
    """Python implementation of :func:`evaluate_query`.

    Args:
        query: The parsed query expression.
        patch: The Patch to evaluate against.
        all_patches: List of all Patches. Required for ancestor:
            property filter matching. If None, ancestor filters return False.

    Returns:
        True if the Patch matches the query, False otherwise.
    """
    searchable_text = get_searchable_text(patch)
    return evaluate(query, searchable_text, patch, all_patches)
