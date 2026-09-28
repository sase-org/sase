"""Stash → Trash commit preview and confirmation text.

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
    need explicit confirmation before a pinned row may move.
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
    """Compute the confirmation preview for moving marked rows to Trash.

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


def trash_commit_confirm_text(preview: TrashCommitPreview) -> str:
    """Return the explicit confirmation message for a Stash → Trash commit."""
    count = len(preview.marked_ids)
    noun = "draft" if count == 1 else "drafts"
    lines = [f"Move {count} {noun} to Trash?"]
    if preview.pinned_ids:
        pinned = len(preview.pinned_ids)
        noun_pinned = "is pinned" if pinned == 1 else "are pinned"
        lines.append(f"{pinned} marked {noun_pinned}: restoring keeps them stashed.")
    if preview.expected_evictions:
        lost = preview.expected_evictions
        noun_lost = "draft" if lost == 1 else "drafts"
        lines.append(
            f"Trash holds {preview.trash_count} of {preview.trash_limit}: "
            f"{lost} oldest {noun_lost} will be permanently deleted. "
            f"{STASH_ARCHIVE_RECOVERY_HINT}"
        )
    return "\n".join(lines)


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
