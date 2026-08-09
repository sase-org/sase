"""Legacy aliases for patch clipboard actions."""

from sase.project_display_names import humanize_cl_name

from ._delivery import schedule_copy_delivery
from ._patch import ClipboardPatchMixin

ClipboardChangeSpecMixin = ClipboardPatchMixin

__all__ = [
    "ClipboardChangeSpecMixin",
    "humanize_cl_name",
    "schedule_copy_delivery",
]
