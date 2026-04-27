"""Identity-preserving selection restoration after list rebuilds.

Every list-bearing tab in the ace TUI must satisfy this invariant after
any data-source rebuild: *the cursor lands on the same logical entry the
user had selected, or on the nearest valid neighbor if that entry is
gone.* :func:`restore_selection_by_identity` is the one helper that
encodes that rule, so each rebuild path can stop reinventing it.

Algorithm (in priority order):

1. If ``prior_identity`` is found in ``new_items``, return its index
   (identity restoration).
2. Else if ``prior_visual_row`` is in ``[0, len(new_items)-1]``, clamp
   to it (nearest-neighbor: the same visible row position now points at
   whichever entry slid into the previous selection's slot).
3. Else fall back to ``0`` when the list is non-empty, otherwise ``0``
   for an empty list (caller is expected to gate widget updates by
   length).

The helper deliberately does *not* mutate any state — callers wire the
returned index into ``current_idx`` / per-tab saved-position fields
themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence


def restore_selection_by_identity[T, K](
    new_items: Sequence[T],
    *,
    prior_identity: K | None,
    prior_visual_row: int | None,
    identity_fn: Callable[[T], K],
) -> int:
    """Return the row index to focus in ``new_items`` after a rebuild.

    Args:
        new_items: The freshly-rebuilt sequence the caller is about to
            display.
        prior_identity: The identity of the entry that was selected
            *before* the rebuild, or ``None`` when nothing was
            selected.
        prior_visual_row: The visible row index the cursor was on
            before the rebuild, used as a deterministic neighbor
            fallback when the prior identity disappeared.
        identity_fn: Callable that maps an item to its stable identity
            key. Identity types differ per tab (``str`` for ChangeSpec
            name, ``tuple`` for Agent identity, etc.) so this is
            parameterized.

    Returns:
        The row index in ``new_items`` to focus. Always in
        ``[0, len(new_items))`` when ``new_items`` is non-empty;
        returns ``0`` for an empty list (callers should clamp/gate).
    """
    if not new_items:
        return 0

    if prior_identity is not None:
        for idx, item in enumerate(new_items):
            if identity_fn(item) == prior_identity:
                return idx

    if prior_visual_row is not None:
        clamped = max(0, min(prior_visual_row, len(new_items) - 1))
        return clamped

    return 0
