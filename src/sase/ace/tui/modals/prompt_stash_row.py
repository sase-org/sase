"""Shared row rendering helpers for prompt-stash picker modals."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.prompt_stash_entries import entry_prompt_segments
from sase.core.prompt_stash_wire import PromptStashEntryWire
from sase.notifications.models import format_relative_time

# The fallback preserves the fixed 96-column modal's historical row layout.
# Split-pane callers derive a smaller/larger budget from the laid-out list.
INDEX_KEYS = "1234567890"
PIN_GLYPH = "📌"

_SHORTCUT_WIDTH = 4
_SHORTCUT_STYLE = "bold black on #AF87FF"
DEFAULT_STASH_PREVIEW_WIDTH = 36
_MIN_PREVIEW_WIDTH = 8
_OPTION_HORIZONTAL_PADDING_WIDTH = 2
_ROW_FIXED_WIDTH = 47
_PROJECT_WIDTH = 14
_AGE_WIDTH = 9
_BUNDLE_WIDTH = 10
_PROJECT_PLACEHOLDER = "—"


def first_line_preview(text: str, width: int) -> str:
    """Return the first non-blank line of *text*, truncated to *width*."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            preview = stripped
            break
    else:
        preview = text.strip()
    if len(preview) <= width:
        return preview
    if width <= 1:
        return preview[:width]
    return f"{preview[: width - 1]}…"


def prompt_stash_preview_width_for_list_content(list_content_width: int) -> int:
    """Return the row-preview budget for a laid-out option-list width."""
    if list_content_width <= 0:
        return DEFAULT_STASH_PREVIEW_WIDTH
    return max(
        _MIN_PREVIEW_WIDTH,
        list_content_width - _OPTION_HORIZONTAL_PADDING_WIDTH - _ROW_FIXED_WIDTH,
    )


def _project_chip(project: str | None) -> str:
    """Return a fixed-width originating-project chip for a stash row."""
    label = project if project else _PROJECT_PLACEHOLDER
    if len(label) > _PROJECT_WIDTH:
        label = f"{label[: _PROJECT_WIDTH - 1]}…"
    return label.ljust(_PROJECT_WIDTH)


def _bundle_chip(prompt_count: int) -> str:
    """Return a fixed-width bundle marker for a stash row."""
    label = f"{prompt_count} prompts" if prompt_count > 1 else ""
    if len(label) > _BUNDLE_WIDTH:
        label = f"{label[: _BUNDLE_WIDTH - 1]}…"
    return label.ljust(_BUNDLE_WIDTH)


def append_shortcut(text: Text, shortcut: str | None) -> None:
    """Append the fixed-width digit shortcut gutter to *text*."""
    if shortcut is None:
        text.append(" " * _SHORTCUT_WIDTH)
        return
    text.append(f" {shortcut} ", style=_SHORTCUT_STYLE)
    text.append(" ")


def stash_row_label(
    entry: PromptStashEntryWire,
    *,
    marked_for_pop: bool,
    marked_for_delete: bool,
    pinned: bool,
    age: str,
    prompt_count: int = 1,
    preview_width: int = DEFAULT_STASH_PREVIEW_WIDTH,
) -> Text:
    """Build the styled single-line label for one stash row.

    Kept as a pure helper (no widget access) so row rendering can be unit
    tested without a running app. ``age`` is the already-formatted relative
    time so callers control the clock.
    """
    text = Text(no_wrap=True, overflow="ellipsis")
    if marked_for_delete:
        text.append("✗ ", style="bold red")
    elif marked_for_pop:
        text.append("✓ ", style="bold #AF87FF")
    else:
        text.append("  ")

    row_style = "dim strike" if marked_for_delete else ""
    if pinned:
        text.append(PIN_GLYPH, style=row_style or "bold #FFD75F")
    else:
        text.append("  ")
    restoring = marked_for_pop
    text.append(
        age.rjust(_AGE_WIDTH), style="dim" if not marked_for_delete else row_style
    )
    text.append("  ")
    text.append(
        _project_chip(entry.project),
        style="cyan" if not marked_for_delete else row_style,
    )
    text.append("  ")
    text.append(
        _bundle_chip(prompt_count),
        style="magenta" if prompt_count > 1 and not marked_for_delete else row_style,
    )
    text.append("  ")
    preview = first_line_preview(entry.text, preview_width)
    text.append(preview, style=row_style or ("bold" if restoring else ""))
    return text


def stash_row_prompt_count(entry: PromptStashEntryWire) -> int:
    """Return how many prompt panes one stash row represents."""
    return len(entry_prompt_segments(entry))


def stash_row_age(entry: PromptStashEntryWire) -> str:
    """Return the display age for one stash row."""
    return format_relative_time(entry.created_at)


__all__ = [
    "INDEX_KEYS",
    "PIN_GLYPH",
    "DEFAULT_STASH_PREVIEW_WIDTH",
    "append_shortcut",
    "first_line_preview",
    "prompt_stash_preview_width_for_list_content",
    "stash_row_age",
    "stash_row_label",
    "stash_row_prompt_count",
]
