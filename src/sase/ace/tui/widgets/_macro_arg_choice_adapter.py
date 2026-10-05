"""Typed adapter between TUI macro hints and the shared Rust choice contract."""

from __future__ import annotations

from dataclasses import dataclass

from sase.core.rust import require_rust_binding

from ._macro_arg_assist_models import MacroInputHint


@dataclass(frozen=True, slots=True)
class _MacroChoiceRow:
    """One rehydrated Rust choice candidate for TUI rendering."""

    value: str
    insertion: str
    label: str | None
    description: str | None
    index: int
    is_default: bool


def hint_to_wire(hint: MacroInputHint) -> dict:
    """Serialize a TUI hint to the Rust ``MacroInputHint`` wire shape."""
    return {
        "name": hint.name,
        "type": hint.type,
        "description": hint.description,
        "required": hint.required,
        "default_display": hint.default_display,
        "position": hint.position,
        "repeatable": hint.repeatable,
        "choices": [
            {
                "value": choice.value,
                "label": choice.label,
                "description": choice.description,
            }
            for choice in hint.choices
        ],
        "named_type": hint.named_type,
        "value_role": hint.value_role,
    }


def choice_candidates_for_hint(
    hint: MacroInputHint,
    *,
    partial: str,
    replacement: str,
    selected: frozenset[str] | set[str] | tuple[str, ...] | list[str] = (),
) -> list[_MacroChoiceRow]:
    """Return shared Rust choice candidates for one TUI hint."""
    candidates = require_rust_binding("macro_argument_choice_candidates")(
        {
            "hint": hint_to_wire(hint),
            "partial": partial,
            "replacement": replacement,
            "selected": sorted(selected),
        }
    )
    rows: list[_MacroChoiceRow] = []
    for row in candidates:
        rows.append(
            _MacroChoiceRow(
                value=str(row["value"]),
                insertion=str(row["insertion"]),
                label=row.get("label"),
                description=row.get("description"),
                index=int(row["index"]),
                is_default=bool(row.get("is_default", False)),
            )
        )
    return rows


def type_label_for_hint(hint: MacroInputHint) -> str:
    """Return the shared Rust type label for one TUI hint."""
    return str(
        require_rust_binding("macro_input_type_label")({"hint": hint_to_wire(hint)})
    )


__all__ = [
    "choice_candidates_for_hint",
    "hint_to_wire",
    "type_label_for_hint",
]
