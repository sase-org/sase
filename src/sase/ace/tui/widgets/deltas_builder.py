"""DELTAS section builder for ChangeSpec detail display."""

import os
from collections.abc import Sequence

from rich.text import Text

from ...changespec import ChangeSpec
from ...changespec.models import DeltaEntry, DeltaLineStats
from ..models.fold_state import FoldLevel
from .file_panel._linked_deltas import LinkedDeltaGroup
from .hint_tracker import HintTracker
from .prompt_panel._agent_context_common import (
    COLOR_ARTIFACT_FILE_BASENAME,
    COLOR_ARTIFACT_FILE_PATH,
    COLOR_EXTERNAL_REPO_GLYPH,
    COLOR_EXTERNAL_REPO_NAME,
    COLOR_WORKSPACE_GLYPH,
    COLOR_WORKSPACE_NAME,
    EXTERNAL_REPO_GLYPH,
    WORKSPACE_GLYPH,
)

_COLOR_HEADER = "bold #87D7FF"
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
        text.append(dirname + "/", style=COLOR_ARTIFACT_FILE_PATH)
    text.append(basename or path, style=COLOR_ARTIFACT_FILE_BASENAME)


def _counts(deltas: list[DeltaEntry]) -> tuple[int, int, int]:
    added = sum(1 for d in deltas if d.change_type == "A")
    modified = sum(1 for d in deltas if d.change_type == "M")
    deleted = sum(1 for d in deltas if d.change_type == "D")
    return added, modified, deleted


def _append_summary(text: Text, deltas: list[DeltaEntry], *, indent: str = "") -> None:
    """Append a one-line summary: ``+3 ~2 -1 (6 files)``."""
    added, modified, deleted = _counts(deltas)
    added_entries = [d for d in deltas if d.change_type == "A"]
    modified_entries = [d for d in deltas if d.change_type == "M"]
    deleted_entries = [d for d in deltas if d.change_type == "D"]
    text.append(f"{indent}  ")
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
    *,
    indent: str = "  ",
    show_line_stats: bool = False,
) -> None:
    glyph = _GLYPH_BY_TYPE.get(entry.change_type, "?")
    style = _GLYPH_STYLE.get(entry.change_type, "")
    text.append(f"{indent}{glyph} ", style=style)
    if hint_counter is not None:
        text.append(f"[{hint_counter}] ", style="bold #FFFF00")
    _append_path(text, entry.path)
    if show_line_stats and entry.line_stats is not None:
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

    DELTAS uses the shared three fold levels:
    - Collapsed: header + one-line summary ``+A ~M -D (N files)``.
    - Expanded: header + alphabetical entry list with bold basename.
    - Fully expanded: expanded entries plus per-entry line stats.

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
    return build_delta_entries_section(
        text,
        changespec.deltas,
        deltas_fold=deltas_fold,
        hint_tracker=hint_tracker,
        show_file_hints=show_file_hints,
        workspace_dir=workspace_dir,
    )


def build_delta_entries_section(
    text: Text,
    deltas: list[DeltaEntry] | None,
    deltas_fold: FoldLevel = FoldLevel.COLLAPSED,
    hint_tracker: HintTracker | None = None,
    show_file_hints: bool = False,
    workspace_dir: str | None = None,
    *,
    header_label: str = "DELTAS:",
    linked_delta_groups: Sequence[LinkedDeltaGroup] | None = None,
    indent: str = "",
    header_style: str = _COLOR_HEADER,
) -> HintTracker:
    """Build a DELTAS section from already-computed entries."""
    tracker = hint_tracker or HintTracker(
        counter=1 if show_file_hints else 0,
        mappings={},
        hook_hint_to_idx={},
        hint_to_entry_id={},
        mentor_hint_to_info={},
    )

    primary_deltas = deltas or []
    linked_groups = tuple(
        sorted(
            (group for group in linked_delta_groups or () if group.entries),
            key=lambda group: group.kind == "external",
        )
    )
    if not primary_deltas and not linked_groups:
        return tracker

    text.append(f"{indent}{header_label}", style=header_style)
    if deltas_fold == FoldLevel.COLLAPSED:
        summary_deltas = list(primary_deltas)
        for group in linked_groups:
            summary_deltas.extend(group.entries)
        _append_summary(text, summary_deltas, indent=indent)
        return tracker

    text.append("\n")
    show_line_stats = deltas_fold == FoldLevel.FULLY_EXPANDED
    hint_counter = tracker.counter
    hint_mappings = dict(tracker.mappings)
    for entry in sorted(primary_deltas, key=lambda e: e.path):
        if show_file_hints:
            hint_mappings[hint_counter] = _resolve_delta_path(entry.path, workspace_dir)
            _append_entry(
                text,
                entry,
                hint_counter,
                indent=f"{indent}  ",
                show_line_stats=show_line_stats,
            )
            hint_counter += 1
        else:
            _append_entry(
                text,
                entry,
                indent=f"{indent}  ",
                show_line_stats=show_line_stats,
            )

    for group in linked_groups:
        external = group.kind == "external"
        text.append(f"{indent}  ")
        text.append(
            EXTERNAL_REPO_GLYPH if external else WORKSPACE_GLYPH,
            style=(COLOR_EXTERNAL_REPO_GLYPH if external else COLOR_WORKSPACE_GLYPH),
        )
        text.append(" ")
        text.append(
            group.repo_name,
            style=COLOR_EXTERNAL_REPO_NAME if external else COLOR_WORKSPACE_NAME,
        )
        text.append("\n")
        for entry in sorted(group.entries, key=lambda e: e.path):
            if show_file_hints:
                hint_mappings[hint_counter] = _resolve_delta_path(
                    entry.path,
                    group.workspace_dir,
                )
                _append_entry(
                    text,
                    entry,
                    hint_counter,
                    indent=f"{indent}    ",
                    show_line_stats=show_line_stats,
                )
                hint_counter += 1
            else:
                _append_entry(
                    text,
                    entry,
                    indent=f"{indent}    ",
                    show_line_stats=show_line_stats,
                )

    return HintTracker(
        counter=hint_counter,
        mappings=hint_mappings,
        hook_hint_to_idx=tracker.hook_hint_to_idx,
        hint_to_entry_id=tracker.hint_to_entry_id,
        mentor_hint_to_info=tracker.mentor_hint_to_info,
    )
