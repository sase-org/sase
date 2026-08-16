"""Profile-driven Artifact row coercion and evaluation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from typing import Any, cast

from sase.ace.query.searchable import RUNNING_AGENT_MARKER, RUNNING_PROCESS_MARKER
from sase.ace.query.types import (
    AndExpr,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
)
from sase.ace.query_profile import CompiledQueryProfile, QueryFieldSpec
from sase.ace.query_profile.types import FieldValueKind
from sase.core.patch import strip_reverted_suffix
from sase.vcs_log.dates import (
    VcsLogDateError,
    normalize_reference_time,
    parse_time_bound,
)

type ProfileFieldValue = str | bool | int
type ArtifactQueryRowInput = Mapping[str, Any] | object

_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_BOOLEAN_VALUES = {"true": True, "false": False}


@dataclass(frozen=True, slots=True)
class ArtifactQueryRow:
    """Typed/coerced row consumed by the profile reference evaluator."""

    stable_id: str
    fields: Mapping[str, tuple[ProfileFieldValue, ...]]
    searchable_text: str
    predicates: frozenset[str] = frozenset()


@dataclass(slots=True)
class ArtifactQueryEvaluationContext:
    """Immutable per-corpus data shared by profile-driven per-row evaluation."""

    profile: CompiledQueryProfile
    rows: tuple[ArtifactQueryRow, ...]
    by_stable_id: Mapping[str, ArtifactQueryRow] = field(init=False)

    def __post_init__(self) -> None:
        self.by_stable_id = {row.stable_id: row for row in self.rows}


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
    return _evaluate(query, typed_row, ctx.profile)


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
    return _evaluate(query, typed_row, profile)


def coerce_artifact_query_row(
    profile: CompiledQueryProfile,
    entry: ArtifactQueryRowInput,
) -> ArtifactQueryRow:
    """Coerce an ArtifactEntry-like object or mapping into a typed query row."""

    if _is_patch_row(entry):
        return _coerce_patch_query_row(profile, entry)

    raw = _entry_mapping(entry)
    raw_fields = _entry_field_mapping(raw)
    fields = {
        spec.key: values
        for spec in profile.fields
        if (values := _coerce_field_values(spec, raw_fields.get(spec.key)))
    }
    searchable_text = _searchable_text(profile, fields, raw)
    predicates = frozenset(str(item) for item in _raw_sequence(raw.get("predicates")))
    return ArtifactQueryRow(
        stable_id=_stable_id(raw),
        fields=fields,
        searchable_text=searchable_text,
        predicates=predicates,
    )


def coerce_artifact_query_rows(
    profile: CompiledQueryProfile,
    entries: Iterable[ArtifactQueryRowInput],
) -> tuple[ArtifactQueryRow, ...]:
    """Coerce entries with any corpus-level facts needed by *profile*.

    ``repeatable`` belongs to the query syntax, not row cardinality. Patch
    ancestry is also corpus-level: descendants must see the full transitive
    parent chain, matching the Rust Patch corpus.
    """

    materialized = tuple(entries)
    if profile.pane_id == "patches" and all(
        _is_patch_row(item) for item in materialized
    ):
        parent_by_name = {
            str(getattr(item, "name", "")).casefold(): _patch_parent_name(item)
            for item in materialized
        }
        return tuple(
            _coerce_patch_query_row(
                profile,
                item,
                ancestor_chain=_patch_ancestor_chain(item, parent_by_name),
            )
            for item in materialized
        )
    return tuple(coerce_artifact_query_row(profile, entry) for entry in materialized)


def _entry_mapping(entry: ArtifactQueryRowInput) -> Mapping[str, Any]:
    if isinstance(entry, Mapping):
        return entry
    to_wire = getattr(entry, "to_wire", None)
    if callable(to_wire):
        wire = to_wire()
        if isinstance(wire, Mapping):
            return wire
    raw: dict[str, Any] = {}
    for name in (
        "stable_id",
        "ref_kind",
        "canonical_argument",
        "display_label",
        "origin",
        "project_display_name",
        "repository",
        "repo_relative_path",
        "captured_revision",
        "captured_digest",
        "logical_path",
        "properties",
        "predicates",
        "searchable_text",
    ):
        if hasattr(entry, name):
            raw[name] = getattr(entry, name)
    return raw


def _entry_field_mapping(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    properties = raw.get("properties")
    fields = raw.get("fields")
    merged: dict[str, Any] = {}
    if isinstance(properties, Mapping):
        merged.update(properties)
    if isinstance(fields, Mapping):
        merged.update(fields)
    for key, value in raw.items():
        if key not in {"properties", "fields", "predicates", "searchable_text"}:
            merged.setdefault(key, value)
    return merged


def _stable_id(raw: Mapping[str, Any]) -> str:
    value = raw.get("stable_id") or raw.get("id") or raw.get("canonical_argument")
    if value is None:
        return ""
    return str(value)


def _coerce_field_values(
    field: QueryFieldSpec,
    raw: object,
) -> tuple[ProfileFieldValue, ...]:
    values = _raw_values(raw, repeatable=field.repeatable)
    coerced: list[ProfileFieldValue] = []
    for value in values:
        item = _coerce_one_field_value(field.value_kind, value)
        if item is not None:
            coerced.append(item)
    return tuple(coerced)


def _raw_values(raw: object, *, repeatable: bool) -> tuple[object, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        if repeatable:
            parsed = _parse_serialized_sequence(raw)
            if parsed is not None:
                return parsed
        return (raw,)
    if isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        return tuple(raw)
    return (raw,)


def _raw_sequence(raw: object) -> tuple[object, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, Iterable) and not isinstance(raw, (bytes, bytearray, Mapping)):
        return tuple(raw)
    return (raw,)


def _parse_serialized_sequence(value: str) -> tuple[object, ...] | None:
    stripped = value.strip()
    if not stripped:
        return ()
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list):
            return tuple(parsed)
    if "\n" in value:
        return tuple(item.strip() for item in value.splitlines() if item.strip())
    return None


def _coerce_one_field_value(
    kind: FieldValueKind,
    value: object,
) -> ProfileFieldValue | None:
    if kind in {"string", "enum"}:
        return _string_value(value)
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return _BOOLEAN_VALUES.get(value.casefold())
        return None
    if kind == "int":
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and _INTEGER_RE.fullmatch(value.strip()):
            return int(value)
        return None
    if kind == "date":
        return _coerce_date_value(value)
    return None


def _coerce_date_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if _INTEGER_RE.fullmatch(text):
        return int(text)
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        try:
            return parse_time_bound(text).resolve(
                now=normalize_reference_time(),
                boundary="since",
            )
        except VcsLogDateError:
            return None


def _string_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int)):
        return str(value).lower() if isinstance(value, bool) else str(value)
    return None


def _searchable_text(
    profile: CompiledQueryProfile,
    fields: Mapping[str, tuple[ProfileFieldValue, ...]],
    raw: Mapping[str, Any],
) -> str:
    explicit = raw.get("searchable_text")
    if isinstance(explicit, str):
        return explicit
    parts: list[str] = []
    for key in profile.searchable_fields():
        for value in fields.get(key, ()):
            parts.append(str(value))
    return "\n".join(parts)


def _evaluate(
    expr: QueryExpr,
    row: ArtifactQueryRow,
    profile: CompiledQueryProfile,
) -> bool:
    if isinstance(expr, StringMatch):
        if expr.is_error_suffix:
            return "error_suffix" in row.predicates
        if expr.is_running_agent:
            return "running_agent" in row.predicates
        if expr.is_running_process:
            return "running_process" in row.predicates
        return _match_string(row.searchable_text, expr)
    if isinstance(expr, PropertyMatch):
        return _match_field(profile, row, expr)
    if isinstance(expr, NotExpr):
        return not _evaluate(expr.operand, row, profile)
    if isinstance(expr, AndExpr):
        return all(_evaluate(item, row, profile) for item in expr.operands)
    if isinstance(expr, OrExpr):
        return any(_evaluate(item, row, profile) for item in expr.operands)
    raise TypeError(f"Unknown expression type: {type(expr)}")


def _match_string(text: str, expr: StringMatch) -> bool:
    if expr.case_sensitive:
        return expr.value in text
    return expr.value.casefold() in text.casefold()


def _match_field(
    profile: CompiledQueryProfile,
    row: ArtifactQueryRow,
    expr: PropertyMatch,
) -> bool:
    field = profile.field(expr.key)
    if field is None:
        return False
    values = row.fields.get(expr.key, ())
    if not values:
        return False
    if field.value_kind == "bool":
        desired = expr.value == "true"
        return any(isinstance(value, bool) and value is desired for value in values)
    if field.value_kind == "int":
        try:
            desired_int = int(expr.value)
        except ValueError:
            return False
        return any(value == desired_int for value in values)
    if field.value_kind == "date":
        try:
            desired_epoch = int(expr.value)
        except ValueError:
            return False
        return _match_date_field(expr.key, values, desired_epoch)
    return _match_text_field(profile, field, values, expr.value)


def _match_date_field(
    key: str,
    values: tuple[ProfileFieldValue, ...],
    desired_epoch: int,
) -> bool:
    int_values = tuple(value for value in values if isinstance(value, int))
    if key == "since":
        return any(value >= desired_epoch for value in int_values)
    if key == "until":
        return any(value <= desired_epoch for value in int_values)
    return any(value == desired_epoch for value in int_values)


def _match_text_field(
    profile: CompiledQueryProfile,
    field: QueryFieldSpec,
    values: tuple[ProfileFieldValue, ...],
    desired: str,
) -> bool:
    desired_text = desired.casefold()
    if field.key == "sibling" and profile.pane_id == "patches":
        desired_text = strip_reverted_suffix(desired).casefold()
    haystack = tuple(str(value).casefold() for value in values)
    if field.value_kind == "enum" or field.exact_match:
        return desired_text in haystack
    return any(desired_text in value for value in haystack)


def _is_patch_row(entry: object) -> bool:
    return all(
        hasattr(entry, name)
        for name in ("name", "description", "status", "project_query_name")
    )


def _coerce_patch_query_row(
    profile: CompiledQueryProfile,
    entry: object,
    *,
    ancestor_chain: tuple[str, ...] | None = None,
) -> ArtifactQueryRow:
    from sase.ace.patch import has_any_status_suffix, normalize_pr_origin
    from sase.ace.query.matchers import get_base_status
    from sase.ace.query.searchable import get_searchable_text

    name = str(getattr(entry, "name", ""))
    parent = getattr(entry, "parent", None)
    searchable = get_searchable_text(cast(Any, entry))
    raw_fields: dict[str, Any] = {
        "status": get_base_status(str(getattr(entry, "status", ""))),
        "project": str(getattr(entry, "project_query_name", "")),
        "name": name,
        "sibling": strip_reverted_suffix(name),
        "origin": normalize_pr_origin(getattr(entry, "pr_origin", None)),
        "description": str(getattr(entry, "description", "")),
        "refs": tuple(getattr(entry, "refs", ()) or ()),
        "parent": parent or "",
        "pr_url": getattr(entry, "pr_url", "") or "",
        "notes": searchable,
    }
    if ancestor_chain is not None:
        raw_fields["ancestor"] = ancestor_chain
    elif parent:
        raw_fields["ancestor"] = (name, str(parent))
    else:
        raw_fields["ancestor"] = (name,)
    fields = {
        spec.key: values
        for spec in profile.fields
        if (values := _coerce_field_values(spec, raw_fields.get(spec.key)))
    }
    predicates = set[str]()
    if has_any_status_suffix(cast(Any, entry)):
        predicates.add("error_suffix")
    if RUNNING_AGENT_MARKER in searchable:
        predicates.add("running_agent")
    if RUNNING_PROCESS_MARKER in searchable:
        predicates.add("running_process")
    return ArtifactQueryRow(
        stable_id=patch_query_stable_id(entry),
        fields=fields,
        searchable_text=searchable,
        predicates=frozenset(predicates),
    )


def patch_query_stable_id(entry: object) -> str:
    """Return the profile-query row id for a Patch-like object."""

    project = getattr(entry, "project_name", None)
    if project is None:
        project = getattr(entry, "project_query_name", "")
    return f"{project}\x1f{getattr(entry, 'name', '')}"


def _patch_parent_name(entry: object) -> str | None:
    parent = getattr(entry, "parent", None)
    if parent is None:
        return None
    text = str(parent)
    return text or None


def _patch_ancestor_chain(
    entry: object,
    parent_by_name: Mapping[str, str | None],
) -> tuple[str, ...]:
    """Return own name followed by transitive ancestors, cycle-guarded."""

    chain: list[str] = []
    seen: set[str] = set()
    current = str(getattr(entry, "name", ""))
    while current:
        folded = current.casefold()
        if folded in seen:
            break
        seen.add(folded)
        chain.append(current)
        parent = parent_by_name.get(folded)
        if parent is None:
            break
        current = parent
    return tuple(chain)


__all__ = [
    "ArtifactQueryEvaluationContext",
    "ArtifactQueryRow",
    "ArtifactQueryRowInput",
    "ProfileFieldValue",
    "build_query_context_for_profile",
    "coerce_artifact_query_row",
    "coerce_artifact_query_rows",
    "evaluate_query_for_profile",
    "evaluate_query_with_profile_context",
    "patch_query_stable_id",
]
