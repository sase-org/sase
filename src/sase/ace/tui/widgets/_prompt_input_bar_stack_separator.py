"""Width-aware separator widget for prompt-stack panes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_cursor_readout import (
    cursor_readout_cell_width,
    format_cursor_readout,
)

_STACK_SEPARATOR_RULE = "─"
_STACK_SEPARATOR_ACTIVE_MARKER = "▍"


def _take_cells(value: str, width: int, *, from_right: bool = False) -> str:
    """Return a prefix/suffix of *value* that fits in *width* terminal cells."""
    if width <= 0:
        return ""
    chars = reversed(value) if from_right else iter(value)
    used = 0
    taken: list[str] = []
    for char in chars:
        char_width = max(cell_len(char), 0)
        if used + char_width > width:
            break
        taken.append(char)
        used += char_width
    if from_right:
        taken.reverse()
    return "".join(taken)


def _middle_elide_cells(value: str, width: int) -> str:
    """Fit *value* in *width* cells, preserving the path tail."""
    if width <= 0:
        return ""
    if cell_len(value) <= width:
        return value
    if width == 1:
        return "…"
    left_width = max(1, (width - 1) // 2)
    right_width = max(0, width - 1 - left_width)
    suffix = _take_cells(value, right_width, from_right=True)
    return f"{_take_cells(value, left_width)}…{suffix}"


@dataclass(frozen=True)
class SnippetSeparatorInfo:
    """The chip/destination/state data the snippet pane's separator renders."""

    trigger: str
    destination: str
    state: str  # "clean" | "dirty" | "new"


@dataclass(frozen=True)
class MiniXPromptSeparatorInfo:
    """The chip/destination/state data the mini-xprompt separator renders."""

    name: str
    destination: str
    state: str  # "clean" | "dirty" | "new" | "stale"


class PromptStackSeparator(Static):
    """Width-aware separator row for one prompt-stack pane."""

    def __init__(
        self,
        label: str,
        *,
        active: bool = False,
        snippet: SnippetSeparatorInfo | None = None,
        mini_xprompt: MiniXPromptSeparatorInfo | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__("", **kwargs)
        self.label = label
        self.active = active
        self.snippet = snippet
        self.mini_xprompt = mini_xprompt
        self.position: tuple[int, int] | None = None
        self.vim_mode: str = "insert"

    def set_active(self, active: bool) -> None:
        """Update active state and refresh the rendered rule when it changes."""
        if self.active == active:
            return
        self.active = active
        self.refresh()

    def set_snippet_info(self, info: SnippetSeparatorInfo | None) -> None:
        """Replace the snippet chip/destination/marker, no-op when unchanged."""
        if self.snippet == info:
            return
        self.snippet = info
        self.refresh()

    def set_mini_xprompt_info(self, info: MiniXPromptSeparatorInfo | None) -> None:
        """Replace the mini-xprompt chip/destination/marker when changed."""
        if self.mini_xprompt == info:
            return
        self.mini_xprompt = info
        self.refresh()

    def set_position(
        self, position: tuple[int, int] | None, vim_mode: str = "insert"
    ) -> None:
        """Update the parked-pane cursor readout, no-op when nothing changed."""
        if self.position == position and self.vim_mode == vim_mode:
            return
        self.position = position
        self.vim_mode = vim_mode
        self.refresh()

    def render(self) -> Text:
        """Render a centered pane label connected by full-width hairline rules."""
        width = max(0, int(self.size.width))
        if self.snippet is not None:
            return self._render_snippet(width)
        if self.mini_xprompt is not None:
            return self._render_mini_xprompt(width)

        label = self.label
        if self.active:
            label = f"{_STACK_SEPARATOR_ACTIVE_MARKER} {label}"
        padded_label = f" {label} "
        label_width = cell_len(padded_label)
        label_style = "bold" if self.active else "dim"

        if width <= label_width:
            text = Text(padded_label.strip(), no_wrap=True, overflow="ellipsis")
            text.truncate(width, overflow="ellipsis")
            text.stylize(label_style)
            return text

        rule_width = width - label_width
        left_width = rule_width // 2
        right_width = rule_width - left_width
        text = Text(no_wrap=True, overflow="crop")
        text.append(_STACK_SEPARATOR_RULE * left_width, style="dim")
        text.append(padded_label, style=label_style)
        text.append_text(self._render_right_rule(right_width))
        return text

    def _theme_color(self, attr: str, fallback: str) -> str:
        """Return a theme color by attribute name, falling back outside an app."""
        try:
            theme = self.app.current_theme
        except Exception:
            return fallback
        color = getattr(theme, attr, None)
        return str(color) if color else fallback

    def _snippet_marker(self) -> tuple[str, str]:
        """Return ``(text, style)`` for the snippet pane's state marker."""
        info = self.snippet
        assert info is not None
        if info.state == "new":
            return "new", f"bold {self._theme_color('success', 'green')}"
        if info.state == "dirty":
            return "●", f"bold {self._theme_color('warning', 'yellow')}"
        return "✓", "dim"

    def _mini_xprompt_marker(self) -> tuple[str, str]:
        """Return ``(text, style)`` for the mini-xprompt pane's state marker."""
        info = self.mini_xprompt
        assert info is not None
        if info.state == "new":
            return "new", f"bold {self._theme_color('success', 'green')}"
        if info.state == "dirty":
            return "●", f"bold {self._theme_color('warning', 'yellow')}"
        if info.state == "stale":
            return (
                "⚠ changed on disk",
                f"bold {self._theme_color('warning', 'yellow')}",
            )
        return "✓", "dim"

    def _render_snippet(self, width: int) -> Text:
        """Render the trigger-labeled title bar for the pinned snippet pane.

        Unlike the centered agent label, this row reads left-to-right: the
        ``⇥ <trigger>`` chip, the destination file (dim, middle-elided so a
        deep path never overruns the rule), then a truthful state marker.
        """
        info = self.snippet
        assert info is not None
        chip_prefix = f"{_STACK_SEPARATOR_ACTIVE_MARKER} " if self.active else ""
        chip = f"{chip_prefix}⇥ {info.trigger}"
        chip_style = "bold" if self.active else "dim"
        marker_text, marker_style = self._snippet_marker()

        fixed_width = cell_len(f"  {chip}   {marker_text}  ")
        dest_budget = max(0, width - fixed_width)
        destination = (
            _middle_elide_cells(info.destination, dest_budget)
            if info.destination and dest_budget > 0
            else ""
        )

        body = Text(no_wrap=True, overflow="crop")
        body.append(" ")
        body.append(chip, style=chip_style)
        if destination:
            body.append(" · ", style="dim")
            body.append(destination, style="dim")
        body.append(" ")
        body.append(marker_text, style=marker_style)
        body.append(" ")
        label_width = body.cell_len

        if width <= label_width:
            text = body.copy()
            text.no_wrap = True
            text.overflow = "ellipsis"
            text.truncate(width, overflow="ellipsis")
            return text

        rule_width = width - label_width
        left_width = rule_width // 2
        right_width = rule_width - left_width
        text = Text(no_wrap=True, overflow="crop")
        text.append(_STACK_SEPARATOR_RULE * left_width, style="dim")
        text.append_text(body)
        text.append_text(self._render_right_rule(right_width))
        return text

    def _render_mini_xprompt(self, width: int) -> Text:
        """Render the name-labeled title bar for a pinned mini-xprompt pane."""
        info = self.mini_xprompt
        assert info is not None
        chip_prefix = f"{_STACK_SEPARATOR_ACTIVE_MARKER} " if self.active else ""
        chip = f"{chip_prefix}#{info.name}"
        chip_style = "bold" if self.active else "dim"
        marker_text, marker_style = self._mini_xprompt_marker()

        fixed_width = cell_len(f"  {chip}   {marker_text}  ")
        dest_budget = max(0, width - fixed_width)
        destination = (
            _middle_elide_cells(info.destination, dest_budget)
            if info.destination and dest_budget > 0
            else ""
        )

        body = Text(no_wrap=True, overflow="crop")
        body.append(" ")
        body.append(chip, style=chip_style)
        if destination:
            body.append(" · ", style="dim")
            body.append(destination, style="dim")
        body.append(" ")
        body.append(marker_text, style=marker_style)
        body.append(" ")
        label_width = body.cell_len

        if width <= label_width:
            text = body.copy()
            text.no_wrap = True
            text.overflow = "ellipsis"
            text.truncate(width, overflow="ellipsis")
            return text

        rule_width = width - label_width
        left_width = rule_width // 2
        right_width = rule_width - left_width
        text = Text(no_wrap=True, overflow="crop")
        text.append(_STACK_SEPARATOR_RULE * left_width, style="dim")
        text.append_text(body)
        text.append_text(self._render_right_rule(right_width))
        return text

    def _render_right_rule(self, right_width: int) -> Text:
        """Return the right-hand rule run, carrying the readout when it fits.

        The centered-label math above never changes: this only decides how
        the *already allotted* right-hand rule cells are spent.  When the
        readout does not fit alongside at least one rule cell on each side,
        it is omitted entirely -- never abbreviated to a second format.
        """
        if self.position is not None:
            line, column = self.position
            chip_cells = cursor_readout_cell_width(line, column) + 2
            if right_width >= chip_cells + 2:
                dash_count = right_width - chip_cells - 1
                text = Text(no_wrap=True, overflow="crop")
                text.append(_STACK_SEPARATOR_RULE * dash_count, style="dim")
                text.append(" ")
                text.append_text(
                    format_cursor_readout(line, column, vim_mode=self.vim_mode)
                )
                text.append(" ")
                text.append(_STACK_SEPARATOR_RULE, style="dim")
                return text
        return Text(_STACK_SEPARATOR_RULE * right_width, style="dim")
