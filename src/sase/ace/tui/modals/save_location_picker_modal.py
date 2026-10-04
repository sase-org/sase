"""Shared save-location picker modal for location-first save flows.

The modal is presentation-only: it renders choices built by
:mod:`save_location_choices`, handles hotkeys, highlight movement, the
collapsed plugin section, and the loading / type-ahead contract. All disk
I/O stays with the orchestrator, which pushes this modal synchronously and
feeds it via :meth:`set_choices`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from .save_location_choices import SaveLocationChoice, SaveLocationPick

SaveLocationPickerKind = Literal["macro", "snippet"]

STEPPER_TEXT = "● Location › ○ Name"

_LOADING_OPTION_ID = "__loading__"
_ERROR_OPTION_ID = "__error__"
_EMPTY_OPTION_ID = "__empty__"
_SUMMARY_OPTION_ID = "__plugins_summary__"


def _choice_option_id(choice_id: str) -> str:
    return f"choice__{choice_id}"


class SaveLocationPickerModal(ModalScreen[SaveLocationPick | None]):
    """Pick where a new mini-macro or snippet will live.

    Push synchronously, then feed loaded choices with :meth:`set_choices`.
    Keys typed while loading are buffered: the first hotkey (or Enter)
    becomes the pending pick and later keystrokes become type-ahead carried
    into the name step.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        kind: SaveLocationPickerKind,
        title: str,
        choices: Sequence[SaveLocationChoice] | None = None,
        highlight_id: str | None = None,
        notice: str | None = None,
    ) -> None:
        super().__init__()
        self._kind = kind
        self._title = title
        self._choices: tuple[SaveLocationChoice, ...] = ()
        self._loaded = choices is not None
        self._load_error: str | None = None
        self._notice = notice or ""
        self._default_id: str | None = None
        self._highlight_id: str | None = None
        self._expanded = False
        self._pending: str | None = None
        self._typeahead = ""
        self._error: str | None = None
        self._dismissed = False
        if choices is not None:
            self._adopt_choices(tuple(choices), highlight_id)

    @property
    def kind(self) -> SaveLocationPickerKind:
        return self._kind

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def pending_pick(self) -> str | None:
        """Return the hotkey (or ``"enter"``) buffered while loading."""
        return self._pending

    @property
    def typeahead(self) -> str:
        return self._typeahead

    @property
    def highlighted_id(self) -> str | None:
        return self._highlight_id

    def set_choices(
        self,
        choices: Sequence[SaveLocationChoice],
        *,
        highlight_id: str | None = None,
    ) -> None:
        """Deliver loaded choices and resolve any buffered pick."""
        if self._dismissed:
            return
        self._loaded = True
        self._load_error = None
        self._error = None
        self._adopt_choices(tuple(choices), highlight_id)
        if self._pending is not None:
            pending = self._pending
            typeahead = self._typeahead
            self._pending = None
            if pending == "enter":
                if self._default_id is not None:
                    self._dismiss_once(SaveLocationPick(self._default_id, typeahead))
                    return
                self._typeahead = ""
            else:
                target = self._hotkey_map().get(pending)
                if target is not None and target.disabled_reason is None:
                    self._dismiss_once(SaveLocationPick(target.choice_id, typeahead))
                    return
                if target is not None and target.disabled_reason is not None:
                    self._error = f"✗ {target.display_path}: {target.disabled_reason}"
                else:
                    self._error = f"✗ no destination on {pending}"
                self._typeahead = ""
        self._rebuild()

    def set_load_error(self, message: str) -> None:
        """Show a load failure. ``Esc`` closes from this state."""
        if self._dismissed:
            return
        self._load_error = message
        self._pending = None
        self._typeahead = ""
        self._rebuild()

    def set_notice(self, message: str) -> None:
        """Show a footer notice line (for example a fallback warning)."""
        if self._dismissed:
            return
        self._notice = message or ""
        if not self.is_mounted:
            return
        try:
            existing = self.query_one("#save-location-picker-notice", Static)
        except Exception:
            existing = None
        if existing is not None:
            existing.update(self._notice)
            return
        if not self._notice:
            return
        try:
            container = self.query_one("#save-location-picker-container", Container)
            hints = self.query_one("#save-location-picker-hints", Static)
        except Exception:
            return
        container.mount(
            Static(self._notice, id="save-location-picker-notice"),
            before=hints,
        )

    def compose(self) -> ComposeResult:
        with Container(id="save-location-picker-container"):
            with Horizontal(id="save-location-picker-header"):
                yield Label(self._title, id="save-location-picker-title")
                yield Label(STEPPER_TEXT, id="save-location-picker-stepper")
            yield OptionList(*self._build_options(), id="save-location-picker-list")
            yield Static("", id="save-location-picker-preview")
            if self._notice:
                yield Static(self._notice, id="save-location-picker-notice")
            yield Static("", id="save-location-picker-hints")

    def on_mount(self) -> None:
        self.call_after_refresh(self._finish_mount)

    def _finish_mount(self) -> None:
        try:
            option_list = self.query_one("#save-location-picker-list", OptionList)
        except Exception:
            return
        option_list.can_focus = False
        option_list.highlighted = self._highlight_option_index()
        self._refresh_footer()

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.action_cancel()
            return
        if not self._loaded:
            self._on_key_loading(event)
            return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self._select_highlighted()
            return
        if event.key in ("j", "down", "ctrl+n"):
            event.prevent_default()
            event.stop()
            self._move_highlight(1)
            return
        if event.key in ("k", "up", "ctrl+p"):
            event.prevent_default()
            event.stop()
            self._move_highlight(-1)
            return
        if event.key == "q":
            event.prevent_default()
            event.stop()
            self.action_cancel()
            return
        character = event.character or ""
        if character == "+" or event.key == "plus":
            event.prevent_default()
            event.stop()
            self._toggle_collapsed()
            return
        if len(character) == 1 and character != " ":
            event.prevent_default()
            event.stop()
            self._press_hotkey(character)
            return
        event.prevent_default()
        event.stop()

    def _on_key_loading(self, event: events.Key) -> None:
        if self._load_error is not None:
            event.prevent_default()
            event.stop()
            if event.key == "q":
                self.action_cancel()
            return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            if self._pending is None:
                self._pending = "enter"
            return
        if event.key == "backspace":
            event.prevent_default()
            event.stop()
            self._typeahead = self._typeahead[:-1]
            return
        if event.key == "q" and self._pending is None:
            event.prevent_default()
            event.stop()
            self.action_cancel()
            return
        character = event.character or ""
        if len(character) == 1 and character.isprintable():
            event.prevent_default()
            event.stop()
            if self._pending is None:
                self._pending = character
            else:
                self._typeahead += character
            return
        event.prevent_default()
        event.stop()

    def action_cancel(self) -> None:
        self._dismiss_once(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = str(event.option.id) if event.option.id is not None else ""
        if option_id == _SUMMARY_OPTION_ID:
            event.prevent_default()
            event.stop()
            self._toggle_collapsed()
            return
        choice = self._choice_for_option(option_id)
        if choice is not None and choice.disabled_reason is None:
            self._dismiss_once(SaveLocationPick(choice.choice_id, ""))

    def _select_highlighted(self) -> None:
        if self._summary_highlighted():
            self._toggle_collapsed()
            return
        choice = self._highlighted_choice()
        if choice is not None and choice.disabled_reason is None:
            self._dismiss_once(SaveLocationPick(choice.choice_id, ""))

    def _press_hotkey(self, character: str) -> None:
        target = self._hotkey_map().get(character)
        if target is None:
            return
        if target.disabled_reason is not None:
            self._error = f"✗ {target.display_path}: {target.disabled_reason}"
            self._rebuild()
            return
        self._dismiss_once(SaveLocationPick(target.choice_id, ""))

    def _move_highlight(self, direction: int) -> None:
        positions = self._highlightable_positions()
        if not positions:
            return
        option_index = self._highlight_option_index()
        if option_index is None or option_index not in positions:
            fallback = 0 if direction > 0 else len(positions) - 1
            self._apply_highlight(positions[fallback])
            return
        current = positions.index(option_index)
        self._apply_highlight(positions[(current + direction) % len(positions)])

    def _apply_highlight(self, option_index: int) -> None:
        kinds = self._option_kinds()
        if 0 <= option_index < len(kinds):
            kind, choice = kinds[option_index]
            if kind == "summary":
                self._highlight_id = _SUMMARY_OPTION_ID
            elif kind == "choice" and choice is not None:
                self._highlight_id = choice.choice_id
            else:
                return
        self._error = None
        if not self.is_mounted:
            return
        try:
            option_list = self.query_one("#save-location-picker-list", OptionList)
        except Exception:
            return
        option_list.highlighted = option_index
        self._refresh_footer()

    def _toggle_collapsed(self) -> None:
        if not any(choice.collapsed_group for choice in self._choices):
            return
        self._expanded = not self._expanded
        self._rebuild()

    def _adopt_choices(
        self,
        choices: tuple[SaveLocationChoice, ...],
        highlight_id: str | None,
    ) -> None:
        self._choices = choices
        self._default_id = next(
            (
                choice.choice_id
                for choice in choices
                if choice.is_default
                and choice.disabled_reason is None
                and choice.kind != "existing"
            ),
            next(
                (
                    choice.choice_id
                    for choice in choices
                    if choice.disabled_reason is None and choice.kind != "existing"
                ),
                None,
            ),
        )
        self._expanded = any(
            choice.collapsed_group
            and (
                choice.is_default
                or any(badge in ("● current", "★ current") for badge in choice.badges)
            )
            for choice in choices
        )
        highlightables = {
            choice.choice_id for choice in choices if choice.disabled_reason is None
        }
        if highlight_id is not None and highlight_id in highlightables:
            self._highlight_id = highlight_id
            if any(
                choice.choice_id == highlight_id and choice.collapsed_group
                for choice in choices
            ):
                self._expanded = True
        else:
            self._highlight_id = self._default_id

    def _hotkey_map(self) -> dict[str, SaveLocationChoice]:
        return {choice.hotkey: choice for choice in self._choices if choice.hotkey}

    def _choice_for_option(self, option_id: str) -> SaveLocationChoice | None:
        if not option_id.startswith("choice__"):
            return None
        choice_id = option_id.removeprefix("choice__")
        return next(
            (choice for choice in self._choices if choice.choice_id == choice_id),
            None,
        )

    def _option_kinds(self) -> list[tuple[str, SaveLocationChoice | None]]:
        kinds: list[tuple[str, SaveLocationChoice | None]] = []
        sections: list[str] = []
        for choice in self._visible_choices():
            if choice.section not in sections:
                sections.append(choice.section)
                kinds.append(("header", None))
            kinds.append(("choice", choice))
        if self._collapsed_summary_count() is not None:
            kinds.append(("summary", None))
        return kinds

    def _visible_choices(self) -> list[SaveLocationChoice]:
        if self._expanded:
            return list(self._choices)
        return [choice for choice in self._choices if not choice.collapsed_group]

    def _collapsed_summary_count(self) -> int | None:
        collapsed = [choice for choice in self._choices if choice.collapsed_group]
        if not collapsed or self._expanded:
            return None
        return len(collapsed)

    def _highlightable_positions(self) -> list[int]:
        positions: list[int] = []
        for index, (kind, choice) in enumerate(self._option_kinds()):
            if kind == "summary":
                positions.append(index)
            elif kind == "choice" and choice is not None:
                if choice.disabled_reason is None:
                    positions.append(index)
        return positions

    def _highlight_option_index(self) -> int | None:
        kinds = self._option_kinds()
        for index, (kind, choice) in enumerate(kinds):
            if kind == "summary" and self._highlight_id == _SUMMARY_OPTION_ID:
                return index
            if (
                kind == "choice"
                and choice is not None
                and choice.choice_id == self._highlight_id
            ):
                return index
        return None

    def _highlighted_choice(self) -> SaveLocationChoice | None:
        return next(
            (
                choice
                for choice in self._choices
                if choice.choice_id == self._highlight_id
            ),
            None,
        )

    def _summary_highlighted(self) -> bool:
        return self._highlight_id == _SUMMARY_OPTION_ID

    def _dismiss_once(self, result: SaveLocationPick | None) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.dismiss(result)

    def _rebuild(self) -> None:
        if not self.is_mounted:
            return
        try:
            option_list = self.query_one("#save-location-picker-list", OptionList)
        except Exception:
            return
        option_list.can_focus = False
        option_list.clear_options()
        for option in self._build_options():
            option_list.add_option(option)
        option_list.highlighted = self._highlight_option_index()
        self._refresh_footer()

    def _build_options(self) -> list[Option]:
        if self._load_error is not None:
            return [
                Option(
                    Text(self._load_error, style="bold red"),
                    id=_ERROR_OPTION_ID,
                    disabled=True,
                )
            ]
        if not self._loaded:
            return [
                Option(
                    Text("Finding destinations…", style="dim italic"),
                    id=_LOADING_OPTION_ID,
                    disabled=True,
                )
            ]
        if not self._choices:
            return [
                Option(
                    Text("No destinations found", style="dim"),
                    id=_EMPTY_OPTION_ID,
                    disabled=True,
                )
            ]
        if not any(
            choice.disabled_reason is None and choice.kind != "existing"
            for choice in self._choices
        ):
            options: list[Option] = [
                Option(
                    Text("No writable destinations found", style="dim"),
                    id=_EMPTY_OPTION_ID,
                    disabled=True,
                )
            ]
            for choice in self._choices:
                options.append(self._choice_option(choice))
            return options
        options = []
        seen_sections: set[str] = set()
        for choice in self._visible_choices():
            if choice.section not in seen_sections:
                seen_sections.add(choice.section)
                options.append(
                    Option(
                        Text(f"── {choice.section} ──", style="dim"),
                        id=f"__header__{choice.section}",
                        disabled=True,
                    )
                )
            options.append(self._choice_option(choice))
        summary_count = self._collapsed_summary_count()
        if summary_count is not None:
            options.append(
                Option(
                    Text(
                        f"── Plugins & built-in ({summary_count}) · + to show ──",
                        style="dim",
                    ),
                    id=_SUMMARY_OPTION_ID,
                    disabled=False,
                )
            )
        return options

    def _choice_option(self, choice: SaveLocationChoice) -> Option:
        return Option(
            _choice_text(choice),
            id=_choice_option_id(choice.choice_id),
            disabled=choice.disabled_reason is not None,
        )

    def _refresh_footer(self) -> None:
        if not self.is_mounted:
            return
        try:
            preview = self.query_one("#save-location-picker-preview", Static)
            hints = self.query_one("#save-location-picker-hints", Static)
        except Exception:
            return
        if self._error is not None:
            preview.update(Text(self._error, style="bold red"))
            preview.remove_class("-save-location-error")
            preview.add_class("-save-location-error")
        else:
            choice = self._highlighted_choice()
            if choice is not None and choice.disabled_reason is None:
                preview.update(choice.preview)
            elif self._loaded and not self._choices:
                preview.update("")
            elif self._loaded and not any(
                item.disabled_reason is None for item in self._choices
            ):
                preview.update("Enter does nothing here · esc cancel")
            else:
                preview.update("")
            preview.remove_class("-save-location-error")
        hints.update(self._hints_text())

    def _hints_text(self) -> str:
        if not self._loaded or self._load_error is not None:
            return "esc cancel"
        selectable = [c for c in self._choices if c.disabled_reason is None]
        if not selectable:
            return "esc cancel"
        existing = next(
            (c for c in selectable if c.kind == "existing" and c.hotkey),
            None,
        )
        letters = " ".join(
            c.hotkey for c in selectable if c.hotkey and c.kind != "existing"
        )
        parts: list[str] = []
        if existing is not None:
            parts.append(f"{existing.hotkey} existing")
        if letters:
            parts.append(f"{letters} pick")
        default = next((c for c in selectable if c.choice_id == self._default_id), None)
        if default is not None:
            reason = next(
                (
                    badge.removeprefix("★ ")
                    for badge in default.badges
                    if badge.startswith("★ ")
                ),
                "default",
            )
            parts.append(f"↵ {reason}")
        parts.append("j/k move")
        if any(c.collapsed_group for c in self._choices) and not self._expanded:
            parts.append("+ plugins")
        parts.append("esc cancel")
        return " · ".join(parts)


def _badge_style(badge: str) -> str:
    if badge.startswith("★ "):
        return "bold #FFD700"
    if badge.startswith("● "):
        return "#87D7FF"
    if badge.startswith("⚠ "):
        return "bold #D7AF5F"
    if badge.startswith("has "):
        return "#D7AF5F"
    if badge == "new":
        return "italic #FFD700"
    if badge == "chezmoi":
        return "dim italic"
    return "dim"


def _choice_icon(choice: SaveLocationChoice) -> str:
    if choice.kind == "existing":
        return "✎"
    if choice.kind == "directory":
        return "📁"
    return "📄"


def _choice_label_style(choice: SaveLocationChoice) -> str:
    if choice.kind == "existing":
        return "bold #D7AFFF"
    return "bold #87D7FF"


def _append_path(text: Text, choice: SaveLocationChoice) -> None:
    if choice.display_path:
        text.append("  ", style="")
        text.append(choice.display_path, style="dim")


def _choice_text(choice: SaveLocationChoice) -> Text:
    text = Text()
    icon = _choice_icon(choice)
    if choice.disabled_reason is not None:
        text.append("·  ", style="dim")
        text.append(f"{icon} ", style="dim")
        text.append(choice.label, style="dim")
        _append_path(text, choice)
        text.append("  ", style="")
        text.append(choice.disabled_reason, style="italic #D7AF5F")
        for badge in choice.badges:
            text.append("  ", style="")
            text.append(badge, style=_badge_style(badge))
        return text
    text.append(f"{choice.hotkey or ' '}  ", style="bold #00D7AF")
    text.append(f"{icon} ", style="")
    text.append(choice.label, style=_choice_label_style(choice))
    _append_path(text, choice)
    for badge in choice.badges:
        text.append("  ", style="")
        text.append(badge, style=_badge_style(badge))
    return text


__all__ = [
    "STEPPER_TEXT",
    "SaveLocationPickerKind",
    "SaveLocationPickerModal",
]
