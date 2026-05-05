"""DELTAS section builder for ChangeSpec detail display."""

import os

from rich.text import Text

from ...changespec import ChangeSpec
from ...changespec.models import DeltaEntry, DeltaLineStats
from ..models.fold_state import FoldLevel, normalize_deltas_fold_level
from .hint_tracker import HintTracker

_COLOR_HEADER = "bold #87D7FF"
_COLOR_PATH = "#87AFFF"
_COLOR_BASENAME = "bold #87AFFF"
_COLOR_DIM_ITALIC = "italic #808080"

_GLYPH_BY_TYPE = {"A": "+", "M": "~", "D": "-"}
_GLYPH_STYLE = {
    "A": "bold #5FD787",
    "M": "bold #FFD787",
    "D": "bold #FF5F5F",
}


def _line_tokens(stats: DeltaLineStats) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    if stats.added:
        tokens.append((f"+{stats.added}", _GLYPH_STYLE["A"]))
    if stats.modified:
        tokens.append((f"~{stats.modified}", _GLYPH_STYLE["M"]))
    if stats.removed:
        tokens.append((f"-{stats.removed}", _GLYPH_STYLE["D"]))
    if stats.binary:
        tokens.append(("binary", _COLOR_DIM_ITALIC))
    return tokens or [("0 lines", _COLOR_DIM_ITALIC)]


def _combined_line_stats(entries: list[DeltaEntry]) -> DeltaLineStats | None:
    stats = [entry.line_stats for entry in entries if entry.line_stats is not None]
    if not stats:
        return None
    return DeltaLineStats(
        added=sum(stat.added for stat in stats),
        modified=sum(stat.modified for stat in stats),
        removed=sum(stat.removed for stat in stats),
        binary=any(stat.binary for stat in stats),
    )


def _append_line_tokens(text: Text, stats: DeltaLineStats) -> None:
    for idx, (token, style) in enumerate(_line_tokens(stats)):
        if idx:
            text.append(" ")
        text.append(token, style=style)


def _append_group_line_stats(text: Text, entries: list[DeltaEntry]) -> None:
    stats = _combined_line_stats(entries)
    if stats is None:
        return
    text.append(" (", style=_COLOR_DIM_ITALIC)
    _append_line_tokens(text, stats)
    text.append(")", style=_COLOR_DIM_ITALIC)


def _append_path(text: Text, path: str) -> None:
    """Append a path with a bold-basename treatment."""
    dirname, basename = os.path.split(path)
    if dirname:
        text.append(dirname + "/", style=_COLOR_PATH)
    text.append(basename or path, style=_COLOR_BASENAME)


def _counts(deltas: list[DeltaEntry]) -> tuple[int, int, int]:
    added = sum(1 for d in deltas if d.change_type == "A")
    modified = sum(1 for d in deltas if d.change_type == "M")
    deleted = sum(1 for d in deltas if d.change_type == "D")
    return added, modified, deleted


def _append_summary(text: Text, deltas: list[DeltaEntry]) -> None:
    """Append a one-line summary: ``+3 ~2 -1 (6 files)``."""
    added, modified, deleted = _counts(deltas)
    added_entries = [d for d in deltas if d.change_type == "A"]
    modified_entries = [d for d in deltas if d.change_type == "M"]
    deleted_entries = [d for d in deltas if d.change_type == "D"]
    text.append("  ")
    text.append(f"+{added}", style=_GLYPH_STYLE["A"])
    _append_group_line_stats(text, added_entries)
    text.append(" ")
    text.append(f"~{modified}", style=_GLYPH_STYLE["M"])
    _append_group_line_stats(text, modified_entries)
    text.append(" ")
    text.append(f"-{deleted}", style=_GLYPH_STYLE["D"])
    _append_group_line_stats(text, deleted_entries)
    total = len(deltas)
    suffix = "file" if total == 1 else "files"
    text.append(f" ({total} {suffix})\n", style=_COLOR_DIM_ITALIC)


def _resolve_delta_path(path: str, workspace_dir: str | None) -> str:
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return expanded
    if workspace_dir:
        return os.path.join(workspace_dir, expanded)
    return os.path.abspath(expanded)


def _append_entry(
    text: Text,
    entry: DeltaEntry,
    hint_counter: int | None = None,
) -> None:
    glyph = _GLYPH_BY_TYPE.get(entry.change_type, "?")
    style = _GLYPH_STYLE.get(entry.change_type, "")
    text.append(f"  {glyph} ", style=style)
    if hint_counter is not None:
        text.append(f"[{hint_counter}] ", style="bold #FFFF00")
    _append_path(text, entry.path)
    if entry.line_stats is not None:
        text.append("  ")
        _append_line_tokens(text, entry.line_stats)
    text.append("\n")


def build_deltas_section(
    text: Text,
    changespec: ChangeSpec,
    deltas_fold: FoldLevel = FoldLevel.COLLAPSED,
    hint_tracker: HintTracker | None = None,
    show_file_hints: bool = False,
    workspace_dir: str | None = None,
) -> HintTracker:
    """Build the DELTAS section of the display.

    DELTAS has two semantic states:
    - Folded: header + one-line summary ``+A ~M -D (N files)``.
    - Unfolded: header + alphabetical entry list with bold basename.

    ``FoldLevel.EXPANDED`` is accepted as a compatibility/shared-control input
    and is normalized to the unfolded DELTAS state.

    The section is also fully omitted when ``changespec.deltas`` is ``None``
    (never computed) or ``[]`` (computed; no file changes).

    Args:
        text: The Rich Text object to append to.
        changespec: The ChangeSpec to display.
        deltas_fold: Fold level for the DELTAS section.
        hint_tracker: Current hint tracking state.
        show_file_hints: Whether to show file path hints on visible entries.
        workspace_dir: Workspace directory for resolving relative paths.

    Returns:
        Updated HintTracker.
    """
    tracker = hint_tracker or HintTracker(
        counter=1 if show_file_hints else 0,
        mappings={},
        hook_hint_to_idx={},
        hint_to_entry_id={},
        mentor_hint_to_info={},
    )

    deltas = changespec.deltas
    if not deltas:
        return tracker

    text.append("DELTAS:", style=_COLOR_HEADER)
    if normalize_deltas_fold_level(deltas_fold) == FoldLevel.COLLAPSED:
        _append_summary(text, deltas)
        return tracker

    text.append("\n")
    hint_counter = tracker.counter
    hint_mappings = dict(tracker.mappings)
    for entry in sorted(deltas, key=lambda e: e.path):
        if show_file_hints:
            hint_mappings[hint_counter] = _resolve_delta_path(entry.path, workspace_dir)
            _append_entry(text, entry, hint_counter)
            hint_counter += 1
        else:
            _append_entry(text, entry)

    return HintTracker(
        counter=hint_counter,
        mappings=hint_mappings,
        hook_hint_to_idx=tracker.hook_hint_to_idx,
        hint_to_entry_id=tracker.hint_to_entry_id,
        mentor_hint_to_info=tracker.mentor_hint_to_info,
    )
