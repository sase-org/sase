"""Public facade for profile-driven Python reference query handling."""

from __future__ import annotations

from collections.abc import Iterable

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
    """Parse *query* using the syntax declared by *profile*."""

    if profile.boolean:
        return parse_boolean_query(query, profile)
    return parse_flat_query(query, profile)


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
    """Return the canonical query for *profile*'s declared syntax."""

    if profile.boolean:
        return to_canonical_string(parse_query_for_profile(query, profile))
    return canonical_flat_query(query, profile)


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
