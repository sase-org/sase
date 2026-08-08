"""Prompt-stack submit choice modal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rich.cells import cell_len
from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

if TYPE_CHECKING:
    from sase.ace.tui.widgets.prompt_stack import XPromptBinding


type PromptSubmitChoice = Literal["send", "all", "current", "write", "save_as"]


def _take_cells(value: str, width: int, *, from_right: bool = False) -> str:
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
    if width <= 0:
        return ""
    value = " ".join(value.splitlines())
    if cell_len(value) <= width:
        return value
    if width == 1:
        return "…"
    left_width = max(1, (width - 1) // 2)
    right_width = max(0, width - 1 - left_width)
    suffix = _take_cells(value, right_width, from_right=True)
    return f"{_take_cells(value, left_width)}…{suffix}"


@dataclass(frozen=True)
class _PromptSubmitChoiceRow:
    key: str
    title: str
    subtitle: str
    result: PromptSubmitChoice
    tone: str = ""
    summary: str | None = None


class PromptSubmitChoiceModal(ModalScreen[PromptSubmitChoice | None]):
    """Single-key chooser for ambiguous prompt-stack submit intent."""

    BINDINGS = [
        Binding("s", "choose_send", "Send", show=False),
        Binding("a", "choose_all", "Submit all", show=False),
        Binding("ctrl+s", "choose_all", "Submit all", show=False),
        Binding("c", "choose_current", "Submit current", show=False),
        Binding("w", "choose_write", "Write xprompt", show=False),
        Binding("X", "choose_save_as", "Save as xprompt", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        *,
        prompt_count: int,
        pane_count: int | None = None,
        target: XPromptBinding | None = None,
        is_dirty: bool = False,
    ) -> None:
        super().__init__()
        self._prompt_count = max(0, prompt_count)
        self._pane_count = max(0, prompt_count if pane_count is None else pane_count)
        self._target = target
        self._is_dirty = is_dirty

    def compose(self) -> ComposeResult:
        rows = self._choice_rows()
        with Container(
            id="prompt-submit-choice-container",
            classes="duration-choice-container",
        ):
            with Vertical(
                id="prompt-submit-choice-body",
                classes="duration-choice-body",
            ):
                yield Label(
                    "Submit prompt stack",
                    id="prompt-submit-choice-title",
                    classes="duration-choice-title",
                )
                for row in rows:
                    yield Static(
                        self._render_choice(row.key, row.title, row.subtitle),
                        classes=self._row_classes(row),
                    )
                yield Static(
                    "",
                    classes="prompt-submit-choice-spacer duration-choice-spacer",
                )
                yield Static(
                    f"  [dim]{self._summary_line(rows)}[/]",
                    classes="prompt-submit-choice-row duration-choice-row",
                )

    def _choice_rows(self) -> list[_PromptSubmitChoiceRow]:
        rows: list[_PromptSubmitChoiceRow] = []
        is_multi_pane = self._pane_count > 1
        if self._target is not None and not is_multi_pane:
            rows.append(
                _PromptSubmitChoiceRow(
                    "s",
                    "Send",
                    "Launch this draft as one agent.",
                    "send",
                    tone="primary",
                    summary="s send",
                )
            )
        if is_multi_pane:
            if self._target is None:
                rows.extend(
                    [
                        _PromptSubmitChoiceRow(
                            "a",
                            "Submit all",
                            self._all_subtitle(),
                            "all",
                            tone="primary",
                            summary="a/^S all",
                        ),
                        _PromptSubmitChoiceRow(
                            "c",
                            "Submit current",
                            "Launch only the selected prompt as a single agent.",
                            "current",
                            summary="c current",
                        ),
                    ]
                )
            else:
                rows.extend(
                    [
                        _PromptSubmitChoiceRow(
                            "a",
                            f"Launch all {self._prompt_count}",
                            self._all_subtitle(),
                            "all",
                            tone="primary",
                            summary="a/^S all",
                        ),
                        _PromptSubmitChoiceRow(
                            "c",
                            "Launch current",
                            "Launch only the selected prompt as a single agent.",
                            "current",
                            summary="c current",
                        ),
                    ]
                )
        if self._target is not None:
            rows.extend(
                [
                    _PromptSubmitChoiceRow(
                        "w",
                        f"Save to {self._target_chip()}",
                        self._write_subtitle(),
                        "write",
                        tone="accent",
                        summary="w save",
                    ),
                    _PromptSubmitChoiceRow(
                        "X",
                        "Save as a new xprompt…",
                        "Fork this definition to a new location.",
                        "save_as",
                        summary="X save as",
                    ),
                ]
            )
        return rows

    def _all_subtitle(self) -> str:
        noun = "prompt" if self._prompt_count == 1 else "prompts"
        return f"Launch all {self._prompt_count} {noun} as one xprompt swarm."

    def _target_chip(self) -> str:
        if self._target is None:
            return ""
        theme = self._current_theme()
        foreground = self._theme_color(theme, "background", "black")
        background = self._theme_color(theme, "secondary", "cyan")
        return (
            f"[bold {foreground} on {background}] ✎ "
            f"{escape(self._target.reference)} [/]"
        )

    def _write_subtitle(self) -> str:
        if self._target is None:
            return ""
        if not self._is_dirty:
            return "No unsaved changes since the last save."
        return (
            f"Overwrite {escape(self._display_path(self._target.write_path))} "
            "with your edits."
        )

    @staticmethod
    def _display_path(path: str) -> str:
        home = str(Path.home())
        if path.startswith(home + "/"):
            path = "~" + path[len(home) :]
        return _middle_elide_cells(path, 20)

    @staticmethod
    def _render_choice(key: str, title: str, subtitle: str) -> str:
        return f"  [bold]{key}[/]   [bold]{title}[/]\n      [dim]{subtitle}[/]"

    def _current_theme(self) -> object | None:
        try:
            return self.app.current_theme
        except Exception:
            return None

    @staticmethod
    def _theme_color(theme: object | None, attr: str, fallback: str) -> str:
        if theme is not None:
            color = getattr(theme, attr, None)
            if color:
                return str(color)
        return fallback

    @staticmethod
    def _row_classes(row: _PromptSubmitChoiceRow) -> str:
        classes = "prompt-submit-choice-row duration-choice-row"
        if row.tone:
            classes = f"{classes} duration-choice-tone-{row.tone}"
        return classes

    @staticmethod
    def _summary_line(rows: list[_PromptSubmitChoiceRow]) -> str:
        rendered = [row.summary or f"{row.key} {row.result}" for row in rows]
        rendered.append("esc cancel")
        return " · ".join(rendered)

    def action_choose_send(self) -> None:
        """Submit the single targeted pane."""
        if self._target is not None and self._pane_count <= 1:
            self.dismiss("send")

    def action_choose_all(self) -> None:
        """Submit every non-empty pane."""
        if self._pane_count > 1:
            self.dismiss("all")

    def action_choose_current(self) -> None:
        """Submit only the selected pane."""
        if self._pane_count > 1:
            self.dismiss("current")

    def action_choose_write(self) -> None:
        """Write the targeted xprompt definition."""
        if self._target is not None:
            self.dismiss("write")

    def action_choose_save_as(self) -> None:
        """Fork the targeted definition to a new xprompt."""
        if self._target is not None:
            self.dismiss("save_as")

    def action_cancel(self) -> None:
        """Close without submitting."""
        self.dismiss(None)


__all__ = ["PromptSubmitChoice", "PromptSubmitChoiceModal"]
