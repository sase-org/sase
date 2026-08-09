"""Legacy aliases for patch list helper functions."""

from ._patch_list_helpers import (
    calculate_entry_display_width,
    compute_mentor_stats,
    format_patch_option,
    get_status_indicator,
    row_signature,
)

format_changespec_option = format_patch_option  # legacy compatibility alias

__all__ = [
    "calculate_entry_display_width",
    "compute_mentor_stats",
    "format_changespec_option",  # legacy compatibility alias
    "get_status_indicator",
    "row_signature",
]
