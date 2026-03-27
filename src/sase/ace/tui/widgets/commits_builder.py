"""COMMITS section builder for ChangeSpec detail display."""

import os
import re
from pathlib import Path

from rich.text import Text

from ...changespec import ChangeSpec, CommitEntry
from ...display_helpers import is_suffix_timestamp
from ..models.fold_state import FoldLevel
from .hint_tracker import HintTracker


def _should_show_commits_drawers(
    entry: CommitEntry,
    changespec: ChangeSpec,
    commits_fold: FoldLevel,
) -> bool:
    """Determine if drawers (CHAT/DIFF) should be shown for a COMMITS entry.

    - COLLAPSED: Show drawers only for the latest entry (highest number).
    - EXPANDED: Show drawers for all entries.
    - FULLY_EXPANDED: Show drawers for all entries.
    """
    if commits_fold != FoldLevel.COLLAPSED:
        return True
    if changespec.commits:
        max_number = max(
            (e.number for e in changespec.commits if not e.is_proposed),
            default=0,
        )
        # Show drawers for the highest-numbered entry (and its proposals)
        if entry.number == max_number:
            return True
    return False


def _should_show_chat_drawer(
    entry: CommitEntry,
    changespec: ChangeSpec,
    commits_fold: FoldLevel,
) -> bool:
    """Determine if CHAT drawer should be shown for a COMMITS entry.

    CHAT is always shown for entry 1 (first entry, non-proposal).
    For other entries, follows the same logic as DIFF.
    """
    if entry.number == 1 and not entry.is_proposed:
        return True
    return _should_show_commits_drawers(entry, changespec, commits_fold)


def _get_rejected_proposals_for_entry(
    entry: CommitEntry,
    all_commits: list[CommitEntry],
    max_number: int,
) -> list[CommitEntry]:
    """Get rejected proposals that belong to this parent entry.

    A proposal is rejected if its number doesn't match the max (latest) number.

    Args:
        entry: The parent (non-proposal) entry to check.
        all_commits: All commit entries in the ChangeSpec.
        max_number: The highest numeric commit entry number.

    Returns:
        List of rejected proposals for this parent entry.
    """
    if entry.is_proposed:
        return []  # Only regular entries can have proposals folded under them

    return [
        e
        for e in all_commits
        if e.is_proposed
        and e.number == entry.number  # Same base number
        and e.number != max_number  # Not the latest (i.e., rejected)
    ]


def _should_hide_rejected_proposals(commits_fold: FoldLevel) -> bool:
    """Whether rejected proposals should be hidden at this fold level.

    - COLLAPSED: Hidden (folded under parent).
    - EXPANDED: Hidden (folded under parent).
    - FULLY_EXPANDED: Visible.
    """
    return commits_fold != FoldLevel.FULLY_EXPANDED


def _truncate_note(note: str, available: int) -> str:
    """Truncate a note to fit within the available width, adding ellipsis if needed."""
    if available <= 0:
        return "\u2026"
    if len(note) <= available:
        return note
    return note[: available - 1] + "\u2026"


def build_commits_section(
    text: Text,
    changespec: ChangeSpec,
    show_history_hints: bool,
    commits_fold: FoldLevel,
    hint_tracker: HintTracker,
    max_width: int | None = None,
) -> HintTracker:
    """Build the COMMITS section of the display.

    Fold levels:
    - COLLAPSED: Show CHAT/DIFF only for latest entry. Hide rejected proposals.
      Body hidden, show [+N lines] indicator.
    - EXPANDED: Show CHAT/DIFF for all entries. Hide rejected proposals.
      Body shown in dimmer style.
    - FULLY_EXPANDED: Show everything including rejected proposals.
      Body shown in dimmer style.

    Args:
        text: The Rich Text object to append to.
        changespec: The ChangeSpec to display.
        show_history_hints: Whether to show file path hints.
        commits_fold: Fold level for the commits section.
        hint_tracker: Current hint tracking state.
        max_width: Optional maximum display width for truncation.

    Returns:
        Updated HintTracker with new hint mappings.
    """
    if not changespec.commits:
        return hint_tracker

    hint_counter = hint_tracker.counter
    hint_mappings = dict(hint_tracker.mappings)

    # Calculate max_number once before the loop for rejected proposal detection
    max_number = max(
        (e.number for e in changespec.commits if not e.is_proposed),
        default=0,
    )

    hide_rejected = _should_hide_rejected_proposals(commits_fold)

    text.append("COMMITS:\n", style="bold #87D7FF")
    for entry in changespec.commits:
        # Skip rejected proposals when not fully expanded
        if hide_rejected and entry.is_proposed and entry.number != max_number:
            continue

        entry_style = "bold #D7AF5F"
        prefix_str = f"  ({entry.display_number}) "
        text.append(prefix_str, style=entry_style)

        # Calculate suffix width for truncation
        suffix_width = 0
        if entry.suffix:
            # Approximate suffix display width: " - (PREFIX: MSG)" or " - (MSG)"
            if entry.suffix_type == "error":
                suffix_width = len(f" - (!: {entry.suffix})")
            elif entry.suffix_type == "running_agent":
                suffix_width = len(f" - (@: {entry.suffix})")
            elif entry.suffix_type == "running_process":
                suffix_width = len(f" - ($: {entry.suffix})")
            elif entry.suffix_type == "rejected_proposal":
                suffix_width = len(f" - (~!: {entry.suffix})")
            else:
                suffix_width = len(f" - ({entry.suffix})")

        # Pre-compute fold state for this entry (needed for truncation calc)
        show_drawers = _should_show_commits_drawers(entry, changespec, commits_fold)
        show_chat = _should_show_chat_drawer(entry, changespec, commits_fold)
        show_body = entry.body and commits_fold != FoldLevel.COLLAPSED
        rejected_proposals = (
            _get_rejected_proposals_for_entry(entry, changespec.commits, max_number)
            if hide_rejected
            else []
        )
        has_folded_chat = not show_chat and entry.chat
        has_folded_diff = not show_drawers and entry.diff
        has_folded_content = has_folded_chat or has_folded_diff or rejected_proposals

        # Determine display note (truncated only when collapsed)
        display_note = entry.note
        if max_width is not None and commits_fold == FoldLevel.COLLAPSED:
            # Calculate folded indicator width
            folded_width = 0
            if has_folded_content:
                parts_strs: list[str] = []
                if has_folded_chat:
                    parts_strs.append("CHAT")
                if has_folded_diff:
                    parts_strs.append("DIFF")
                if rejected_proposals:
                    count = len(rejected_proposals)
                    parts_strs.append(f"{count} proposal{'s' if count > 1 else ''}")
                folded_width = len("  [folded: " + " + ".join(parts_strs) + "]")

            available = max_width - len(prefix_str) - suffix_width - folded_width
            # Account for body fold indicator
            if entry.body:
                available -= len(f"  [+{len(entry.body)} lines]")
            display_note = _truncate_note(entry.note, available)

        # Check if note contains a file path in parentheses
        note_path_match = re.search(r"\((~/[^)]+)\)", display_note)
        if show_history_hints and note_path_match:
            # Split the note around the path and add hint
            note_path = note_path_match.group(1)
            full_path = os.path.expanduser(note_path)
            hint_mappings[hint_counter] = full_path
            before_path = display_note[: note_path_match.start()]
            after_path = display_note[note_path_match.end() :]
            text.append(before_path, style="#D7D7AF")
            text.append("(", style="#D7D7AF")
            text.append(f"[{hint_counter}] ", style="bold #FFFF00")
            text.append(note_path, style="#87AFFF")
            text.append(f"){after_path}", style="#D7D7AF")
            hint_counter += 1
        else:
            text.append(f"{display_note}", style="#D7D7AF")

        if entry.suffix:
            text.append(" - ")
            if entry.suffix_type == "error":
                text.append(f"(!: {entry.suffix})", style="bold #FFFFFF on #AF0000")
            elif entry.suffix_type == "running_agent" or is_suffix_timestamp(
                entry.suffix
            ):
                # Orange background with white text (same as @@@ query)
                text.append(f"(@: {entry.suffix})", style="bold #FFFFFF on #FF8C00")
            elif entry.suffix_type == "running_process":
                # Yellow background with dark brown text (same as $$$ query)
                text.append(f"($: {entry.suffix})", style="bold #3D2B1F on #FFD700")
            elif entry.suffix_type == "pending_dead_process":
                # Grey background with yellow text for pending dead process
                text.append(f"(?$: {entry.suffix})", style="bold #FFD700 on #444444")
            elif entry.suffix_type == "killed_process":
                # Grey background with olive text for killed process
                text.append(f"(~$: {entry.suffix})", style="bold #B8A800 on #444444")
            elif entry.suffix_type == "rejected_proposal":
                # Grey background with red text for rejected proposal
                text.append(f"(~!: {entry.suffix})", style="bold #FF5F5F on #444444")
            else:
                text.append(f"({entry.suffix})")

        # Body fold indicator (shown when body exists but is collapsed)
        if entry.body and not show_body:
            text.append(f"  [+{len(entry.body)} lines]", style="italic #808080")

        if has_folded_content:
            text.append("  [folded: ", style="italic #808080")
            parts: list[tuple[str, str]] = []
            if has_folded_chat:
                parts.append(("CHAT", "bold #87D7FF"))
            if has_folded_diff:
                parts.append(("DIFF", "bold #87D7FF"))
            if rejected_proposals:
                count = len(rejected_proposals)
                label = f"{count} proposal{'s' if count > 1 else ''}"
                parts.append((label, "bold #87D7FF"))

            for i, (label, style) in enumerate(parts):
                if i > 0:
                    text.append(" + ", style="italic #808080")
                text.append(label, style=style)
            text.append("]", style="italic #808080")

        text.append("\n")

        # Render body lines when expanded
        if entry.body and show_body:
            for body_line in entry.body:
                if body_line == "":
                    text.append("\n")
                else:
                    text.append(f"      {body_line}\n", style="#B8B890")

        # CHAT field - only show if chat drawer visible
        if entry.chat and show_chat:
            text.append("      ", style="")
            # Parse duration suffix from chat (e.g., "path (1h2m3s)")
            chat_duration_match = re.search(r" \((\d+[hms]+[^)]*)\)$", entry.chat)
            if chat_duration_match:
                chat_path_raw = entry.chat[: chat_duration_match.start()]
                chat_duration = chat_duration_match.group(1)
            else:
                chat_path_raw = entry.chat
                chat_duration = None
            if show_history_hints:
                hint_mappings[hint_counter] = chat_path_raw
                text.append(f"[{hint_counter}] ", style="bold #FFFF00")
                hint_counter += 1
            text.append("| ", style="#808080")
            text.append("CHAT: ", style="bold #87D7FF")
            chat_path = chat_path_raw.replace(str(Path.home()), "~")
            text.append(chat_path, style="#87AFFF")
            if chat_duration:
                text.append(f" ({chat_duration})", style="#808080")
            text.append("\n")

        # DIFF field - only show if drawers visible
        if entry.diff and show_drawers:
            text.append("      ", style="")
            if show_history_hints:
                hint_mappings[hint_counter] = entry.diff
                text.append(f"[{hint_counter}] ", style="bold #FFFF00")
                hint_counter += 1
            text.append("| ", style="#808080")
            text.append("DIFF: ", style="bold #87D7FF")
            diff_path = entry.diff.replace(str(Path.home()), "~")
            text.append(f"{diff_path}\n", style="#87AFFF")

    return HintTracker(
        counter=hint_counter,
        mappings=hint_mappings,
        hook_hint_to_idx=hint_tracker.hook_hint_to_idx,
        hint_to_entry_id=hint_tracker.hint_to_entry_id,
        mentor_hint_to_info=hint_tracker.mentor_hint_to_info,
    )
