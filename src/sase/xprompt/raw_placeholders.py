"""Typed facade over raw placeholder Rust bindings.

The parsing, literal-zone classification, substitution, and input-name
slugging rules live in ``sase-core``.  This module rehydrates the binding's
JSON-shaped values so callers stay typed and do not depend on untyped dicts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding

DEFAULT_CONTEXT_WIDTH = 60


@dataclass(frozen=True, slots=True)
class RawPlaceholderField:
    """One unique raw placeholder prepared for an input collection surface."""

    text: str
    occurrences: int
    context: str


def raw_placeholder_fields(
    text: str,
    context_width: int = DEFAULT_CONTEXT_WIDTH,
) -> tuple[RawPlaceholderField, ...]:
    """Return unique raw placeholders in first-occurrence order."""
    binding = require_rust_binding("raw_placeholder_fields")
    return tuple(_field_from_dict(item) for item in binding(text, context_width))


def substitute_raw_placeholders(text: str, values: Mapping[str, str]) -> str:
    """Replace mapped raw placeholders while leaving literal spans untouched."""
    binding = require_rust_binding("substitute_raw_placeholders")
    return str(binding(text, dict(values)))


def placeholder_input_names(texts: Sequence[str]) -> tuple[str, ...]:
    """Return deterministic Jinja-safe input names for placeholder texts."""
    binding = require_rust_binding("placeholder_input_names")
    return tuple(str(item) for item in binding(list(texts)))


def _field_from_dict(payload: dict[str, Any]) -> RawPlaceholderField:
    return RawPlaceholderField(
        text=str(payload["text"]),
        occurrences=int(payload["occurrences"]),
        context=str(payload["context"]),
    )
