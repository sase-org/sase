"""TIMESTAMPS section builder for ChangeSpec detail display."""

from rich.text import Text

from ...changespec import ChangeSpec
from ..models.fold_state import FoldLevel
from .hint_tracker import HintTracker

# Color palette for TIMESTAMPS rendering
_COLOR_HEADER = "bold #87D7FF"
_COLOR_TIMESTAMP = "#AF87D7"
_COLOR_COMMIT = "bold #00D7AF"
_COLOR_STATUS = "bold #FFD787"
_COLOR_SYNC = "bold #5FD7FF"
_COLOR_REWORD = "bold #D7AFFF"
_COLOR_ARROW = "bold #808080"
_COLOR_DETAIL = "#D7D7AF"

_EVENT_COLORS: dict[str, str] = {
    "COMMIT": _COLOR_COMMIT,
    "STATUS": _COLOR_STATUS,
    "SYNC": _COLOR_SYNC,
    "REWORD": _COLOR_REWORD,
}


def build_timestamps_section(
    text: Text,
    changespec: ChangeSpec,
    timestamps_fold: FoldLevel = FoldLevel.COLLAPSED,
    hint_tracker: HintTracker | None = None,
) -> HintTracker:
    """Build the TIMESTAMPS section of the display.

    Fold levels:
    - COLLAPSED: Section not rendered at all (zero visual footprint).
    - EXPANDED: Header + only COMMIT entries shown.
    - FULLY_EXPANDED: Header + all entries shown.

    Args:
        text: The Rich Text object to append to.
        changespec: The ChangeSpec to display.
        timestamps_fold: Fold level for the timestamps section.
        hint_tracker: Current hint tracking state.

    Returns:
        Updated HintTracker (unchanged — timestamps have no hints).
    """
    tracker = hint_tracker or HintTracker(
        counter=0,
        mappings={},
        hook_hint_to_idx={},
        hint_to_entry_id={},
        mentor_hint_to_info={},
    )

    if not changespec.timestamps:
        return tracker

    if timestamps_fold == FoldLevel.COLLAPSED:
        text.append("TIMESTAMPS:", style=_COLOR_HEADER)
        text.append(f" [folded: {len(changespec.timestamps)}]", style="italic #808080")
        text.append("\n")
        return tracker

    text.append("TIMESTAMPS:\n", style=_COLOR_HEADER)

    for entry in changespec.timestamps:
        # EXPANDED: only show COMMIT entries
        if timestamps_fold == FoldLevel.EXPANDED and entry.event_type != "COMMIT":
            continue

        # Timestamp in brackets
        text.append(f"  [{entry.timestamp}] ", style=_COLOR_TIMESTAMP)

        # Event type keyword
        padded_event = entry.event_type.ljust(7)
        event_color = _EVENT_COLORS.get(entry.event_type, "")
        text.append(padded_event, style=event_color)

        # Detail — STATUS gets special arrow rendering
        if entry.event_type == "STATUS" and " -> " in entry.detail:
            old_status, new_status = entry.detail.split(" -> ", 1)
            text.append(old_status, style=_COLOR_DETAIL)
            text.append(" -> ", style=_COLOR_ARROW)
            text.append(new_status, style=_COLOR_DETAIL)
        else:
            text.append(entry.detail, style=_COLOR_DETAIL)

        text.append("\n")

    return tracker
