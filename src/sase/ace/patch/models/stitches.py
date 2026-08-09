"""Stitch data models and identifiers."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class Stitch:
    """Represents a single entry in the STITCHES/COMMITS field.

    Regular entries have format: (N) Note text
    Proposed entries have format: (Na) Note text (where 'a' is a lowercase letter)
    Entries can have optional suffix: (Na) Note text - (!: MSG) or - (MSG)
    """

    number: int
    note: str
    chat: str | None = None
    diff: str | None = None
    plan: str | None = None
    proposal_letter: str | None = None  # e.g., 'a', 'b', 'c' for proposed entries
    suffix: str | None = None  # e.g., "NEW PROPOSAL" (message without prefix)
    suffix_type: str | None = None  # "error" for !:, None for plain
    body: list[str] | None = (
        None  # Multi-line note body (empty strings = paragraph breaks)
    )

    @property
    def is_proposed(self) -> bool:
        """Check if this is a proposed (not yet accepted) stitch."""
        return self.proposal_letter is not None

    @property
    def display_number(self) -> str:
        """Get the display string for this entry's number (e.g., '2' or '2a')."""
        if self.proposal_letter:
            return f"{self.number}{self.proposal_letter}"
        return str(self.number)


CommitEntry = Stitch
StitchDict = dict[str, str | int | None]


def parse_stitch_id(stitch_id: str) -> tuple[int, str]:
    """Parse a stitch ID into (number, letter) for sorting.

    Args:
        stitch_id: The stitch ID string (e.g., "1", "1a", "2").

    Returns:
        Tuple of (number, letter) where letter is "" for regular entries.
        E.g., "1" -> (1, ""), "1a" -> (1, "a"), "2" -> (2, "").
    """
    # Match digit(s) optionally followed by a letter
    match = re.match(r"^(\d+)([a-z]?)$", stitch_id)
    if match:
        return int(match.group(1)), match.group(2)
    # Fallback for unexpected format
    return 0, stitch_id


parse_commit_entry_id = parse_stitch_id
