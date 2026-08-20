"""Public facade for profile-driven Python reference query handling."""

from __future__ import annotations

from collections.abc import Iterable

from sase.ace.query.limit_token import LimitTokenError, extract_limit
from sase.ace.query.profile_evaluator import (
    ArtifactQueryEvaluationContext,
    ArtifactQueryRow,
    ArtifactQueryRowInput,
    ProfileFieldValue,
    build_query_context_for_profile,
    coerce_artifact_query_row,
    coerce_artifact_query_rows,
    evaluate_query_for_profile,
    evaluate_query_with_profile_context,
    patch_query_stable_id,
)
from sase.ace.query.profile_reference_boolean import parse_boolean_query
from sase.ace.query.profile_reference_flat import (
    canonical_flat_query,
    parse_flat_query,
)
from sase.ace.query.profile_reference_support import ProfileQueryError
from sase.ace.query.types import QueryExpr, to_canonical_string
from sase.ace.query_profile import CompiledQueryProfile


def parse_query_for_profile(query: str, profile: CompiledQueryProfile) -> QueryExpr:
    """Parse *query* using the syntax declared by *profile*.

    Host-owned ``limit:`` is stripped before dialect parse so it is never a
    row-matching :class:`~sase.ace.query.types.PropertyMatch`.
    """

    remainder = _membership_query(query)
    if profile.boolean:
        return parse_boolean_query(remainder, profile)
    return parse_flat_query(remainder, profile)


def evaluate_query_many_for_profile(
    query: str,
    entries: Iterable[ArtifactQueryRowInput],
    profile: CompiledQueryProfile,
) -> list[bool]:
    """Parse and evaluate *query* against every entry under *profile*."""

    expr = parse_query_for_profile(query, profile)
    ctx = build_query_context_for_profile(profile, entries)
    return [evaluate_query_for_profile(expr, row, profile) for row in ctx.rows]


def canonical_query_for_profile(query: str, profile: CompiledQueryProfile) -> str:
    """Return the canonical query for *profile*'s declared syntax.

    Host-owned ``limit:`` is omitted: it is a presentation cap, not a
    row-membership field, so cache keys and Rust programs see the remainder.
    """

    remainder = _membership_query(query)
    if not remainder.strip():
        return ""
    if profile.boolean:
        return to_canonical_string(parse_query_for_profile(remainder, profile))
    return canonical_flat_query(remainder, profile)


def _membership_query(query: str) -> str:
    try:
        remainder, _cap = extract_limit(query)
    except LimitTokenError as exc:
        raise ProfileQueryError(exc.message, exc.start) from exc
    return remainder


__all__ = [
    "ArtifactQueryEvaluationContext",
    "ArtifactQueryRow",
    "ArtifactQueryRowInput",
    "ProfileFieldValue",
    "ProfileQueryError",
    "build_query_context_for_profile",
    "canonical_query_for_profile",
    "coerce_artifact_query_row",
    "coerce_artifact_query_rows",
    "evaluate_query_for_profile",
    "evaluate_query_many_for_profile",
    "evaluate_query_with_profile_context",
    "patch_query_stable_id",
    "parse_query_for_profile",
]
