"""Functions for adding COMMITS entries to ChangeSpecs."""

import os
import re

from sase.sase_utils import generate_timestamp
from sase.spec_writer.client import make_request, submit_spec_write_and_wait
from sase.spec_writer.models import OperationType


def _extract_timestamp_from_chat_path(chat_path: str) -> str | None:
    """Extract the timestamp from a chat file path.

    Chat filenames have format: <branch>-<workflow>[-<agent>]-<timestamp>.md
    The timestamp is always the last 13 characters before the .md extension.

    Args:
        chat_path: Path to the chat file (e.g., "~/.sase/chats/mybranch-crs-251227_143052.md")

    Returns:
        The timestamp string (e.g., "251227_143052") or None if extraction fails.
    """
    if not chat_path or not chat_path.endswith(".md"):
        return None

    # Get the basename and remove .md extension
    basename = os.path.basename(chat_path)
    name_without_ext = basename[:-3]  # Remove ".md"

    # Timestamp is last 13 characters (YYmmdd_HHMMSS format)
    if len(name_without_ext) < 13:
        return None

    timestamp = name_without_ext[-13:]

    # Validate format: 6 digits + underscore + 6 digits
    if (
        len(timestamp) == 13
        and timestamp[6] == "_"
        and timestamp[:6].isdigit()
        and timestamp[7:].isdigit()
    ):
        return timestamp

    return None


def format_chat_line_with_duration(
    chat_path: str, end_timestamp: str | None = None
) -> str:
    """Format a CHAT line with optional duration suffix.

    Args:
        chat_path: Path to the chat file.
        end_timestamp: Optional end timestamp (YYmmdd_HHMMSS format) for duration
            calculation. If not provided, uses current time.

    Returns:
        Formatted CHAT line like "      | CHAT: <path> (1m23s)\n" or
        "      | CHAT: <path>\n" if duration cannot be calculated.
    """
    from sase.ace.hooks.timestamps import (
        calculate_duration_from_timestamps,
        format_duration,
    )

    timestamp = _extract_timestamp_from_chat_path(chat_path)
    if timestamp is None:
        return f"      | CHAT: {chat_path}\n"

    # Use provided end_timestamp, or fall back to current time
    if end_timestamp is not None:
        current_timestamp = end_timestamp
    else:
        current_timestamp = generate_timestamp()

    # Calculate duration
    duration_seconds = calculate_duration_from_timestamps(timestamp, current_timestamp)
    if duration_seconds is None or duration_seconds < 0:
        return f"      | CHAT: {chat_path}\n"

    duration_str = format_duration(duration_seconds)
    return f"      | CHAT: {chat_path} ({duration_str})\n"


def get_next_commit_number(lines: list[str], cl_name: str) -> int:
    """Get the next commit entry number for a ChangeSpec.

    Only counts regular entries (not proposed entries with letter suffixes).

    Args:
        lines: Lines from the project file.
        cl_name: The CL name to find.

    Returns:
        The next commit entry number (1 if no entries exist).
    """
    in_target_changespec = False
    in_commits = False
    max_number = 0

    for line in lines:
        if line.startswith("NAME: "):
            current_name = line[6:].strip()
            in_target_changespec = current_name == cl_name
            in_commits = False
        elif in_target_changespec:
            if line.startswith("COMMITS:"):
                in_commits = True
            elif line.startswith(
                (
                    "NAME:",
                    "DESCRIPTION:",
                    "PARENT:",
                    "CL:",
                    "STATUS:",
                    "TEST TARGETS:",
                    "KICKSTART:",
                )
            ):
                in_commits = False
                if line.startswith("NAME:"):
                    in_target_changespec = False
            elif in_commits:
                # Check for regular commit entry: (N) Note text (no letter suffix)
                # Skip proposed entries like (2a)
                match = re.match(r"^\s*\((\d+)\)\s+", line)
                if match:
                    num = int(match.group(1))
                    max_number = max(max_number, num)

    return max_number + 1


def get_next_proposal_letter(lines: list[str], cl_name: str, base_number: int) -> str:
    """Get the next available proposal letter for a base number.

    Args:
        lines: Lines from the project file.
        cl_name: The CL name to find.
        base_number: The base commit number (e.g., 2 for 2a, 2b, etc.).

    Returns:
        The next available letter ('a' if none exist, 'b' if 'a' exists, etc.).
    """
    in_target_changespec = False
    in_commits = False
    used_letters: set[str] = set()

    for line in lines:
        if line.startswith("NAME: "):
            current_name = line[6:].strip()
            in_target_changespec = current_name == cl_name
            in_commits = False
        elif in_target_changespec:
            if line.startswith("COMMITS:"):
                in_commits = True
            elif line.startswith(
                (
                    "NAME:",
                    "DESCRIPTION:",
                    "PARENT:",
                    "CL:",
                    "STATUS:",
                    "TEST TARGETS:",
                    "KICKSTART:",
                )
            ):
                in_commits = False
                if line.startswith("NAME:"):
                    in_target_changespec = False
            elif in_commits:
                # Check for proposed entry: (Na) where N is base_number
                match = re.match(r"^\s*\((\d+)([a-z])\)\s+", line)
                if match and int(match.group(1)) == base_number:
                    used_letters.add(match.group(2))

    # Find the first unused letter
    for letter in "abcdefghijklmnopqrstuvwxyz":
        if letter not in used_letters:
            return letter

    # Should never happen in practice (26 proposals max)
    raise ValueError(f"No available proposal letters for base number {base_number}")


def add_proposed_commit_entry(
    project_file: str,
    cl_name: str,
    note: str,
    diff_path: str | None = None,
    chat_path: str | None = None,
    end_timestamp: str | None = None,
) -> tuple[bool, str | None]:
    """Add a proposed COMMITS entry to a ChangeSpec.

    Proposed entries have format (Na) where N is the last regular entry number.
    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the project file.
        cl_name: The CL name to add commit entry to.
        note: The note for this commit entry.
        diff_path: Optional path to the diff file.
        chat_path: Optional path to the chat file.
        end_timestamp: Optional end timestamp for duration calculation.

    Returns:
        Tuple of (success, entry_id). entry_id is like "2a" if successful.
    """
    try:
        request = make_request(
            project_file,
            OperationType.ADD_PROPOSED_COMMIT_ENTRY,
            {
                "cl_name": cl_name,
                "note": note,
                "diff_path": diff_path,
                "chat_path": chat_path,
                "end_timestamp": end_timestamp,
            },
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        if response.success and response.result:
            return True, response.result.get("entry_id")
        return response.success, None
    except Exception:
        return False, None


def add_commit_entry(
    project_file: str,
    cl_name: str,
    note: str,
    diff_path: str | None = None,
    chat_path: str | None = None,
    end_timestamp: str | None = None,
) -> bool:
    """Add a new COMMITS entry to a ChangeSpec.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the project file.
        cl_name: The CL name to add commit entry to.
        note: The note for this commit entry.
        diff_path: Optional path to the diff file.
        chat_path: Optional path to the chat file.
        end_timestamp: Optional end timestamp for duration calculation.

    Returns:
        True if successful, False otherwise.
    """
    try:
        request = make_request(
            project_file,
            OperationType.ADD_COMMIT_ENTRY,
            {
                "cl_name": cl_name,
                "note": note,
                "diff_path": diff_path,
                "chat_path": chat_path,
                "end_timestamp": end_timestamp,
            },
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False
