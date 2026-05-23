"""Modal for choosing a visible sibling agent."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from .base import OptionListNavigationMixin

_SELECTOR_KEYS = "abcdefghijklmnopqrstuvwxyz"
_RESERVED_KEYS = {"j", "k", "q"}
_MAX_AGENT_NAME_LEN = 34
_MAX_DISPLAY_NAME_LEN = 24
_MAX_PANEL_LABEL_LEN = 18
_MAX_TIME_HINT_LEN = 18


@dataclass(frozen=True)
class AgentSiblingChoice:
    """One visible sibling row offered by :class:`AgentSiblingModal`."""

    global_idx: int
    agent_name: str
    display_name: str
    status: str
    panel_label: str
    time_hint: str = ""


def _agent_sibling_selector_keys(count: int) -> list[str]:
    """Return quick-select keys that do not conflict with modal navigation."""
    return [key for key in _SELECTOR_KEYS if key not in _RESERVED_KEYS][:count]


def _short_text(value: object, *, max_len: int) -> str:
    text = str(value or "")
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."


def _status_style(status: str) -> str:
    if status == "RUNNING":
        return "bold #FFD700"
    if status in {"DONE", "PLAN DONE", "TALE DONE", "PLAN COMMITTED"}:
        return "bold #5FD75F"
    if status == "FAILED":
        return "bold #FF5F5F"
    if status == "WAITING":
        return "bold #AF87FF"
    if status in {"PLAN", "QUESTION"}:
        return "bold #FFAF00"
    return "bold #87D7FF"


def _agent_sibling_option_text(
    selector: str | None,
    choice: AgentSiblingChoice,
) -> Text:
    """Render one sibling choice as compact OptionList text."""
    text = Text()
    if selector is None:
        text.append("   ", style="dim")
    else:
        text.append(f"{selector}  ", style="bold #D7AF5F")
    text.append(
        _short_text(choice.agent_name, max_len=_MAX_AGENT_NAME_LEN),
        style="bold #00D7AF",
    )
    if choice.display_name and choice.display_name != choice.agent_name:
        text.append("  ")
        text.append(
            _short_text(choice.display_name, max_len=_MAX_DISPLAY_NAME_LEN),
            style="dim #87D7FF",
        )
    text.append("  ")
    text.append(choice.status, style=_status_style(choice.status))
    text.append("  ")
    text.append(
        _short_text(choice.panel_label, max_len=_MAX_PANEL_LABEL_LEN),
        style="dim #FFD75F",
    )
    if choice.time_hint:
        text.append("  ")
        text.append(
            _short_text(choice.time_hint, max_len=_MAX_TIME_HINT_LEN),
            style="dim",
        )
    return text


class AgentSiblingModal(
    OptionListNavigationMixin,
    ModalScreen[int | None],
):
    """Keyboard-first chooser for visible sibling Agents-tab rows."""

    _option_list_id = "agent-sibling-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_highlighted", "Jump"),
    ]

    def __init__(
        self,
        family_label: str,
        choices: list[AgentSiblingChoice],
    ) -> None:
        super().__init__()
        self._family_label = family_label
        self._choices = choices
        selectors = _agent_sibling_selector_keys(len(choices))
        self._selector_by_index = selectors
        self._index_by_selector = {key: index for index, key in enumerate(selectors)}

    def compose(self) -> ComposeResult:
        with Container(id="agent-sibling-container"):
            yield Label(self._title_text(), id="agent-sibling-title")
            yield OptionList(*self._create_options(), id=self._option_list_id)
            yield Static(self._hint_text(), id="agent-sibling-hints")

    def _title_text(self) -> str:
        count = len(self._choices)
        plural = "" if count == 1 else "s"
        return f"Sibling Agents: {self._family_label}  [{count} sibling{plural}]"

    def _hint_text(self) -> str:
        return "enter: jump    a-z: quick select    j/k: move    q/esc: close"

    def _create_options(self) -> list[Option]:
        options: list[Option] = []
        for index, choice in enumerate(self._choices):
            selector = (
                self._selector_by_index[index]
                if index < len(self._selector_by_index)
                else None
            )
            options.append(
                Option(
                    _agent_sibling_option_text(selector, choice),
                    id=str(choice.global_idx),
                )
            )
        return options

    def on_mount(self) -> None:
        self.query_one(f"#{self._option_list_id}", OptionList).focus()

    def on_key(self, event: events.Key) -> None:
        if event.key not in self._index_by_selector:
            return
        self.dismiss(self._choices[self._index_by_selector[event.key]].global_idx)
        event.prevent_default()
        event.stop()

    def action_select_highlighted(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        index = option_list.highlighted
        if index is None or not 0 <= index < len(self._choices):
            return
        self.dismiss(self._choices[index].global_idx)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option and event.option.id is not None:
            self.dismiss(int(str(event.option.id)))
