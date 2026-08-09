"""Patch parsing implementation."""

from .models import (
    CommentEntry,
    DeltaEntry,
    HookEntry,
    MentorEntry,
    Patch,
    Stitch,
    TimestampEntry,
)
from .review_field import parse_review_url_line
from .section_parsers import (
    StitchEntryDict,
    build_stitch,
    parse_comments_line,
    parse_deltas_line,
    parse_hooks_line,
    parse_mentors_line,
    parse_stitches_line,
    parse_timestamps_line,
)
from .storage import is_patch_heading, stitch_section_header_for


class _ParserState:
    """Encapsulates parser state for a single Patch."""

    def __init__(self, start_idx: int, file_path: str) -> None:
        # Field values
        self.name: str | None = None
        self.description_lines: list[str] = []
        self.parent: str | None = None
        self.pr_url: str | None = None
        self.bug: str | None = None
        self.status: str | None = None
        self.refs: list[str] = []

        # Entry collections
        self.stitches: list[Stitch] = []
        self.current_stitch: StitchEntryDict | None = None
        self.hook_entries: list[HookEntry] = []
        self.current_hook_entry: HookEntry | None = None
        self.comment_entries: list[CommentEntry] = []
        self.mentor_entries: list[MentorEntry] = []
        self.current_mentor_entry: MentorEntry | None = None
        self.timestamp_entries: list[TimestampEntry] = []
        self.delta_entries: list[DeltaEntry] = []

        # Metadata
        self.line_number = start_idx + 1  # Convert to 1-based line numbering
        self.file_path = file_path
        self.stitch_section_header: str | None = None

        # Section flags
        self.in_description = False
        self.in_refs = False
        self.in_stitches = False
        self.in_hooks = False
        self.in_comments = False
        self.in_mentors = False
        self.in_timestamps = False
        self.in_deltas = False

    def reset_section_flags(self) -> None:
        """Reset all section flags to False."""
        self.in_description = False
        self.in_refs = False
        self.in_stitches = False
        self.in_hooks = False
        self.in_comments = False
        self.in_mentors = False
        self.in_timestamps = False
        self.in_deltas = False

    def save_pending_entries(self) -> None:
        """Save any pending entries before switching sections or finalizing."""
        if self.current_stitch is not None:
            self.stitches.append(build_stitch(self.current_stitch))
            self.current_stitch = None
        if self.current_hook_entry is not None:
            self.hook_entries.append(self.current_hook_entry)
            self.current_hook_entry = None
        if self.current_mentor_entry is not None:
            self.mentor_entries.append(self.current_mentor_entry)
            self.current_mentor_entry = None

    def build_patch(self) -> Patch | None:
        """Build Patch from accumulated state."""
        self.save_pending_entries()

        if self.name and self.status:
            description = "\n".join(self.description_lines).strip()
            return Patch(
                name=self.name,
                description=description,
                parent=self.parent,
                pr_url=self.pr_url,
                status=self.status,
                file_path=self.file_path,
                line_number=self.line_number,
                bug=self.bug,
                refs=self.refs if self.refs else None,
                stitches=self.stitches if self.stitches else None,
                hooks=self.hook_entries if self.hook_entries else None,
                comments=self.comment_entries if self.comment_entries else None,
                mentors=self.mentor_entries if self.mentor_entries else None,
                timestamps=self.timestamp_entries if self.timestamp_entries else None,
                deltas=self.delta_entries if self.delta_entries else None,
                stitch_section_header=self.stitch_section_header,
            )
        return None


def _parse_field_header(state: _ParserState, line: str) -> bool:
    """Parse a field header line (NAME:, DESCRIPTION:, etc.).

    Returns True if a field header was parsed, False otherwise.
    """
    if line.startswith("NAME: "):
        # If we already have a name, this is a new Patch
        if state.name is not None:
            return False  # Signal to stop parsing
        state.name = line[6:].strip()
        state.reset_section_flags()
        return True

    if line.startswith("DESCRIPTION:"):
        state.save_pending_entries()
        state.reset_section_flags()
        state.in_description = True
        # Check if description is on the same line
        desc_inline = line[12:].strip()
        if desc_inline:
            state.description_lines.append(desc_inline)
        return True

    if line.startswith("PARENT: "):
        state.save_pending_entries()
        state.parent = line[8:].strip()
        state.reset_section_flags()
        return True

    pr_url = parse_review_url_line(line)
    if pr_url is not None:
        state.save_pending_entries()
        state.pr_url = pr_url
        state.reset_section_flags()
        return True

    if line.startswith("BUG: "):
        state.save_pending_entries()
        state.bug = line[5:].strip()
        state.reset_section_flags()
        return True

    if line.startswith("STATUS: "):
        state.save_pending_entries()
        state.status = line[8:].strip()
        state.reset_section_flags()
        return True

    return False


def _parse_section_header(state: _ParserState, line: str) -> bool:
    """Parse a section header line (STITCHES:/COMMITS:, HOOKS:, etc.).

    Returns True if a section header was parsed, False otherwise.
    """
    if line.startswith("REFS:"):
        state.save_pending_entries()
        state.reset_section_flags()
        state.in_refs = True
        return True

    stitch_header = stitch_section_header_for(line)
    if stitch_header is not None:
        state.save_pending_entries()
        state.reset_section_flags()
        state.in_stitches = True
        state.stitch_section_header = stitch_header
        return True

    if line.startswith("HOOKS:"):
        state.save_pending_entries()
        state.reset_section_flags()
        state.in_hooks = True
        return True

    if line.startswith("COMMENTS:"):
        state.save_pending_entries()
        state.reset_section_flags()
        state.in_comments = True
        return True

    if line.startswith("MENTORS:"):
        state.save_pending_entries()
        state.reset_section_flags()
        state.in_mentors = True
        return True

    if line.startswith("TIMESTAMPS:"):
        state.save_pending_entries()
        state.reset_section_flags()
        state.in_timestamps = True
        return True

    if line.startswith("DELTAS:"):
        state.save_pending_entries()
        state.reset_section_flags()
        state.in_deltas = True
        return True

    return False


def _parse_section_content(state: _ParserState, line: str) -> None:
    """Parse content within the current section."""
    stripped = line.strip()

    if state.in_refs:
        if stripped:
            state.refs.append(stripped)
    elif state.in_timestamps:
        state.timestamp_entries = parse_timestamps_line(
            line, stripped, state.timestamp_entries
        )
    elif state.in_deltas:
        state.delta_entries = parse_deltas_line(line, stripped, state.delta_entries)
    elif state.in_hooks:
        state.current_hook_entry, state.hook_entries = parse_hooks_line(
            line, stripped, state.current_hook_entry, state.hook_entries
        )
    elif state.in_comments:
        state.comment_entries = parse_comments_line(
            line, stripped, state.comment_entries
        )
    elif state.in_mentors:
        state.current_mentor_entry, state.mentor_entries = parse_mentors_line(
            line, stripped, state.current_mentor_entry, state.mentor_entries
        )
    elif state.in_stitches:
        state.current_stitch, state.stitches = parse_stitches_line(
            line, stripped, state.current_stitch, state.stitches
        )
    elif state.in_description and line.startswith("  "):
        # Description continuation (2-space indented)
        state.description_lines.append(line[2:].rstrip("\n"))
    elif stripped == "":
        # Blank line - preserve in description
        if state.in_description:
            state.description_lines.append("")
    elif not line.startswith("#"):
        # Any other non-comment content ends the special parsing modes
        state.reset_section_flags()


def parse_patch_from_lines(
    lines: list[str], start_idx: int, file_path: str
) -> tuple[Patch | None, int]:
    """Parse a single Patch from lines starting at start_idx.

    Returns:
        Tuple of (Patch or None, next_index_to_process)
    """
    state = _ParserState(start_idx, file_path)
    idx = start_idx
    consecutive_blank_lines = 0

    while idx < len(lines):
        line = lines[idx]

        # Check for end of Patch (next Patch header or 2 blank lines)
        if is_patch_heading(line) and idx > start_idx:
            break
        if line.strip() == "":
            consecutive_blank_lines += 1
            # 2 blank lines indicate end of Patch
            if consecutive_blank_lines >= 2:
                break
        else:
            consecutive_blank_lines = 0

        # Try to parse field headers (NAME:, DESCRIPTION:, etc.)
        if _parse_field_header(state, line):
            idx += 1
            continue

        # Check if we hit a new NAME: when we already have one
        if line.startswith("NAME: ") and state.name is not None:
            state.save_pending_entries()
            # Don't increment idx - let the caller re-process this NAME line
            idx -= 1
            break

        # Try to parse section headers (STITCHES:/COMMITS:, HOOKS:, etc.)
        if _parse_section_header(state, line):
            idx += 1
            continue

        # Parse section content
        _parse_section_content(state, line)
        idx += 1

    return state.build_patch(), idx


def parse_patch_project_file(file_path: str) -> list[Patch]:
    """Parse all Patches from a project file.

    Public entry point. It routes through the :mod:`sase.core` facade, which
    keeps this file-path API on the Python parser even when the Rust backend
    is selected. The bytes-shaped core API is the Rust-eligible parser path.
    """
    from sase.core.parser_facade import parse_patch_project_file as _facade

    return _facade(file_path)


def parse_patch_project_file_python(file_path: str) -> list[Patch]:
    """Python implementation of :func:`parse_patch_project_file`.

    Args:
        file_path: Path to the project markdown file

    Returns:
        List of Patch objects
    """
    patches: list[Patch] = []

    try:
        with open(file_path) as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}")
        return []

    idx = 0
    while idx < len(lines):
        line = lines[idx]

        # Look for Patch start by detecting NAME: field
        # (Patches can start with ## Patch/## ChangeSpec header OR directly with NAME:)  # legacy compatibility alias
        if is_patch_heading(line):
            # Skip the header line and parse the Patch
            patch, next_idx = parse_patch_from_lines(lines, idx + 1, file_path)
            if patch:
                patches.append(patch)
            idx = next_idx
        elif line.startswith("NAME: "):
            # Patch starts directly with NAME field (no header)
            patch, next_idx = parse_patch_from_lines(lines, idx, file_path)
            if patch:
                patches.append(patch)
            idx = next_idx
        else:
            idx += 1

    return patches


parse_project_file = parse_patch_project_file
parse_project_file_python = parse_patch_project_file_python
_parse_changespec_from_lines = parse_patch_from_lines  # legacy compatibility alias
_parse_patch_from_lines = parse_patch_from_lines
