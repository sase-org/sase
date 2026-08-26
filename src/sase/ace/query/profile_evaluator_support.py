"""Generic (non-Patch) row coercion and field-value support code for
:mod:`sase.ace.query.profile_evaluator`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
import json
import re
from typing import Any

from sase.ace.query.profile_evaluator_types import (
    ArtifactQueryRow,
    ArtifactQueryRowInput,
    ProfileFieldValue,
)
from sase.ace.query_profile import CompiledQueryProfile, QueryFieldSpec
from sase.ace.query_profile.types import FieldValueKind
from sase.vcs_log.dates import (
    VcsLogDateError,
    normalize_reference_time,
    parse_time_bound,
)

_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_BOOLEAN_VALUES = {"true": True, "false": False}


def build_generic_query_row(
    profile: CompiledQueryProfile,
    entry: ArtifactQueryRowInput,
) -> ArtifactQueryRow:
    """Coerce a mapping or ArtifactEntry-like object into a typed query row."""

    raw = _entry_mapping(entry)
    raw_fields = _entry_field_mapping(raw)
    fields = coerced_fields(profile, raw_fields)
    searchable = _searchable_text(profile, fields, raw)
    predicates = frozenset(str(item) for item in _raw_sequence(raw.get("predicates")))
    return ArtifactQueryRow(
        stable_id=_stable_id(raw),
        fields=fields,
        searchable_text=searchable,
        predicates=predicates,
    )


def build_generic_query_row_with_wire(
    profile: CompiledQueryProfile,
    entry: ArtifactQueryRowInput,
) -> tuple[ArtifactQueryRow, dict[str, Any]]:
    """Coerce *entry* and build its Rust corpus wire in the same pass."""

    raw = _entry_mapping(entry)
    raw_fields = _entry_field_mapping(raw)
    fields, wire_fields = coerced_fields_with_wire(profile, raw_fields)
    searchable = _searchable_text(profile, fields, raw)
    predicates = frozenset(str(item) for item in _raw_sequence(raw.get("predicates")))
    row = ArtifactQueryRow(
        stable_id=_stable_id(raw),
        fields=fields,
        searchable_text=searchable,
        predicates=predicates,
    )
    return row, row_wire_from_parts(
        wire_fields,
        searchable_text=searchable,
        predicates=predicates,
    )


def artifact_query_row_wire(row: ArtifactQueryRow) -> dict[str, Any]:
    """Return the Rust corpus wire shape for one already-coerced query row."""

    return row_wire_from_parts(
        {key: list(values) for key, values in row.fields.items()},
        searchable_text=row.searchable_text,
        predicates=row.predicates,
    )


def coerced_fields(
    profile: CompiledQueryProfile,
    raw_fields: Mapping[str, Any],
) -> dict[str, tuple[ProfileFieldValue, ...]]:
    return {
        spec.key: values
        for spec in profile.fields
        if (values := _coerce_field_values(spec, raw_fields.get(spec.key)))
    }


def coerced_fields_with_wire(
    profile: CompiledQueryProfile,
    raw_fields: Mapping[str, Any],
) -> tuple[
    dict[str, tuple[ProfileFieldValue, ...]], dict[str, list[ProfileFieldValue]]
]:
    fields: dict[str, tuple[ProfileFieldValue, ...]] = {}
    wire_fields: dict[str, list[ProfileFieldValue]] = {}
    for spec in profile.fields:
        values = _coerce_field_values(spec, raw_fields.get(spec.key))
        if not values:
            continue
        fields[spec.key] = values
        wire_fields[spec.key] = list(values)
    return fields, wire_fields


def row_wire_from_parts(
    fields: dict[str, list[ProfileFieldValue]],
    *,
    searchable_text: str,
    predicates: frozenset[str],
) -> dict[str, Any]:
    return {
        "fields": fields,
        "searchable_text": searchable_text,
        "predicates": {
            "error_suffix": "error_suffix" in predicates,
            "running_agent": "running_agent" in predicates,
            "running_process": "running_process" in predicates,
        },
    }


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
        return coerce_date_value(value)
    return None


def coerce_date_value(value: object) -> int | None:
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
