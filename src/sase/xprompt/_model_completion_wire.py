"""Wire conversion and Rust-backed filtering for ``%model`` completions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.rust import require_rust_binding
from sase.xprompt._model_completion_entry import (
    MODEL_COMPLETION_ENTRY_WIRE_FIELDS,
    MODEL_COMPLETION_INT_FIELDS,
    ModelCompletionEntry,
)


def filter_model_completion_entries(
    entries: list[ModelCompletionEntry],
    partial: str,
) -> list[ModelCompletionEntry]:
    """Return entries whose value or alias hint prefix-matches ``partial``."""
    binding = require_rust_binding("filter_model_completion_entries")
    payload: Any = binding(model_completion_entry_wire_rows(entries), partial)
    if not isinstance(payload, list):
        raise TypeError("filter_model_completion_entries returned a non-list payload")
    return [_model_completion_entry_from_wire(row) for row in payload]


def filter_model_alias_shortcut_entries(
    entries: Sequence[ModelCompletionEntry],
    query: str,
) -> list[ModelCompletionEntry]:
    """Return alias-only catalog rows a ``*query`` shortcut may expand to.

    Reuses the shared Rust ``filter_model_alias_shortcut_entries`` binding so
    ACE and the xprompt LSP never diverge on alias-kind filtering, prefix
    matching, or canonical catalog order.
    """
    binding = require_rust_binding("filter_model_alias_shortcut_entries")
    payload: Any = binding(model_completion_entry_wire_rows(entries), query)
    if not isinstance(payload, list):
        raise TypeError(
            "filter_model_alias_shortcut_entries returned a non-list payload"
        )
    return [_model_completion_entry_from_wire(row) for row in payload]


def model_completion_entry_wire_rows(
    entries: Sequence[ModelCompletionEntry],
) -> list[dict[str, object]]:
    """Return rectangular Rust/Python wire rows for model catalog entries."""
    return [model_completion_entry_to_wire(entry) for entry in entries]


def model_completion_entry_to_wire(
    entry: ModelCompletionEntry,
) -> dict[str, object]:
    """Return the rectangular Rust/Python wire row for one entry."""
    row: dict[str, object] = {}
    for field_name in MODEL_COMPLETION_ENTRY_WIRE_FIELDS:
        value = getattr(entry, field_name)
        row[field_name] = list(value) if field_name == "aliases" else value
    return row


def _model_completion_entry_from_wire(
    payload: object,
) -> ModelCompletionEntry:
    """Rehydrate one Rust-returned wire row into the Python dataclass."""
    if not isinstance(payload, Mapping):
        raise TypeError("model completion filter row must be a mapping")
    values: dict[str, object] = {}
    for field_name in MODEL_COMPLETION_ENTRY_WIRE_FIELDS:
        raw = payload.get(field_name)
        if field_name == "aliases":
            values[field_name] = tuple(item for item in _str_list(raw) if item)
        elif field_name in MODEL_COMPLETION_INT_FIELDS:
            values[field_name] = raw if isinstance(raw, int) else 0
        else:
            values[field_name] = raw if isinstance(raw, str) else ""
    return ModelCompletionEntry(**values)  # type: ignore[arg-type]


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


__all__ = [
    "filter_model_alias_shortcut_entries",
    "filter_model_completion_entries",
    "model_completion_entry_to_wire",
    "model_completion_entry_wire_rows",
]
