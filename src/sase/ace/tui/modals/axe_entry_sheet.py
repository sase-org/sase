"""Pure presentation model for the AXE entry property sheet.

This module deliberately has no Textual imports.  It turns the sparse schema
form into stable row, detail-dock, status, and hint descriptors that can be
tested without mounting a TUI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .config_edit_helpers import format_value
from .schema_object_form import (
    SchemaFieldGroup,
    SchemaObjectField,
    SchemaObjectForm,
)


AxeEntrySheetMode = Literal["browse", "cell"]
AxeEntrySheetStage = Literal["edit", "preview"]
AxeEntrySheetRowState = Literal[
    "target",
    "inherited",
    "unset",
    "edited",
    "inherit",
    "invalid",
]

_EM_DASH = "—"
_BADGE_STYLES: dict[AxeEntrySheetRowState, str] = {
    "target": "source",
    "inherited": "source",
    "unset": "unset",
    "edited": "edited",
    "inherit": "inherit",
    "invalid": "invalid",
}


@dataclass(frozen=True)
class AxeEntrySheetRow:
    """One stable property row in the AXE entry sheet."""

    group: SchemaFieldGroup
    name: str
    required: bool
    value: str
    badge: str
    badge_style: str
    state: AxeEntrySheetRowState
    dim_value: bool
    editor_kind: str
    validation_message: str | None = None


@dataclass(frozen=True)
class _AxeEntrySheetColumns:
    """Calculated property-sheet column widths."""

    name: int
    value: int
    badge: int


def build_sheet_rows(
    form: SchemaObjectForm,
    *,
    target: str | None,
) -> tuple[AxeEntrySheetRow, ...]:
    """Return ordered row descriptors for every schema property."""
    return tuple(_sheet_row(field, target=target) for field in form.fields)


def _sheet_row(
    field: SchemaObjectField,
    *,
    target: str | None,
) -> AxeEntrySheetRow:
    state = _row_state(field)
    if state == "invalid":
        raw_value: Any = (
            field.draft_text if field.draft_text is not None else field.draft_value
        )
        badge = "edited"
    elif state == "inherit":
        raw_value = (
            field.inherited_value
            if field.has_inherited
            else field.schema.get("default")
        )
        badge = "inherit"
    elif state == "edited":
        raw_value = (
            field.draft_text if field.draft_text is not None else field.draft_value
        )
        badge = "edited"
    elif state == "target":
        raw_value = field.effective_value
        badge = f"·{target or field.source or 'local'}"
    elif state == "inherited":
        raw_value = field.effective_value
        badge = f"·{field.source or 'inherit'}"
    else:
        raw_value = None
        badge = "unset"
    return AxeEntrySheetRow(
        group=field.group,
        name=field.name,
        required=field.required,
        value=_summarize_sheet_value(field.name, raw_value),
        badge=badge,
        badge_style=_BADGE_STYLES[state],
        state=state,
        dim_value=state in {"inherited", "unset", "inherit"},
        editor_kind=field.editor_kind,
        validation_message=field.parse_error,
    )


def _row_state(field: SchemaObjectField) -> AxeEntrySheetRowState:
    if field.parse_error is not None:
        return "invalid"
    if field.reset:
        return "inherit"
    if field.touched:
        return "edited"
    if field.has_target:
        return "target"
    if field.has_effective:
        return "inherited"
    return "unset"


def _summarize_sheet_value(name: str, value: Any) -> str:
    """Render a compact, single-line value suitable for a property row."""
    if value is None:
        return _EM_DASH
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        flattened = " ".join(part.strip() for part in value.splitlines()).strip()
        return flattened or '""'
    if isinstance(value, Mapping):
        if not value:
            return "{}"
        if len(value) == 1:
            key, item = next(iter(value.items()))
            if _is_scalar(item):
                return f"{key}: {_scalar_summary(item)}"
        return f"{len(value)} entries"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        noun = "targets" if name == "for_each" else "items"
        return f"{len(value)} {noun}"
    return format_value(value)


def sheet_column_widths(
    rows: Sequence[AxeEntrySheetRow],
    *,
    width: int,
    narrow: bool = False,
) -> _AxeEntrySheetColumns:
    """Fit fixed name/badge columns while preserving a useful value column."""
    available = max(18, width - 2)
    required_width = max(
        (len(row.name) + (2 if row.required else 0) for row in rows), default=8
    )
    name_cap = 14 if narrow else 22
    name_width = max(8, min(name_cap, required_width + 2))
    if narrow:
        return _AxeEntrySheetColumns(
            name=name_width,
            value=max(8, available - name_width),
            badge=0,
        )
    badge_width = max(
        7,
        min(24, max((len(row.badge) for row in rows), default=5) + 1),
    )
    value_width = max(8, available - name_width - badge_width)
    overflow = name_width + badge_width + value_width - available
    if overflow > 0:
        name_width = max(8, name_width - overflow)
    return _AxeEntrySheetColumns(
        name=name_width,
        value=max(8, available - name_width - badge_width),
        badge=badge_width,
    )


def detail_dock_lines(
    field: SchemaObjectField | None,
    *,
    target: str | None,
    vim_mode: str = "",
) -> tuple[str, str, str]:
    """Return the fixed three logical lines rendered by the detail dock."""
    if field is None:
        return ("No editable properties.", "", "")
    required = " *" if field.required else ""
    mode = f"  {vim_mode}" if vim_mode else ""
    header = f"{field.name}{required}  {field.editor_kind}{mode}"
    description = field.description or "No description available."
    effective = (
        _detail_value(field.effective_value) if field.has_effective else _EM_DASH
    )
    layer = _detail_value(field.target_value) if field.has_target else _EM_DASH
    inherited = (
        _detail_value(field.inherited_value) if field.has_inherited else _EM_DASH
    )
    definitions = (
        f'Effective "{effective}"  '
        f'Layer({target or "target"}) "{layer}"  '
        f'Inherits "{inherited}"'
    )
    return header, description, definitions


def status_line_text(
    field: SchemaObjectField | None,
    *,
    error: str | None = None,
    status: str | None = None,
) -> str:
    """Choose the highest-priority validation/transaction status line."""
    if error:
        return f"! {error}"
    if field is not None and field.parse_error:
        return f"! {field.parse_error}"
    if field is not None and field.parse_deferred:
        return "large YAML buffer; preview validates it"
    return status or ""


def hint_text(
    *,
    mode: AxeEntrySheetMode,
    stage: AxeEntrySheetStage,
    running: bool,
    busy: bool = False,
    narrow: bool = False,
) -> str:
    """Return the mode-aware bottom hint text."""
    if stage == "preview":
        if busy:
            return "Working…"
        primary = "save & restart" if running else "save"
        save_only = " · ^O save only" if running and not narrow else ""
        return f"↑↓ scroll · ^D/^U page · ⏎ {primary}{save_only} · q quit · esc back"
    if mode == "cell":
        if narrow:
            return "tab next · ⇧tab prev · esc normal/browse · ^S preview"
        return (
            "tab next · shift+tab previous · esc normal/browse · "
            "^R inherit · ^S preview"
        )
    if narrow:
        return "↑↓ move · ⏎/i edit · space toggle · 1-9 scope · ^S save · q quit · esc"
    return (
        "↑↓/jk move · ⏎/i edit · space toggle · ^R inherit · "
        "1-9 scope · ^S preview & save · q quit · esc"
    )


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _scalar_summary(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return format_value(value)


def _detail_value(value: Any) -> str:
    rendered = _summarize_sheet_value("", value)
    return rendered.replace('"', r"\"")


__all__ = [
    "AxeEntrySheetMode",
    "AxeEntrySheetRow",
    "AxeEntrySheetRowState",
    "AxeEntrySheetStage",
    "build_sheet_rows",
    "detail_dock_lines",
    "hint_text",
    "sheet_column_widths",
    "status_line_text",
]
