"""MENTORS section builder for ChangeSpec detail display."""

import os

from rich.text import Text

from ...changespec import ChangeSpec
from ...hooks import format_timestamp_display
from ...scheduler.mentor_runner import get_mentor_chat_path
from ..models.fold_state import FoldLevel
from .hint_tracker import HintTracker
from .suffix_formatting import SUFFIX_STYLES, append_suffix_to_text


def build_mentors_section(
    text: Text,
    changespec: ChangeSpec,
    mentors_fold: FoldLevel = FoldLevel.COLLAPSED,
    with_hints: bool = False,
    hints_for: str | None = None,
    hint_tracker: HintTracker | None = None,
) -> HintTracker:
    """Build the MENTORS section of the display.

    Fold levels:
    - COLLAPSED: Non-latest all hidden. Latest shows only RUNNING/FAILED.
    - EXPANDED: Non-latest still hidden. Latest shows ALL statuses
      (including PASSED/DEAD).
    - FULLY_EXPANDED: Everything shown for all entries.

    Args:
        text: The Rich Text object to append to.
        changespec: The ChangeSpec to display.
        mentors_fold: Fold level for the mentors section.
        with_hints: Whether to show hint numbers for viewable entries.
        hint_tracker: Current hint tracking state (counter, mappings, etc.).

    Returns:
        Updated HintTracker with new hints added.
    """
    # Initialize hint tracking
    hint_counter = hint_tracker.counter if hint_tracker else 0
    hint_mappings = dict(hint_tracker.mappings) if hint_tracker else {}
    hook_hint_to_idx = dict(hint_tracker.hook_hint_to_idx) if hint_tracker else {}
    hint_to_entry_id = dict(hint_tracker.hint_to_entry_id) if hint_tracker else {}
    mentor_hint_to_info = dict(hint_tracker.mentor_hint_to_info) if hint_tracker else {}

    if not changespec.mentors:
        return HintTracker(
            counter=hint_counter,
            mappings=hint_mappings,
            hook_hint_to_idx=hook_hint_to_idx,
            hint_to_entry_id=hint_to_entry_id,
            mentor_hint_to_info=mentor_hint_to_info,
        )

    # Find the latest (highest numeric) commit ID from COMMITS field
    latest_entry_id: str | None = None
    if changespec.commits:
        for commit in changespec.commits:
            # Only consider all-numeric entries (e.g., "5", not "5a")
            if commit.proposal_letter is None:
                if latest_entry_id is None or commit.number > int(latest_entry_id):
                    latest_entry_id = str(commit.number)

    text.append("MENTORS:\n", style="bold #87D7FF")

    for mentor_entry in changespec.mentors:
        from ...display_helpers import format_profile_with_count

        visible_profiles = mentor_entry.profiles

        # Skip entry entirely if no visible profiles
        if not visible_profiles:
            continue

        is_latest_entry = mentor_entry.entry_id == latest_entry_id

        # Count non-RUNNING statuses for folded summary
        # What's folded depends on the fold level:
        # - COLLAPSED: PASSED always folded; FAILED folded for non-latest; DEAD always
        # - EXPANDED: PASSED folded for non-latest; FAILED folded for non-latest; DEAD
        #   folded for non-latest
        # - FULLY_EXPANDED: nothing folded
        passed_count = 0
        failed_count = 0
        dead_count = 0
        if mentors_fold != FoldLevel.FULLY_EXPANDED and mentor_entry.status_lines:
            for msl in mentor_entry.status_lines:
                if msl.status == "PASSED":
                    if mentors_fold == FoldLevel.COLLAPSED:
                        # COLLAPSED: all PASSED are folded
                        passed_count += 1
                    elif not is_latest_entry:
                        # EXPANDED: only non-latest PASSED are folded
                        passed_count += 1
                elif msl.status == "FAILED":
                    if not is_latest_entry:
                        failed_count += 1
                elif msl.status == "DEAD":
                    if mentors_fold == FoldLevel.COLLAPSED:
                        # COLLAPSED: all DEAD are folded
                        dead_count += 1
                    elif not is_latest_entry:
                        # EXPANDED: only non-latest DEAD are folded
                        dead_count += 1

        # Entry line (2-space indented): (N) profile1[x/y] [profile2[x/y] ...]
        text.append("  ", style="")
        text.append(f"({mentor_entry.entry_id}) ", style="bold #D7AF5F")
        profiles_with_counts = [
            format_profile_with_count(p, mentor_entry.status_lines)
            for p in visible_profiles
        ]
        text.append(" ".join(profiles_with_counts), style="#D7D7AF")
        if mentor_entry.is_draft:
            text.append(" #Draft", style="bold #FFD700")

        # Add folded suffix if has folded statuses
        if passed_count or failed_count or dead_count:
            text.append("  [folded: ", style="italic #808080")
            parts: list[tuple[str, int, str]] = []
            if passed_count:
                parts.append(("PASSED", passed_count, "#00AF00"))
            if failed_count:
                parts.append(("FAILED", failed_count, "#FF5F5F"))
            if dead_count:
                parts.append(("DEAD", dead_count, "#B8A800"))
            for i, (status, count, color) in enumerate(parts):
                if i > 0:
                    text.append(" | ", style="italic #808080")
                text.append(status, style=f"bold italic {color}")
                text.append(f": {count}", style="italic #808080")
            text.append("]", style="italic #808080")

        text.append("\n")

        # Status lines (if present) - 6-space indented
        if mentor_entry.status_lines:
            for msl in mentor_entry.status_lines:
                if mentors_fold != FoldLevel.FULLY_EXPANDED:
                    # In mentors_running mode, always show RUNNING mentors
                    # regardless of fold level or entry age
                    force_show = (
                        hints_for == "mentors_running"
                        and msl.suffix_type == "running_agent"
                    )
                    if not force_show:
                        # COLLAPSED: non-latest → hide all; latest → hide PASSED/DEAD
                        # EXPANDED: non-latest → hide all; latest → show all
                        if not is_latest_entry:
                            continue
                        if mentors_fold == FoldLevel.COLLAPSED and msl.status in (
                            "PASSED",
                            "DEAD",
                        ):
                            continue

                text.append("      ", style="")
                text.append("| ", style="#808080")

                # Show hints based on mode:
                # - mentors_running: hints for RUNNING mentors (for ,M kill mode)
                # - default: hints for PASSED/FAILED mentors (for view mode)
                if with_hints and hints_for == "mentors_running":
                    if msl.suffix_type == "running_agent":
                        hint_mappings[hint_counter] = ""  # No file to view
                        hint_to_entry_id[hint_counter] = mentor_entry.entry_id
                        mentor_hint_to_info[hint_counter] = (
                            msl.mentor_name,
                            msl.profile_name,
                        )
                        text.append(f"[{hint_counter}] ", style="bold #FF5F5F")
                        hint_counter += 1
                elif (
                    with_hints and msl.timestamp and msl.status in ("PASSED", "FAILED")
                ):
                    chat_path = get_mentor_chat_path(
                        changespec.name, msl.mentor_name, msl.timestamp
                    )
                    if os.path.exists(chat_path):
                        hint_mappings[hint_counter] = chat_path
                        hint_to_entry_id[hint_counter] = mentor_entry.entry_id
                        mentor_hint_to_info[hint_counter] = (
                            msl.mentor_name,
                            msl.profile_name,
                        )
                        text.append(f"[{hint_counter}] ", style="bold #FFFF00")
                        hint_counter += 1

                # Display timestamp if present (same magenta as HOOKS)
                if msl.timestamp:
                    ts_display = format_timestamp_display(msl.timestamp)
                    text.append(f"{ts_display} ", style="#AF87D7")

                # Format: profile:mentor - STATUS - (suffix/duration)
                text.append(
                    f"{msl.profile_name}:{msl.mentor_name}",
                    style="bold #87AFFF",
                )
                text.append(" - ", style="")
                # Color based on status
                if msl.status == "PASSED":
                    text.append(msl.status, style="bold #00AF00")
                elif msl.status == "FAILED":
                    text.append(msl.status, style="bold #FF5F5F")
                elif msl.status == "RUNNING":
                    text.append(msl.status, style="bold #FFD700")
                else:
                    text.append(msl.status)
                # Duration (if present)
                if msl.duration:
                    text.append(f" - ({msl.duration})", style="#808080")
                # Suffix (if present)
                if msl.suffix is not None and (
                    msl.suffix or msl.suffix_type == "running_agent"
                ):
                    text.append(" - ")
                    if (
                        with_hints
                        and msl.suffix_type == "error"
                        and msl.suffix
                        and (msl.suffix.startswith("~/") or msl.suffix.startswith("/"))
                    ):
                        display_path = msl.suffix
                        full_path = os.path.expanduser(display_path)
                        hint_mappings[hint_counter] = full_path
                        text.append("(!: ", style=SUFFIX_STYLES["error"])
                        text.append(f"[{hint_counter}] ", style="bold #FFFF00")
                        text.append(display_path, style=SUFFIX_STYLES["error"])
                        text.append(")", style=SUFFIX_STYLES["error"])
                        hint_counter += 1
                    else:
                        append_suffix_to_text(
                            text,
                            msl.suffix_type,
                            msl.suffix,
                            summary=None,
                            check_entry_ref=True,
                        )
                text.append("\n")

    return HintTracker(
        counter=hint_counter,
        mappings=hint_mappings,
        hook_hint_to_idx=hook_hint_to_idx,
        hint_to_entry_id=hint_to_entry_id,
        mentor_hint_to_info=mentor_hint_to_info,
    )
