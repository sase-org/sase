"""TIMESTAMPS field utilities for ChangeSpec lifecycle audit trail."""

from .formatting import format_timestamps_field
from .recording import add_timestamp_entry_atomic

__all__ = [
    "add_timestamp_entry_atomic",
    "format_timestamps_field",
]
