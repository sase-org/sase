"""Editor controls and typed searchable picker for provider creation forms."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets._option_list import Option

from sase.workspace_provider._hookspec import RepoCreationChoice

from ..modals.new_project_rendering import clean_source_text
from .single_line_vim_text_area import SingleLineVimTextArea
from .vim_mode_routing import VimModeRoutingMixin
from .vim_text_area import VimTextArea


class RepoCreationLineEditor(VimModeRoutingMixin, SingleLineVimTextArea):
    """Single-line provider field with normal ACE vim-mode routing."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("soft_wrap", True)
        super().__init__(*args, **kwargs)


class RepoCreationTextEditor(VimModeRoutingMixin, VimTextArea):
    """Multiline provider field with normal ACE vim-mode routing."""

    DEFAULT_CSS = """
    RepoCreationTextEditor {
        width: 100%;
        height: 6;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("show_line_numbers", False)
        kwargs.setdefault("tab_behavior", "focus")
        super().__init__(*args, **kwargs)
        self.show_line_numbers = False


class RepoCreationSearchPicker(ModalScreen[str | None]):
    """Search declared provider choices or accept a typed canonical value."""

    DEFAULT_CSS = """
    RepoCreationSearchPicker {
        align: center middle;
    }
    #repo-creation-search-dialog {
        width: 78;
        max-width: 92%;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #repo-creation-search-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #repo-creation-search-options {
        height: auto;
        max-height: 14;
        margin-top: 1;
    }
    #repo-creation-search-status {
        color: $warning;
        height: auto;
        margin-top: 1;
    }
    #repo-creation-search-footer {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        label: str,
        choices: tuple[RepoCreationChoice, ...],
        *,
        current: str = "",
    ) -> None:
        super().__init__()
        self._label = clean_source_text(label)
        self._choices = choices
        self._current = current
        self._visible: list[RepoCreationChoice] = []
        self._highlighted = -1
        self._moved_with_arrows = False

    def compose(self) -> ComposeResult:
        with Vertical(id="repo-creation-search-dialog"):
            yield Static(
                Text(f"{self._label} · search or enter a value"),
                id="repo-creation-search-title",
            )
            yield Input(placeholder="Search choices or type a canonical value")
            yield OptionList(id="repo-creation-search-options")
            yield Static("", id="repo-creation-search-status")
            yield Static(
                "enter use typed value · ↑/↓ choose suggestion · esc cancel",
                id="repo-creation-search-footer",
            )

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self._refresh_options("")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._moved_with_arrows = False
        self._set_status("")
        self._refresh_options(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value
        exact = self._exact_choice(query)
        if exact is not None:
            if exact.disabled_reason:
                self._set_status(exact.disabled_reason)
                return
            self.dismiss(exact.value)
            return
        if self._moved_with_arrows and 0 <= self._highlighted < len(self._visible):
            choice = self._visible[self._highlighted]
            if choice.disabled_reason:
                self._set_status(choice.disabled_reason)
                return
            self.dismiss(choice.value)
            return
        if query.strip():
            self.dismiss(query.strip())

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        try:
            choice = self._visible[int(event.option.id or "")]
        except (ValueError, IndexError):
            return
        if choice.disabled_reason:
            self._set_status(choice.disabled_reason)
            return
        self.dismiss(choice.value)

    def on_key(self, event: events.Key) -> None:
        if event.key not in {"up", "down"} or not self._visible:
            return
        event.prevent_default()
        event.stop()
        direction = 1 if event.key == "down" else -1
        self._move_highlight(direction)

    def _refresh_options(self, query: str) -> None:
        needle = query.casefold()
        self._visible = [
            choice
            for choice in self._choices
            if not needle
            or needle
            in " ".join(
                (choice.value, choice.label, choice.description, choice.disabled_reason)
            ).casefold()
        ]
        if self._current and not needle:
            self._highlighted = next(
                (
                    index
                    for index, choice in enumerate(self._visible)
                    if choice.value == self._current and not choice.disabled_reason
                ),
                0 if self._visible else -1,
            )
        else:
            self._highlighted = 0 if self._visible else -1
        if not self.is_mounted:
            return
        options = self.query_one("#repo-creation-search-options", OptionList)
        options.clear_options()
        for index, choice in enumerate(self._visible):
            label = Text(choice.label or choice.value)
            if choice.label and choice.label != choice.value:
                label.append(f"  {choice.value}", style="dim")
            if choice.disabled_reason:
                label.append(f"  · unavailable: {choice.disabled_reason}", style="dim")
            options.add_option(
                Option(label, id=str(index), disabled=bool(choice.disabled_reason))
            )
        if self._highlighted >= 0:
            options.highlighted = self._highlighted

    def _move_highlight(self, delta: int) -> None:
        if not self._visible:
            return
        self._moved_with_arrows = True
        self._highlighted = max(
            0, min(self._highlighted + delta, len(self._visible) - 1)
        )
        self.query_one(
            "#repo-creation-search-options", OptionList
        ).highlighted = self._highlighted

    def _exact_choice(self, query: str) -> RepoCreationChoice | None:
        folded = query.strip().casefold()
        if not folded:
            return None
        return next(
            (
                choice
                for choice in self._choices
                if choice.value.casefold() == folded
                or (choice.label and choice.label.casefold() == folded)
            ),
            None,
        )

    def _set_status(self, message: str) -> None:
        if self.is_mounted:
            self.query_one("#repo-creation-search-status", Static).update(
                Text(clean_source_text(message))
            )


def choice_label(choice: RepoCreationChoice) -> Text:
    label = clean_source_text(choice.label or choice.value)
    value = clean_source_text(choice.value)
    text = Text(label)
    if value != label:
        text.append(f"  [{value}]", style="dim")
    return text


def search_button_text(value: str) -> Text:
    if not value:
        return Text("Type or choose a value…", style="dim")
    return Text(f"{clean_source_text(value)}  · choose/change…")


def boolean_spellings(value: str) -> tuple[str, str]:
    folded = value.casefold()
    pairs = {
        "true": ("true", "false"),
        "false": ("true", "false"),
        "yes": ("yes", "no"),
        "no": ("yes", "no"),
        "on": ("on", "off"),
        "off": ("on", "off"),
        "1": ("1", "0"),
        "0": ("1", "0"),
    }
    true_value, false_value = pairs.get(folded, ("true", "false"))
    if value.isupper():
        return true_value.upper(), false_value.upper()
    if value.istitle():
        return true_value.title(), false_value.title()
    return true_value, false_value


def bool_is_true(value: str) -> bool:
    return value.casefold() in {"true", "1", "yes", "on"}


__all__ = [
    "RepoCreationLineEditor",
    "RepoCreationSearchPicker",
    "RepoCreationTextEditor",
    "bool_is_true",
    "boolean_spellings",
    "choice_label",
    "search_button_text",
]
