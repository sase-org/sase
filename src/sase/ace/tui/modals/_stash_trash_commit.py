"""Stash → Trash commit preview and outcome text.

Private home of the shared Trash-commit helpers needed by both the stash
controller and the app-layer Trash flow. The preview type carries a public
name so both consumers can reference it without a private cross-module
import.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.core.prompt_stash_wire import PromptStashEntryWire


#: Recovery hint appended to every permanent-deletion confirmation and
#: toast. The stash archive keeps every removed row, so even confirmed
#: purges, evictions, and in-place deletes stay recoverable.
STASH_ARCHIVE_RECOVERY_HINT = (
    "Drafts stay recoverable with `sase prompt stash-archive`."
)


@dataclass(frozen=True, slots=True)
class TrashCommitPreview:
    """Preview of a staged Stash → Trash commit.

    ``expected_evictions`` is the permanent-loss count the batch would cause
    under the current limit (``max(0, trash_count + marked - limit)``),
    because other processes may change Trash between preview and commit the
    host re-reads the Rust outcome for the actual evictions. ``pinned_ids``
    records which marked rows are pinned; pinned rows move to Trash like any
    other row and stay pinned inside the trash record.
    """

    marked_ids: tuple[str, ...]
    pinned_ids: tuple[str, ...]
    expected_evictions: int
    trash_count: int
    trash_limit: int


def preview_trash_commit(
    marked_ids: list[str],
    entries: list[PromptStashEntryWire],
    *,
    trash_count: int,
    trash_limit: int,
) -> TrashCommitPreview:
    """Compute the move preview for sending marked rows to Trash.

    Stale IDs (absent from *entries*) are dropped: unknown IDs are no-ops.
    """
    live = {entry.id for entry in entries}
    pinned = {entry.id for entry in entries if entry.pinned}
    marked = [entry_id for entry_id in marked_ids if entry_id in live]
    pinned_marks = tuple(entry_id for entry_id in marked if entry_id in pinned)
    expected = max(0, trash_count + len(marked) - trash_limit) if trash_limit > 0 else 0
    return TrashCommitPreview(
        marked_ids=tuple(marked),
        pinned_ids=pinned_marks,
        expected_evictions=expected,
        trash_count=trash_count,
        trash_limit=trash_limit,
    )


def trash_outcome_text(moved: int, evicted: list[str]) -> str:
    """Return the success summary naming the actual Trash evictions."""
    noun = "draft" if moved == 1 else "drafts"
    message = f"Moved {moved} {noun} to Trash"
    if evicted:
        lost = len(evicted)
        noun_lost = "draft" if lost == 1 else "drafts"
        message += (
            f" (permanently deleted {lost} oldest {noun_lost}: {', '.join(evicted)}). "
            f"{STASH_ARCHIVE_RECOVERY_HINT}"
        )
    return message
