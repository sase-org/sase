"""Commits entry utilities for hooks."""

from ..patch import Patch, Stitch


def get_last_history_entry_id(patch: Patch) -> str | None:
    """Get the ID of the last COMMITS entry (e.g., '1', '1a', '2').

    Args:
        patch: The Patch to get the last entry ID from.

    Returns:
        The last history entry ID or None if no history.
    """
    if not patch.commits:
        return None

    return patch.commits[-1].display_number


def get_last_history_entry(patch: Patch) -> Stitch | None:
    """Get the last COMMITS entry.

    Args:
        patch: The Patch to get the last entry from.

    Returns:
        The last Stitch or None if no history.
    """
    if not patch.commits:
        return None

    return patch.commits[-1]


def get_last_accepted_history_entry_id(patch: Patch) -> str | None:
    """Get the ID of the last accepted (all-numeric) COMMITS entry.

    This skips proposal entries like '2a' and returns the last entry
    with an all-numeric ID like '2'.

    Args:
        patch: The Patch to get the last accepted entry ID from.

    Returns:
        The last accepted history entry ID or None if no history.
    """
    if not patch.commits:
        return None

    # Iterate in reverse to find the last all-numeric entry
    for entry in reversed(patch.commits):
        if entry.display_number.isdigit():
            return entry.display_number

    return None


def is_proposal_entry(entry_id: str) -> bool:
    """Check if a history entry ID is a proposal (ends with a letter like '2a')."""
    return bool(entry_id) and entry_id[-1].isalpha()


def get_history_entry_by_id(patch: Patch, entry_id: str) -> Stitch | None:
    """Get the Stitch with the given display number.

    Args:
        patch: The Patch to search.
        entry_id: The display number to find (e.g., "1", "2a").

    Returns:
        The matching Stitch, or None if not found.
    """
    if not patch.commits:
        return None
    for entry in patch.commits:
        if entry.display_number == entry_id:
            return entry
    return None
