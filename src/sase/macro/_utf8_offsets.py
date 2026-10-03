"""Sparse UTF-8 offset conversion helpers for Rust scanner adapters."""

from __future__ import annotations

from collections.abc import Iterable


def byte_offsets_to_character_offsets(
    text: str,
    offsets: Iterable[int],
) -> dict[int, int]:
    """Map selected UTF-8 byte offsets to Python character offsets."""
    targets = sorted(set(offsets))
    if not targets:
        return {}
    if text.isascii():
        return {offset: offset for offset in targets}

    data = text.encode("utf-8")
    data_len = len(data)
    mapping: dict[int, int] = {}
    byte_cursor = 0
    character_cursor = 0
    for offset in targets:
        if offset < 0 or offset > data_len:
            mapping[offset] = offset
            continue
        try:
            segment = data[byte_cursor:offset].decode("utf-8")
        except UnicodeDecodeError:
            mapping[offset] = offset
            continue
        character_cursor += len(segment)
        byte_cursor = offset
        mapping[offset] = character_cursor
    return mapping


def character_offsets_to_byte_offsets(
    text: str,
    offsets: Iterable[int],
) -> dict[int, int]:
    """Map selected Python character offsets to UTF-8 byte offsets."""
    targets = sorted(set(offsets))
    if not targets:
        return {}
    if text.isascii():
        return {offset: offset for offset in targets}

    text_len = len(text)
    mapping: dict[int, int] = {}
    character_cursor = 0
    byte_cursor = 0
    for offset in targets:
        if offset < 0 or offset > text_len:
            mapping[offset] = offset
            continue
        byte_cursor += len(text[character_cursor:offset].encode("utf-8"))
        character_cursor = offset
        mapping[offset] = byte_cursor
    return mapping


__all__ = [
    "byte_offsets_to_character_offsets",
    "character_offsets_to_byte_offsets",
]
