"""Legacy aliases for patch stitch section rendering."""

from .stitches_builder import (
    build_stitches_section,
    should_show_stitches_drawers,
    truncate_note,
)

_should_show_commits_drawers = should_show_stitches_drawers
_truncate_note = truncate_note
build_commits_section = build_stitches_section

__all__ = [
    "_should_show_commits_drawers",
    "_truncate_note",
    "build_commits_section",
]
