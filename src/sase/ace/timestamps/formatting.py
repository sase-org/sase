"""Formatting utilities for TIMESTAMPS field serialization."""

from sase.ace.changespec.models import TimestampEntry

# Event type keywords are right-padded to 7 chars for column alignment
_EVENT_WIDTH = 7


def format_timestamps_field(entries: list[TimestampEntry]) -> str:
    """Serialize a list of TimestampEntry objects to .gp file format.

    Args:
        entries: List of TimestampEntry objects.

    Returns:
        Formatted string including the ``TIMESTAMPS:`` header and all entries,
        ready for insertion into a .gp file.
    """
    lines = ["TIMESTAMPS:\n"]
    for entry in entries:
        padded_event = entry.event_type.ljust(_EVENT_WIDTH)
        lines.append(f"  [{entry.timestamp}] {padded_event}{entry.detail}\n")
    return "".join(lines)
