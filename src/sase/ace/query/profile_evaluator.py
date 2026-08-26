"""Profile-driven Artifact row coercion and evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sase.ace.query.profile_evaluator_matching import evaluate_expr
from sase.ace.query.profile_evaluator_patch import (
    coerce_patch_query_row,
    coerce_patch_query_row_with_wire,
    is_patch_row,
    patch_ancestor_chain,
    patch_parent_name,
    patch_query_stable_id,
)
from sase.ace.query.profile_evaluator_support import (
    artifact_query_row_wire,
    build_generic_query_row,
    build_generic_query_row_with_wire,
    coerce_date_value,
)
from sase.ace.query.profile_evaluator_types import (
    ArtifactQueryEvaluationContext,
    ArtifactQueryRow,
    ArtifactQueryRowInput,
    ProfileFieldValue,
)
from sase.ace.query.types import QueryExpr
from sase.ace.query_profile import CompiledQueryProfile

__all__ = [
    "ArtifactQueryEvaluationContext",
    "ArtifactQueryRow",
    "ArtifactQueryRowInput",
    "ProfileFieldValue",
    "build_query_context_for_profile",
    "coerce_artifact_query_date_value",
    "coerce_artifact_query_row",
    "coerce_artifact_query_rows",
    "coerce_artifact_query_rows_with_wire",
    "evaluate_query_for_profile",
    "evaluate_query_with_profile_context",
    "patch_query_stable_id",
]


def build_query_context_for_profile(
    profile: CompiledQueryProfile,
    entries: Iterable[ArtifactQueryRowInput],
) -> ArtifactQueryEvaluationContext:
    """Build a typed row context for *entries* under *profile*."""

    return ArtifactQueryEvaluationContext(
        profile=profile,
        rows=coerce_artifact_query_rows(profile, entries),
    )


def evaluate_query_with_profile_context(
    query: QueryExpr,
    row: ArtifactQueryRow | ArtifactQueryRowInput,
    ctx: ArtifactQueryEvaluationContext,
) -> bool:
    """Evaluate *query* against one row using a shared profile context."""

    typed_row = (
        row
        if isinstance(row, ArtifactQueryRow)
        else coerce_artifact_query_row(ctx.profile, row)
    )
    return evaluate_expr(query, typed_row, ctx.profile)


def evaluate_query_for_profile(
    query: QueryExpr,
    row: ArtifactQueryRow | ArtifactQueryRowInput,
    profile: CompiledQueryProfile,
) -> bool:
    """Evaluate *query* against one row under *profile*."""

    typed_row = (
        row
        if isinstance(row, ArtifactQueryRow)
        else coerce_artifact_query_row(profile, row)
    )
    return evaluate_expr(query, typed_row, profile)


def coerce_artifact_query_row(
    profile: CompiledQueryProfile,
    entry: ArtifactQueryRowInput,
) -> ArtifactQueryRow:
    """Coerce an ArtifactEntry-like object or mapping into a typed query row."""

    if isinstance(entry, ArtifactQueryRow):
        return entry
    if is_patch_row(entry):
        return coerce_patch_query_row(profile, entry)
    return build_generic_query_row(profile, entry)


def coerce_artifact_query_rows(
    profile: CompiledQueryProfile,
    entries: Iterable[ArtifactQueryRowInput],
) -> tuple[ArtifactQueryRow, ...]:
    """Coerce entries with any corpus-level facts needed by *profile*.

    ``repeatable`` belongs to the query syntax, not row cardinality. Patch
    ancestry is also corpus-level: descendants must see the full transitive
    parent chain, matching the Rust Patch corpus.
    """

    if profile.pane_id != "patches":
        return tuple(coerce_artifact_query_row(profile, entry) for entry in entries)

    materialized = tuple(entries)
    if all(is_patch_row(item) for item in materialized):
        parent_by_name = {
            str(getattr(item, "name", "")).casefold(): patch_parent_name(item)
            for item in materialized
        }
        return tuple(
            coerce_patch_query_row(
                profile,
                item,
                ancestor_chain=patch_ancestor_chain(item, parent_by_name),
            )
            for item in materialized
        )
    return tuple(coerce_artifact_query_row(profile, entry) for entry in materialized)


def coerce_artifact_query_rows_with_wire(
    profile: CompiledQueryProfile,
    entries: Iterable[ArtifactQueryRowInput],
) -> tuple[tuple[ArtifactQueryRow, ...], list[dict[str, Any]]]:
    """Coerce *entries* and build their Rust corpus wire in the same pass."""

    if profile.pane_id == "patches":
        materialized = tuple(entries)
        if all(is_patch_row(item) for item in materialized):
            parent_by_name = {
                str(getattr(item, "name", "")).casefold(): patch_parent_name(item)
                for item in materialized
            }
            rows: list[ArtifactQueryRow] = []
            wire_rows: list[dict[str, Any]] = []
            for item in materialized:
                row, wire = coerce_patch_query_row_with_wire(
                    profile,
                    item,
                    ancestor_chain=patch_ancestor_chain(item, parent_by_name),
                )
                rows.append(row)
                wire_rows.append(wire)
            return tuple(rows), wire_rows
        entries = materialized

    rows = []
    wire_rows = []
    for entry in entries:
        row, wire = _coerce_artifact_query_row_with_wire(profile, entry)
        rows.append(row)
        wire_rows.append(wire)
    return tuple(rows), wire_rows


def coerce_artifact_query_date_value(value: object) -> int | None:
    """Coerce one row date value using the profile query row rules."""

    return coerce_date_value(value)


def _coerce_artifact_query_row_with_wire(
    profile: CompiledQueryProfile,
    entry: ArtifactQueryRowInput,
) -> tuple[ArtifactQueryRow, dict[str, Any]]:
    if isinstance(entry, ArtifactQueryRow):
        return entry, artifact_query_row_wire(entry)
    if is_patch_row(entry):
        return coerce_patch_query_row_with_wire(profile, entry)
    return build_generic_query_row_with_wire(profile, entry)
