"""Patch section entry data models."""

from dataclasses import dataclass


@dataclass
class CommentEntry:
    """Represents a single entry in the COMMENTS field.

    Format in file:
      [critique] ~/.sase/comments/<name>-critique-YYmmdd_HHMMSS.json
      [critique] ~/.sase/comments/<name>-critique-YYmmdd_HHMMSS.json - (SUFFIX)

    The optional suffix can be:
    - A timestamp (YYmmdd_HHMMSS) indicating a CRS workflow is running
    - "Unresolved Critique Comments" indicating CRS completed but comments remain
    - "ZOMBIE" indicating a stale CRS run (>2h old timestamp)

    Note: The suffix stores just the message (e.g., "ZOMBIE"), and the
    "!: " prefix is added when formatting for display/storage.
    """

    reviewer: str  # The comment type (e.g., "critique")
    file_path: str  # Full path to the comments JSON file
    suffix: str | None = (
        None  # e.g., "YYmmdd_HHMMSS", "ZOMBIE", "Unresolved Critique Comments"
    )
    suffix_type: str | None = None  # "error" for (!:), None for plain


@dataclass
class DeltaLineStats:
    """Represents line-level stats for a DELTAS entry.

    The counts are semantic counts derived from raw VCS added/deleted totals:
    paired additions/deletions become ``modified`` lines, and only unpaired
    totals remain as added/removed.
    """

    added: int = 0
    modified: int = 0
    removed: int = 0
    binary: bool = False


@dataclass
class DeltaEntry:
    """Represents a single entry in the DELTAS field.

    Format in file (single-character status glyph + path):
      + path/to/added_file.py
          | LINES: +10
      ~ path/to/modified_file.py
          | LINES: +2 ~3 -1
      - path/to/deleted_file.py
          | LINES: -5

    The on-disk glyphs map to long-form change types stored on the dataclass:
      "+" -> "A" (added)
      "~" -> "M" (modified)
      "-" -> "D" (deleted)
    """

    path: str
    change_type: str  # "A" (added), "M" (modified), "D" (deleted)
    line_stats: DeltaLineStats | None = None


@dataclass
class TimestampEntry:
    """Represents a single entry in the TIMESTAMPS field.

    Format in file:
      [YYYY-MM-DD HH:MM:SS] COMMIT  (1)
      [YYYY-MM-DD HH:MM:SS] STATUS  WIP -> Draft
      [YYYY-MM-DD HH:MM:SS] SYNC    (2)
      [YYYY-MM-DD HH:MM:SS] REWORD  description
      [YYYY-MM-DD HH:MM:SS] REWIND  (3)
      [YYYY-MM-DD HH:MM:SS] RENAME  old-name -> new-name
      [YYYY-MM-DD HH:MM:SS] REBASE  old-parent -> new-parent
    """

    timestamp: str  # "YYYY-MM-DD HH:MM:SS"
    # "COMMIT", "STATUS", "SYNC", "REWORD", "REWIND", "RENAME", "REBASE"
    event_type: str
    detail: str  # Event-specific detail string
