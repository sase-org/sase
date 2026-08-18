"""Shared selector-detection glue for the Models panel.

Thin presentation helpers over the existing ``llm_provider`` selector API so
the alias Edit and temporary-Override flows share one detection point instead
of each re-deriving selector syntax and member safety on their own.  No
selector semantics live here — parsing stays in
:mod:`sase.llm_provider.load_balancing` and final validation stays in
:func:`sase.llm_provider.model_alias_resolution.validate_model_alias_selector_value`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sase.llm_provider.load_balancing import (
    ModelAliasSelector,
    ModelAliasSelectorError,
    ModelAliasSelectorMode,
    parse_model_alias_selector,
)

from .model_picker_modal import AliasSelectionContext, alias_reference_rejection

__all__ = [
    "compose_selector",
    "member_rejection",
    "parse_selector_for_display",
]


@dataclass(frozen=True)
class _SelectorParseResult:
    """Outcome of parsing a Models-panel custom-input value for selectors.

    Exactly one of ``selector`` / ``error`` is set unless the value has no
    selector syntax at all, in which case both are ``None``.
    """

    selector: ModelAliasSelector | None
    error: str | None


def parse_selector_for_display(value: str) -> _SelectorParseResult:
    """Parse *value*, turning a raised error into a user-facing message."""
    try:
        selector = parse_model_alias_selector(value)
    except ModelAliasSelectorError as exc:
        return _SelectorParseResult(None, str(exc))
    return _SelectorParseResult(selector, None)


def member_rejection(context: AliasSelectionContext | None, member: str) -> str | None:
    """Return a concise rejection reason for a single selector *member*."""
    return alias_reference_rejection(context, member)


def compose_selector(
    mode: ModelAliasSelectorMode,
    members: Sequence[str],
    weights: Sequence[int] | None = None,
) -> str:
    """Return the canonical ``A | B`` / ``A || B`` spelling for *members*."""
    return ModelAliasSelector(
        mode=mode,
        members=tuple(members),
        weights=() if weights is None else tuple(weights),
    ).normalized
