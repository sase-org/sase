"""Section-specific parsers for ChangeSpec fields."""

import re
from typing import TypedDict

from ..display_helpers import is_entry_ref_suffix
from ..hooks.test_targets import expand_test_target_shorthand
from .models import (
    CommentEntry,
    CommitEntry,
    DeltaEntry,
    DeltaLineStats,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
    TimestampEntry,
)
from .suffix_utils import parse_suffix_prefix


_DELTA_GLYPH_TO_TYPE = {"+": "A", "~": "M", "-": "D"}
_DELTA_LINES_RE = re.compile(r"^\s*(?P<token>[+~\-])(?P<count>\d+)\s*$")


def _parse_delta_line_stats(value: str) -> DeltaLineStats | None:
    """Parse a DELTAS ``LINES`` drawer payload."""
    payload = value.strip()
    if payload == "binary":
        return DeltaLineStats(binary=True)
    if payload in {"0", "0 lines"}:
        return DeltaLineStats()
    if not payload:
        return None

    stats = DeltaLineStats()
    seen = False
    for part in payload.split():
        match = _DELTA_LINES_RE.match(part)
        if not match:
            return None
        count = int(match.group("count"))
        token = match.group("token")
        if token == "+":
            stats.added = count
        elif token == "~":
            stats.modified = count
        else:
            stats.removed = count
        seen = True
    return stats if seen else None


class CommitEntryDict(TypedDict, total=False):
    """Type for in-progress commit entry during parsing."""

    number: int
    note: str
    chat: str | None
    diff: str | None
    plan: str | None
    proposal_letter: str | None
    suffix: str | None
    suffix_type: str | None
    body: list[str] | None


def build_commit_entry(
    entry_dict: CommitEntryDict | dict[str, str | int | None],
) -> CommitEntry:
    """Build a CommitEntry from a dict with proper type handling."""
    number_val = entry_dict.get("number", 0)
    number = int(number_val) if number_val is not None else 0

    note_val = entry_dict.get("note", "")
    note = str(note_val) if note_val is not None else ""

    chat_val = entry_dict.get("chat")
    chat = str(chat_val) if chat_val is not None else None

    diff_val = entry_dict.get("diff")
    diff = str(diff_val) if diff_val is not None else None

    plan_val = entry_dict.get("plan")
    plan = str(plan_val) if plan_val is not None else None

    proposal_letter_val = entry_dict.get("proposal_letter")
    proposal_letter = (
        str(proposal_letter_val) if proposal_letter_val is not None else None
    )

    suffix_val = entry_dict.get("suffix")
    suffix = str(suffix_val) if suffix_val is not None else None

    suffix_type_val = entry_dict.get("suffix_type")
    suffix_type = str(suffix_type_val) if suffix_type_val is not None else None

    body_val = entry_dict.get("body")
    body: list[str] | None = (
        list(body_val) if isinstance(body_val, list) and body_val else None
    )

    return CommitEntry(
        number=number,
        note=note,
        chat=chat,
        diff=diff,
        plan=plan,
        proposal_letter=proposal_letter,
        suffix=suffix,
        suffix_type=suffix_type,
        body=body,
    )


def parse_hooks_line(
    line: str,
    stripped: str,
    current_hook_entry: HookEntry | None,
    hook_entries: list[HookEntry],
) -> tuple[HookEntry | None, list[HookEntry]]:
    """Parse a single line in HOOKS section.

    Args:
        line: The original line (with leading whitespace)
        stripped: The stripped line content
        current_hook_entry: The current hook entry being built (or None)
        hook_entries: List of completed hook entries

    Returns:
        Updated (current_hook_entry, hook_entries) tuple.
    """
    if line.startswith("  ") and not line.startswith("    "):
        # This is a command line (2-space indented, not 4-space)
        # Only if it doesn't start with '[' or '(' (status line markers)
        if not stripped.startswith("[") and not stripped.startswith("("):
            # Save previous hook entry if exists
            if current_hook_entry is not None:
                hook_entries.append(current_hook_entry)
            # Start new hook entry - expand shorthand if needed
            expanded_command = expand_test_target_shorthand(stripped)
            current_hook_entry = HookEntry(command=expanded_command)
    elif line.startswith("      | "):
        # This is a status line (6-space + "| " prefixed)
        # Remove the "| " prefix for regex matching
        status_content = stripped[2:]  # Skip "| " prefix
        # Try new format: (N) [YYmmdd_HHMMSS] STATUS (XmYs) - (SUFFIX)
        # Note: The suffix group uses .+ instead of [^)]+ to handle suffix
        # text that contains literal ")" characters (e.g., AI-generated
        # summaries like "test failed (Exit 3)."). The .+ greedily matches
        # through nested parens, then backtracks to the final ")$".
        new_status_match = re.match(
            r"^\((\d+[a-z]?)\)\s+\[(\d{6})_(\d{6})\]\s*(RUNNING|PASSED|FAILED|DEAD)"
            r"(?:\s+\(([^)]+)\))?(?:\s+-\s+\((.+)\))?$",
            status_content,
        )
        if new_status_match and current_hook_entry is not None:
            # New format with commit entry ID (e.g., "1", "1a", "2")
            commit_num = new_status_match.group(1)
            timestamp = new_status_match.group(2) + "_" + new_status_match.group(3)
            status_val = new_status_match.group(4)
            duration_val = new_status_match.group(5)
            suffix_val = new_status_match.group(6)
            summary_val: str | None = None

            # Check for compound suffix with " | " delimiter
            # Format: (SUFFIX | SUMMARY) or (@: SUFFIX | SUMMARY)
            if suffix_val and " | " in suffix_val:
                parts = suffix_val.split(" | ", 1)
                suffix_val = parts[0]
                summary_val = parts[1] if len(parts) > 1 else None

            # Parse suffix prefix
            parsed = parse_suffix_prefix(suffix_val)
            suffix_val = parsed.value
            suffix_type_val = parsed.suffix_type

            status_line = HookStatusLine(
                commit_entry_num=commit_num,
                timestamp=timestamp,
                status=status_val,
                duration=duration_val,
                suffix=suffix_val,
                suffix_type=suffix_type_val,
                summary=summary_val,
            )
            if current_hook_entry.status_lines is None:
                current_hook_entry.status_lines = []
            current_hook_entry.status_lines.append(status_line)

    return current_hook_entry, hook_entries


def parse_comments_line(
    line: str,
    stripped: str,
    comment_entries: list[CommentEntry],
) -> list[CommentEntry]:
    """Parse a single line in COMMENTS section.

    Args:
        line: The original line (with leading whitespace)
        stripped: The stripped line content
        comment_entries: List of completed comment entries

    Returns:
        Updated comment_entries list.
    """
    if line.startswith("  ") and not line.startswith("    "):
        # This is a comment entry line (2-space indented)
        # Pattern: [reviewer] path or [reviewer] path - (suffix)
        comment_match = re.match(
            r"^\[([^\]]+)\]\s+(\S+)(?:\s+-\s+\(([^)]+)\))?$",
            stripped,
        )
        if comment_match:
            reviewer = comment_match.group(1)
            file_path_val = comment_match.group(2)
            suffix_val = comment_match.group(3)

            # Parse suffix prefix
            parsed = parse_suffix_prefix(suffix_val)
            suffix_val = parsed.value
            comment_suffix_type = parsed.suffix_type

            comment_entries.append(
                CommentEntry(
                    reviewer=reviewer,
                    file_path=file_path_val,
                    suffix=suffix_val,
                    suffix_type=comment_suffix_type,
                )
            )

    return comment_entries


def parse_mentors_line(
    line: str,
    stripped: str,
    current_mentor_entry: MentorEntry | None,
    mentor_entries: list[MentorEntry],
) -> tuple[MentorEntry | None, list[MentorEntry]]:
    """Parse a single line in MENTORS section.

    Args:
        line: The original line (with leading whitespace)
        stripped: The stripped line content
        current_mentor_entry: The current mentor entry being built (or None)
        mentor_entries: List of completed mentor entries

    Returns:
        Updated (current_mentor_entry, mentor_entries) tuple.
    """
    if line.startswith("  ") and not line.startswith("      "):
        # This is an entry line (2-space indented, not 6-space)
        # Pattern: (<id>) <profile1>[x/y] [<profile2>[x/y] ...]
        # Or legacy: (<id>) <profile1> [<profile2> ...]
        entry_match = re.match(r"^\((\d+[a-z]?)\)\s+(.+)$", stripped)
        if entry_match:
            # Save previous entry if exists
            if current_mentor_entry is not None:
                mentor_entries.append(current_mentor_entry)
            # Start new mentor entry
            entry_id = entry_match.group(1)
            profiles_raw = entry_match.group(2)
            # Detect and strip #Draft marker
            is_draft = profiles_raw.rstrip().endswith("#Draft")
            if is_draft:
                profiles_raw = profiles_raw.replace(" #Draft", "").rstrip()
            # Try new format: profile[x/y] (extract just profile names)
            profiles = re.findall(r"(\w+)\[\d+/\d+\]", profiles_raw)
            if not profiles:
                # Fallback: old format without counts
                profiles = profiles_raw.split()
            current_mentor_entry = MentorEntry(
                entry_id=entry_id,
                profiles=profiles,
                status_lines=[],
                is_draft=is_draft,
            )
    elif line.startswith("      | "):
        # This is a status line (6-space + "| " prefixed)
        # Pattern: [timestamp] <profile>:<mentor> - STATUS - (suffix)
        status_content = stripped[2:]  # Skip "| " prefix
        mentor_status_match = re.match(
            r"^(?:\[(\d{6}_\d{6})\]\s+)?([^:]+):(\S+)\s+-\s+"
            r"(STARTING|RUNNING|PASSED|COMMENTED|FAILED|DEAD|KILLED)"
            r"(?:\s+-\s+\(([^)]+)\))?$",
            status_content,
        )
        if mentor_status_match and current_mentor_entry is not None:
            timestamp_val = mentor_status_match.group(1)
            profile_name = mentor_status_match.group(2)
            mentor_name = mentor_status_match.group(3)
            status_val = mentor_status_match.group(4)
            suffix_val = mentor_status_match.group(5)

            # Parse suffix and suffix_type with special handling for mentors
            mentor_suffix_type: str | None = None
            mentor_duration_val: str | None = None
            if suffix_val:
                # First try the standard prefix parsing
                parsed = parse_suffix_prefix(suffix_val)
                if parsed.suffix_type is not None:
                    # Standard prefix found
                    suffix_val = parsed.value
                    mentor_suffix_type = parsed.suffix_type
                elif is_entry_ref_suffix(suffix_val):
                    # Entry reference suffix (e.g., "2a") - proposal created
                    mentor_suffix_type = "entry_ref"
                    # Keep suffix_val as-is, don't treat as duration
                else:
                    # Plain suffix - likely a duration
                    mentor_duration_val = suffix_val
                    suffix_val = None
                    mentor_suffix_type = "plain"

            mentor_status_line = MentorStatusLine(
                profile_name=profile_name,
                mentor_name=mentor_name,
                status=status_val,
                timestamp=timestamp_val,
                duration=mentor_duration_val,
                suffix=suffix_val,
                suffix_type=mentor_suffix_type,
            )
            if current_mentor_entry.status_lines is None:
                current_mentor_entry.status_lines = []
            current_mentor_entry.status_lines.append(mentor_status_line)

    return current_mentor_entry, mentor_entries


def parse_commits_line(
    line: str,
    stripped: str,
    current_commit_entry: CommitEntryDict | None,
    commit_entries: list[CommitEntry],
) -> tuple[CommitEntryDict | None, list[CommitEntry]]:
    """Parse a single line in COMMITS section.

    Args:
        line: The original line (with leading whitespace)
        stripped: The stripped line content
        current_commit_entry: The current commit entry being built (or None)
        commit_entries: List of completed commit entries

    Returns:
        Updated (current_commit_entry, commit_entries) tuple.
    """
    # Check for new commit entry: (N) or (Na) Note text
    # Supports both regular entries (N) and proposed entries (Na)
    commit_match = re.match(r"^\((\d+)([a-z])?\)\s+(.+)$", stripped)
    if commit_match:
        # Save previous entry if exists
        if current_commit_entry is not None:
            commit_entries.append(build_commit_entry(current_commit_entry))

        raw_note = commit_match.group(3)

        # Check for suffix pattern at end of note:
        # - (!: MSG), - (~!: MSG), - (~: MSG), - (@: MSG), or - (MSG)
        # Note: "~:" is legacy and treated as plain suffix (no prefix)
        suffix_match = re.search(r"\s+-\s+\((~!:|!:|~:|@:)?\s*([^)]+)\)$", raw_note)
        if suffix_match:
            note_without_suffix = raw_note[: suffix_match.start()]
            prefix = suffix_match.group(1)  # "~!:", "!:", "~:", "@:", or None
            suffix_msg = suffix_match.group(2).strip()
            if prefix == "~!:":
                suffix_type_val: str | None = "rejected_proposal"
            elif prefix == "!:":
                suffix_type_val = "error"
            elif prefix == "~:":
                # Legacy "~:" prefix treated as plain suffix
                suffix_type_val = None
            elif prefix == "@:":
                suffix_type_val = "running_agent"
            else:
                suffix_type_val = None
            # Handle standalone "@" as running_agent marker
            if suffix_msg == "@":
                suffix_msg = ""
                suffix_type_val = "running_agent"
        else:
            note_without_suffix = raw_note
            suffix_msg = None
            suffix_type_val = None

        # Start new entry
        current_commit_entry = CommitEntryDict(
            number=int(commit_match.group(1)),
            proposal_letter=commit_match.group(2),  # None for regular entries
            note=note_without_suffix,
            chat=None,
            diff=None,
            plan=None,
            suffix=suffix_msg,
            suffix_type=suffix_type_val,
            body=None,
        )
    elif stripped.startswith("| CHAT:"):
        if current_commit_entry is not None:
            current_commit_entry["chat"] = stripped[7:].strip()
    elif stripped.startswith("| DIFF:"):
        if current_commit_entry is not None:
            current_commit_entry["diff"] = stripped[7:].strip()
    elif stripped.startswith("| PLAN:"):
        if current_commit_entry is not None:
            current_commit_entry["plan"] = stripped[7:].strip()
    elif (
        current_commit_entry is not None
        and line.startswith("      ")
        and not stripped.startswith("| ")
    ):
        # Body continuation line: 6-space indent, not a drawer line
        body = current_commit_entry.get("body")
        if body is None:
            body = []
            current_commit_entry["body"] = body
        if stripped == ".":
            # Blank line marker -> empty string in body list
            body.append("")
        else:
            body.append(stripped)
    # If line doesn't match commit format, stay in commits mode
    # (blank lines or other content will be ignored)

    return current_commit_entry, commit_entries


def parse_deltas_line(
    line: str,
    stripped: str,
    delta_entries: list[DeltaEntry],
) -> list[DeltaEntry]:
    """Parse a single line in DELTAS section.

    Format: ``  <glyph> <path>`` where glyph is ``+``, ``~``, or ``-``.
    Optional line stats can follow as ``      | LINES: +N ~N -N``.

    Args:
        line: The original line (with leading whitespace and trailing newline).
        stripped: The stripped line content.
        delta_entries: List of completed delta entries.

    Returns:
        Updated delta_entries list.
    """
    del stripped  # path may contain trailing whitespace; match raw line instead.
    if line.startswith("      | LINES:"):
        if delta_entries:
            value = line.split(":", 1)[1]
            stats = _parse_delta_line_stats(value)
            if stats is not None:
                delta_entries[-1].line_stats = stats
        return delta_entries

    if not (line.startswith("  ") and not line.startswith("   ")):
        return delta_entries
    match = re.match(r"^  ([+~\-]) (.+)$", line.rstrip("\n"))
    if match:
        glyph = match.group(1)
        path = match.group(2)
        change_type = _DELTA_GLYPH_TO_TYPE[glyph]
        delta_entries.append(DeltaEntry(path=path, change_type=change_type))
    return delta_entries


def parse_timestamps_line(
    line: str,
    stripped: str,
    timestamp_entries: list[TimestampEntry],
) -> list[TimestampEntry]:
    """Parse a single line in TIMESTAMPS section.

    Args:
        line: The original line (with leading whitespace)
        stripped: The stripped line content
        timestamp_entries: List of completed timestamp entries

    Returns:
        Updated timestamp_entries list.
    """
    if line.startswith("  "):
        # New format: YYMMDD_HHMMSS EVENT  detail
        new_match = re.match(
            r"^(\d{6}_\d{6})\s+"
            r"(COMMIT|STATUS|SYNC|REWORD|REWIND|RENAME|REBASE)\s+"
            r"(.+)$",
            stripped,
        )
        # Old format: [YYYY-MM-DD HH:MM:SS] EVENT  detail
        old_match = re.match(
            r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+"
            r"(COMMIT|STATUS|SYNC|REWORD|REWIND|RENAME|REBASE)\s+"
            r"(.+)$",
            stripped,
        )
        # Hybrid format: [YYMMDD_HHMMSS] EVENT  detail (migration transition)
        hybrid_match = re.match(
            r"^\[(\d{6}_\d{6})\]\s+"
            r"(COMMIT|STATUS|SYNC|REWORD|REWIND|RENAME|REBASE)\s+"
            r"(.+)$",
            stripped,
        )
        ts_match = new_match or old_match or hybrid_match
        if ts_match:
            timestamp_entries.append(
                TimestampEntry(
                    timestamp=ts_match.group(1),
                    event_type=ts_match.group(2),
                    detail=ts_match.group(3).rstrip(),
                )
            )

    return timestamp_entries
