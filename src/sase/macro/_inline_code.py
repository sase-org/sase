"""Python offset adapter for the core inline-code range scanner."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import cache
from typing import Any

from ._utf8_offsets import (
    byte_offsets_to_character_offsets as _byte_offsets_to_character_offsets,
    character_offsets_to_byte_offsets as _character_offsets_to_byte_offsets,
)


def inline_code_spans(
    text: str,
    *,
    masked_ranges: Iterable[tuple[int, int]] = (),
) -> list[tuple[int, int]]:
    """Return matched single-line backtick spans as character offsets.

    The Rust primitive owns delimiter matching and reports UTF-8 byte offsets.
    This adapter is the sole conversion point between those offsets and the
    absolute character offsets used by Python and Textual consumers.
    """
    if "`" not in text:
        return []

    character_masks = _normalized_character_ranges(masked_ranges, len(text))
    if text.isascii():
        return [
            (int(start), int(end)) for start, end in _scanner()(text, character_masks)
        ]

    character_to_byte = _character_offsets_to_byte_offsets(
        text,
        _range_endpoints(character_masks),
    )
    byte_masks = [
        (character_to_byte[start], character_to_byte[end])
        for start, end in character_masks
    ]
    byte_ranges = _scanner()(text, byte_masks)
    if not byte_ranges:
        return []
    byte_to_character = _byte_offsets_to_character_offsets(
        text,
        _range_endpoints((int(start), int(end)) for start, end in byte_ranges),
    )
    return [
        (byte_to_character[int(start)], byte_to_character[int(end)])
        for start, end in byte_ranges
    ]


def _range_endpoints(ranges: Iterable[tuple[int, int]]) -> list[int]:
    offsets: list[int] = []
    for start, end in ranges:
        offsets.extend((start, end))
    return offsets


def _normalized_character_ranges(
    ranges: Iterable[tuple[int, int]],
    text_length: int,
) -> list[tuple[int, int]]:
    normalized: list[tuple[int, int]] = []
    for start, end in ranges:
        start = max(0, min(start, text_length))
        end = max(0, min(end, text_length))
        if end > start:
            normalized.append((start, end))
    return normalized


@cache
def _scanner() -> Callable[..., Any]:
    from sase.core.rust import require_rust_binding

    return require_rust_binding("inline_code_ranges")


__all__ = ["inline_code_spans"]
