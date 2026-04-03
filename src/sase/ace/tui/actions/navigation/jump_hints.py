"""Helpers for one-key jump-to-entry hint assignment."""

JUMP_HINT_CHARS = "1234567890abcdefghijklmnopqrstuvwxyz"


def build_jump_hint_maps(indices: list[int]) -> tuple[dict[str, int], dict[int, str]]:
    """Build hint->index and index->hint mappings for visible entries."""
    hint_to_index: dict[str, int] = {}
    index_to_hint: dict[int, str] = {}
    for hint, idx in zip(JUMP_HINT_CHARS, indices, strict=False):
        hint_to_index[hint] = idx
        index_to_hint[idx] = hint
    return hint_to_index, index_to_hint
