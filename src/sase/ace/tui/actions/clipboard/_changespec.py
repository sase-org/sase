"""Legacy aliases for patch clipboard actions."""

from sase.project_display_names import humanize_cl_name

from ._delivery import schedule_copy_delivery
from ._patch import ClipboardPatchMixin

__all__ = [
    "ClipboardPatchMixin",
    "humanize_cl_name",
    "schedule_copy_delivery",
]
