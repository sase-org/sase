"""Derive a flat-mode schema from a document provider's ``ref.properties``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..registry import HOST_PREDICATES
from ..types import ArtifactQuerySchema, FieldValueKind, QueryFieldSpec

_PROVIDER_TYPE_KINDS: dict[str, FieldValueKind] = {
    "string": "string",
    "text": "string",
    "datetime": "date",
    "date": "date",
    "bool": "bool",
    "boolean": "bool",
    "int": "int",
    "integer": "int",
    "enum": "enum",
}


def provider_query_schema(
    kind: str, spec: Mapping[str, Any] | None
) -> ArtifactQuerySchema:
    """Derive a flat-mode schema from a document provider's ``ref.properties``.

    Providers declare fields and facts only: the profile compiler never
    grants a provider sigils or macros. Host predicates are shared with the
    fixed panes. An unrecognized declared ``type`` degrades to ``"string"``
    rather than raising, matching the epic's "malformed values degrade per
    entry" policy for provider input.
    """

    ref = spec.get("ref") if isinstance(spec, Mapping) else None
    properties = ref.get("properties") if isinstance(ref, Mapping) else None
    fields: list[QueryFieldSpec] = []
    if isinstance(properties, Mapping):
        for name in sorted(str(key) for key in properties if str(key)):
            declared = properties[name]
            value_kind, repeatable, static_values = _provider_value_kind(declared)
            fields.append(
                QueryFieldSpec(
                    key=name,
                    value_kind=value_kind,
                    static_values=static_values,
                    searchable=_provider_searchable(declared, value_kind),
                    repeatable=repeatable,
                    negatable=True,
                    hint=f"declared {kind} property",
                )
            )
    if not any(item.key == "path" for item in fields):
        fields.append(
            QueryFieldSpec(
                key="path",
                exact_match=True,
                searchable=True,
                negatable=True,
                hint="document path or provider identity",
            )
        )
    searchable_keys = tuple(item.key for item in fields if item.searchable)
    free_text_hint = f"{', '.join(searchable_keys)} (AND)" if searchable_keys else ""
    return ArtifactQuerySchema(
        pane_id=f"ref:{kind}",
        boolean=False,
        fields=tuple(fields),
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        free_text_hint=free_text_hint,
        identity_field="path",
    )


def _provider_value_kind(
    declared: object,
) -> tuple[FieldValueKind, bool, tuple[str, ...]]:
    if not isinstance(declared, Mapping):
        return "string", False, ()
    raw_type = declared.get("type")
    if raw_type == "string_list":
        return "string", True, ()
    if isinstance(raw_type, str):
        value_kind = _PROVIDER_TYPE_KINDS.get(raw_type, "string")
        return value_kind, False, _enum_values(declared) if value_kind == "enum" else ()
    return "string", False, ()


def _enum_values(declared: Mapping[str, Any]) -> tuple[str, ...]:
    values = declared.get("values")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return ()
    return tuple(
        dict.fromkeys(item.strip() for item in values if isinstance(item, str) and item)
    )


def _provider_searchable(declared: object, value_kind: FieldValueKind) -> bool:
    if isinstance(declared, Mapping) and "searchable" in declared:
        return bool(declared["searchable"])
    return value_kind == "string"


__all__ = ["provider_query_schema"]
