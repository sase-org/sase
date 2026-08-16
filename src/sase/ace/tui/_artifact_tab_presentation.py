"""Compile Python-owned provider pane presentation declarations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sase.sidecar_ref_config import REF_PANE_CONFIG_KEY

from ._artifact_tab_model import (
    PaneEmptyState,
    PaneGroupingDecl,
    PaneGroupingModeDecl,
    PanePresentation,
    PaneRowPresentation,
    PaneSortField,
)

_PANE_KEYS = frozenset(
    {
        "label",
        "description",
        "order",
        "row",
        "default_sort",
        "facets",
        "group_by",
        "empty_state",
    }
)
_ROW_KEYS = frozenset(
    {
        "title",
        "badges",
        "secondary",
        "list_fields",
        "fields",
    }
)
_SORT_KEYS = frozenset({"field", "direction"})
_EMPTY_STATE_KEYS = frozenset({"title", "body"})
_HOST_COMMON_FIELDS = frozenset(
    {
        "title",
        "filename",
        "path",
        "relpath",
        "project",
        "created_at",
        "create_time",
        "updated_at",
        "updated_time",
        "status",
        "kind",
    }
)
_SCALAR_KINDS = frozenset(
    {"string", "text", "datetime", "date", "bool", "boolean", "int", "integer", "enum"}
)
_FACET_KINDS = _SCALAR_KINDS | frozenset({"string_list"})


@dataclass(frozen=True, slots=True)
class _PanePresentationCompileResult:
    """Normalized presentation values plus an optional diagnostic."""

    label: str | None
    order: int | None
    presentation: PanePresentation
    grouping: PaneGroupingDecl
    empty_state: PaneEmptyState | None
    error: str | None = None
    error_code: str | None = None


def compile_provider_pane_presentation(
    spec: Mapping[str, Any] | None,
    *,
    default_label: str,
) -> _PanePresentationCompileResult:
    """Validate and normalize a schema-v1 ``ref.pane`` block."""

    ref = spec.get("ref") if isinstance(spec, Mapping) else None
    pane = ref.get(REF_PANE_CONFIG_KEY) if isinstance(ref, Mapping) else None
    if pane is None:
        return _PanePresentationCompileResult(
            label=None,
            order=None,
            presentation=PanePresentation(),
            grouping=PaneGroupingDecl(),
            empty_state=None,
        )
    if not isinstance(pane, Mapping):
        return _invalid("ref.pane must be a mapping")

    unknown = _unknown_keys(pane, _PANE_KEYS)
    if unknown:
        return _invalid(f"unknown ref.pane field(s): {', '.join(unknown)}")

    field_types = _field_types(ref if isinstance(ref, Mapping) else None)
    allowed_fields = frozenset(field_types) | _HOST_COMMON_FIELDS

    label, error = _optional_text(pane, "label", max_len=48)
    if error is not None:
        return _invalid(error)
    description, error = _optional_text(pane, "description", max_len=240)
    if error is not None:
        return _invalid(error)
    order, error = _optional_order(pane.get("order"))
    if error is not None:
        return _invalid(error)

    row, error = _compile_row(pane.get("row"), allowed_fields, field_types)
    if error is not None:
        return _invalid(error)
    default_sort, error = _compile_sort(
        pane.get("default_sort"), allowed_fields, field_types
    )
    if error is not None:
        return _invalid(error)
    facets, error = _compile_facets(pane.get("facets"), allowed_fields, field_types)
    if error is not None:
        return _invalid(error)
    grouping, error = _compile_group_by(
        pane.get("group_by"),
        allowed_fields,
        field_types,
    )
    if error is not None:
        return _invalid(error)
    empty_state, error = _compile_empty_state(pane.get("empty_state"), default_label)
    if error is not None:
        return _invalid(error)

    return _PanePresentationCompileResult(
        label=label,
        order=order,
        presentation=PanePresentation(
            description=description or "",
            row=row,
            default_sort=default_sort,
            facets=facets,
        ),
        grouping=grouping,
        empty_state=empty_state,
    )


def _invalid(message: str) -> _PanePresentationCompileResult:
    return _PanePresentationCompileResult(
        label=None,
        order=None,
        presentation=PanePresentation(),
        grouping=PaneGroupingDecl(),
        empty_state=None,
        error=message,
        error_code="invalid_ref_pane",
    )


def _compile_row(
    raw: object,
    allowed_fields: frozenset[str],
    field_types: Mapping[str, str],
) -> tuple[PaneRowPresentation, str | None]:
    if raw is None:
        return PaneRowPresentation(), None
    if not isinstance(raw, Mapping):
        return PaneRowPresentation(), "ref.pane.row must be a mapping"
    unknown = _unknown_keys(raw, _ROW_KEYS)
    if unknown:
        return (
            PaneRowPresentation(),
            f"unknown ref.pane.row field(s): {', '.join(unknown)}",
        )
    title = raw.get("title", "title")
    if not isinstance(title, str) or not title.strip():
        return PaneRowPresentation(), "ref.pane.row.title must be a non-empty string"
    title = title.strip()
    if not _field_allowed(title, allowed_fields):
        return (
            PaneRowPresentation(),
            f"ref.pane.row.title references unknown field {title!r}",
        )
    if _field_kind(title, field_types) == "string_list":
        return (
            PaneRowPresentation(),
            "ref.pane.row.title must reference a scalar field",
        )
    badges, error = _field_list(raw.get("badges"), "ref.pane.row.badges")
    if error is not None:
        return PaneRowPresentation(), error
    secondary, error = _field_list(raw.get("secondary"), "ref.pane.row.secondary")
    if error is not None:
        return PaneRowPresentation(), error
    list_fields, error = _field_list(
        raw.get("list_fields", raw.get("fields")), "ref.pane.row.list_fields"
    )
    if error is not None:
        return PaneRowPresentation(), error
    for key, fields in (
        ("ref.pane.row.badges", badges),
        ("ref.pane.row.secondary", secondary),
        ("ref.pane.row.list_fields", list_fields),
    ):
        missing = [
            field for field in fields if not _field_allowed(field, allowed_fields)
        ]
        if missing:
            return (
                PaneRowPresentation(),
                f"{key} references unknown field(s): {', '.join(missing)}",
            )
    return (
        PaneRowPresentation(
            title=title,
            badges=badges,
            secondary=secondary,
            list_fields=list_fields,
        ),
        None,
    )


def _compile_sort(
    raw: object,
    allowed_fields: frozenset[str],
    field_types: Mapping[str, str],
) -> tuple[tuple[PaneSortField, ...], str | None]:
    if raw is None:
        return (), None
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return (), "ref.pane.default_sort must be a list"
    result: list[PaneSortField] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if isinstance(item, str):
            field = item.strip()
            direction: Literal["asc", "desc"] = "asc"
        elif isinstance(item, Mapping):
            unknown = _unknown_keys(item, _SORT_KEYS)
            if unknown:
                return (
                    (),
                    (
                        f"unknown ref.pane.default_sort[{index}] field(s): "
                        f"{', '.join(unknown)}"
                    ),
                )
            raw_field = item.get("field")
            if not isinstance(raw_field, str) or not raw_field.strip():
                return (), f"ref.pane.default_sort[{index}].field is required"
            field = raw_field.strip()
            raw_direction = item.get("direction", "asc")
            if raw_direction not in {"asc", "desc"}:
                return (
                    (),
                    f"ref.pane.default_sort[{index}].direction must be asc or desc",
                )
            direction = raw_direction
        else:
            return (), f"ref.pane.default_sort[{index}] must be a mapping or string"
        if not _field_allowed(field, allowed_fields):
            return (
                (),
                f"ref.pane.default_sort[{index}] references unknown field {field!r}",
            )
        if field in seen:
            return (), f"duplicate ref.pane.default_sort field {field!r}"
        seen.add(field)
        if _field_kind(field, field_types) not in _SCALAR_KINDS:
            return (), f"ref.pane.default_sort[{index}] must reference a scalar field"
        result.append(PaneSortField(field=field, direction=direction))
    return tuple(result), None


def _compile_facets(
    raw: object,
    allowed_fields: frozenset[str],
    field_types: Mapping[str, str],
) -> tuple[tuple[str, ...], str | None]:
    if raw is None:
        return (), None
    fields, error = _field_list(raw, "ref.pane.facets")
    if error is not None:
        return (), error
    for field in fields:
        if not _field_allowed(field, allowed_fields):
            return (), f"ref.pane.facets references unknown field {field!r}"
        if _field_kind(field, field_types) not in _FACET_KINDS:
            return (), f"ref.pane.facets field {field!r} is not facetable"
    return fields, None


def _compile_group_by(
    raw: object,
    allowed_fields: frozenset[str],
    field_types: Mapping[str, str],
) -> tuple[PaneGroupingDecl, str | None]:
    if raw is None:
        return PaneGroupingDecl(), None
    fields: tuple[str, ...]
    if isinstance(raw, str):
        fields = (raw.strip(),) if raw.strip() else ()
    else:
        fields, error = _field_list(raw, "ref.pane.group_by")
        if error is not None:
            return PaneGroupingDecl(), error
    if not fields:
        return PaneGroupingDecl(), "ref.pane.group_by must name at least one field"
    for field in fields:
        if not _field_allowed(field, allowed_fields):
            return (
                PaneGroupingDecl(),
                f"ref.pane.group_by references unknown field {field!r}",
            )
        if _field_kind(field, field_types) not in _FACET_KINDS:
            return (
                PaneGroupingDecl(),
                f"ref.pane.group_by field {field!r} is not groupable",
            )
    mode_id = f"by_{'_'.join(fields)}"
    label = " / ".join(_field_label(field) for field in fields)
    return (
        PaneGroupingDecl(
            modes=(PaneGroupingModeDecl(id=mode_id, label=label, keys=fields),),
            default_mode=mode_id,
        ),
        None,
    )


def _compile_empty_state(
    raw: object,
    default_label: str,
) -> tuple[PaneEmptyState | None, str | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, Mapping):
        return None, "ref.pane.empty_state must be a mapping"
    unknown = _unknown_keys(raw, _EMPTY_STATE_KEYS)
    if unknown:
        return None, f"unknown ref.pane.empty_state field(s): {', '.join(unknown)}"
    title, error = _optional_text(
        raw, "title", max_len=80, prefix="ref.pane.empty_state"
    )
    if error is not None:
        return None, error
    body, error = _optional_text(
        raw, "body", max_len=320, prefix="ref.pane.empty_state"
    )
    if error is not None:
        return None, error
    return (
        PaneEmptyState(
            title=title or f"No {default_label.lower()}s",
            body=body
            or f"No {default_label.lower()}s match the current project scope and filters.",
        ),
        None,
    )


def _optional_text(
    raw: Mapping[str, Any],
    key: str,
    *,
    max_len: int,
    prefix: str = "ref.pane",
) -> tuple[str | None, str | None]:
    if key not in raw:
        return None, None
    value = raw.get(key)
    if not isinstance(value, str):
        return None, f"{prefix}.{key} must be a string"
    text = " ".join(value.strip().split())
    if not text:
        return None, f"{prefix}.{key} must not be empty"
    if len(text) > max_len:
        return None, f"{prefix}.{key} must be {max_len} characters or fewer"
    return text, None


def _optional_order(value: object) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, bool) or not isinstance(value, int):
        return None, "ref.pane.order must be an integer"
    if not -10_000 <= value <= 10_000:
        return None, "ref.pane.order must be between -10000 and 10000"
    return value, None


def _field_list(value: object, label: str) -> tuple[tuple[str, ...], str | None]:
    if value is None:
        return (), None
    if isinstance(value, str):
        items = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = tuple(value)
    else:
        return (), f"{label} must be a string or list of strings"
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, str) or not item.strip():
            return (), f"{label}[{index}] must be a non-empty string"
        field = item.strip()
        if field in seen:
            return (), f"duplicate {label} field {field!r}"
        seen.add(field)
        result.append(field)
    return tuple(result), None


def _field_types(ref: Mapping[str, Any] | None) -> dict[str, str]:
    properties = ref.get("properties") if isinstance(ref, Mapping) else None
    if not isinstance(properties, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, value in properties.items():
        name = str(key)
        if not name:
            continue
        raw_type = value.get("type") if isinstance(value, Mapping) else None
        result[name] = raw_type if isinstance(raw_type, str) else "string"
    return result


def _field_kind(field: str, field_types: Mapping[str, str]) -> str:
    return field_types.get(field, "string")


def _field_allowed(field: str, allowed_fields: frozenset[str]) -> bool:
    return field in allowed_fields


def _field_label(field: str) -> str:
    return field.replace("_", " ").replace("-", " ").title()


def _unknown_keys(raw: Mapping[Any, Any], allowed: frozenset[str]) -> list[str]:
    return sorted(str(key) for key in raw if str(key) not in allowed)


__all__ = [
    "compile_provider_pane_presentation",
]
