"""Legacy section parser names backed by :mod:`sase.ace.patch.section_parsers`."""

from sase.ace.patch.section_parsers import (
    CommitEntryDict,
    StitchEntryDict,
    build_commit_entry,
    build_stitch,
    parse_comments_line,
    parse_commits_line,
    parse_deltas_line,
    parse_hooks_line,
    parse_mentors_line,
    parse_stitches_line,
    parse_timestamps_line,
)

__all__ = [
    "CommitEntryDict",
    "StitchEntryDict",
    "build_commit_entry",
    "build_stitch",
    "parse_comments_line",
    "parse_commits_line",
    "parse_deltas_line",
    "parse_hooks_line",
    "parse_mentors_line",
    "parse_stitches_line",
    "parse_timestamps_line",
]
