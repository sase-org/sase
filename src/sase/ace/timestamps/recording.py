"""Atomic recording of TIMESTAMPS entries into Patch .gp files."""

import re
import sys

from sase.ace.patch.locking import patch_lock, write_patch_atomic
from sase.core.time import generate_timestamp


# Event type keywords are right-padded to 7 chars for column alignment
_EVENT_WIDTH = 7


def format_timestamp_entry_line(event_type: str, detail: str) -> str:
    """Format a single TIMESTAMPS entry line with the current time.

    Returns a string like ``  [260330_120000] COMMIT  (1)\\n``.
    """
    ts = generate_timestamp()
    padded_event = event_type.ljust(_EVENT_WIDTH)
    return f"  [{ts}] {padded_event}{detail}\n"


def add_timestamp_entry_atomic(
    project_file: str,
    cl_name: str,
    event_type: str,
    detail: str,
) -> bool:
    """Append a TIMESTAMPS entry to a Patch, creating the section if needed.

    Acquires the patch lock, reads the file, finds (or creates) the
    TIMESTAMPS section for *cl_name*, appends a new entry line, and writes
    atomically.

    Args:
        project_file: Path to the ``.gp`` file.
        cl_name: NAME of the target Patch.
        event_type: One of ``COMMIT``, ``STATUS``, ``SYNC``, ``REWORD``,
            ``REWIND``, ``RENAME``, ``REBASE``.
        detail: Event-specific detail string.

    Returns:
        True on success, False on any error.
    """
    entry_line = format_timestamp_entry_line(event_type, detail)

    try:
        with patch_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            insert_idx = _find_timestamps_insert_point(lines, cl_name)
            if insert_idx is None:
                return False

            lines.insert(insert_idx, entry_line)

            write_patch_atomic(
                project_file,
                "".join(lines),
                f"Add {event_type} timestamp for {cl_name}",
            )
        return True
    except Exception as exc:
        print(f"[sase] add_timestamp_entry_atomic failed: {exc}", file=sys.stderr)
        return False


def _find_timestamps_insert_point(lines: list[str], cl_name: str) -> int | None:
    """Find (or create) the TIMESTAMPS section and return the insert index.

    If the section already exists, returns the index after the last entry.
    If it doesn't exist, inserts a ``TIMESTAMPS:`` header at the end of the
    Patch (before the two-blank-line separator) and returns the index
    after it.

    The caller must hold the patch lock and the *lines* list is mutated
    in-place when a new section header is added.
    """
    in_target = False
    timestamps_header_idx = -1
    last_timestamps_entry_idx = -1
    patch_end_idx = -1
    consecutive_blanks = 0

    for i, line in enumerate(lines):
        if line.startswith("NAME: "):
            current_name = line[6:].strip()
            if in_target:
                # Hit the next Patch — use the end marker we have
                patch_end_idx = i
                break
            in_target = current_name == cl_name
            consecutive_blanks = 0
        elif in_target:
            stripped = line.strip()
            if stripped == "":
                consecutive_blanks += 1
                if consecutive_blanks >= 2:
                    patch_end_idx = i - 1  # before the blank lines
                    break
            else:
                consecutive_blanks = 0

            if line.startswith("TIMESTAMPS:"):
                timestamps_header_idx = i
            elif timestamps_header_idx >= 0 and line.startswith("  "):
                # Lines belonging to the TIMESTAMPS section
                if re.match(r"^\s+(?:\[\d{4}-\d{2}-\d{2}|\[?\d{6}_\d{6})", line):
                    last_timestamps_entry_idx = i

    if not in_target and timestamps_header_idx < 0:
        return None  # Patch not found

    # Handle end of file
    if in_target and patch_end_idx < 0:
        patch_end_idx = len(lines)

    if timestamps_header_idx >= 0:
        # Section exists — insert after the last entry (or after the header)
        if last_timestamps_entry_idx >= 0:
            return last_timestamps_entry_idx + 1
        return timestamps_header_idx + 1

    # Section doesn't exist — create it at the end of the Patch
    insert_at = patch_end_idx
    lines.insert(insert_at, "TIMESTAMPS:\n")
    return insert_at + 1
