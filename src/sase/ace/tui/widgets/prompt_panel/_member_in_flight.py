"""Shared in-flight styling for jump-panel targets and roster rows."""

from __future__ import annotations

from sase.agent.status_buckets import IN_FLIGHT_STATUS_BUCKETS

#: Softly tinted pill backgrounds, derived by blending the bucket's status
#: color about 22% over the detail column's background (``#101010``).
IN_FLIGHT_RUNNING_TINT = "#453C0D"  # dark olive gold
IN_FLIGHT_STARTING_TINT = "#2A3C45"  # dark slate blue

_IN_FLIGHT_TINTS: dict[str, str] = {
    "Running": IN_FLIGHT_RUNNING_TINT,
    "Starting": IN_FLIGHT_STARTING_TINT,
}

#: House agent-name gold, bolded, used for lit labels inside the pill.
IN_FLIGHT_LABEL_COLOR = "#FFD700"

_MEMBER_STATUS_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #FFD700",
    "Queued": "bold #5F87FF",
    "Waiting": "bold #AF87FF",
    "Failed": "bold #FF5F5F",
    "Done": "bold #5FD75F",
}


def member_status_style(bucket: str) -> str:
    """Return the roster status color for a status bucket."""
    return _MEMBER_STATUS_STYLES.get(bucket, "bold #FFFFFF")


def is_in_flight_jump_bucket(
    bucket: str | None,
    *,
    dismissed: bool = False,
) -> bool:
    """Return whether a jump target with ``bucket`` renders lit."""
    if dismissed or bucket is None:
        return False
    return bucket in IN_FLIGHT_STATUS_BUCKETS


def in_flight_tint(bucket: str) -> str:
    """Return the pill tint for ``bucket``, defaulting to the Running tint."""
    return _IN_FLIGHT_TINTS.get(bucket, IN_FLIGHT_RUNNING_TINT)


def in_flight_label_style(bucket: str) -> str:
    """Return the bold gold-on-tint style for a lit label."""
    return f"bold {IN_FLIGHT_LABEL_COLOR} on {in_flight_tint(bucket)}"


def in_flight_glyph_style(bucket: str) -> str:
    """Return the status-color-on-tint style for a lit glyph."""
    return f"{member_status_style(bucket)} on {in_flight_tint(bucket)}"


def in_flight_pad_style(bucket: str) -> str:
    """Return the tint-background style for pill padding spaces."""
    return f"on {in_flight_tint(bucket)}"


__all__ = [
    "IN_FLIGHT_LABEL_COLOR",
    "IN_FLIGHT_RUNNING_TINT",
    "IN_FLIGHT_STARTING_TINT",
    "in_flight_glyph_style",
    "in_flight_label_style",
    "in_flight_pad_style",
    "in_flight_tint",
    "is_in_flight_jump_bucket",
    "member_status_style",
]
