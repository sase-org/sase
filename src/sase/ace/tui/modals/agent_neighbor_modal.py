"""Modal for choosing a visible neighbor agent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.agent.status_buckets import PENDING_EPIC_STATUS, agent_is_asking
from sase.ace.tui.widgets._agent_list_styling import _OWNER_BADGE_STYLE
from sase.ace.tui.models.tribe_display import (
    TRIBE_IDENTITY_FALLBACK_COLOR,
    compose_tribe_identity_style,
    named_tribe_identity_colors,
)

from .base import OptionListNavigationMixin

_SELECTOR_KEYS = "abcdefghijklmnopqrstuvwxyz"
_RESERVED_KEYS = {"j", "k", "q"}
_MAX_AGENT_NAME_LEN = 34
_MAX_DISPLAY_NAME_LEN = 24
_MAX_PANEL_LABEL_LEN = 18
_MAX_TIME_HINT_LEN = 18
_MAX_TITLE_AGENT_LEN = 48


@dataclass(frozen=True)
class AgentNeighborChoice:
    """One selectable related-agent row offered by :class:`AgentNeighborModal`."""

    agent_name: str
    display_name: str
    status: str
    panel_label: str
    time_hint: str = ""
    group: str = "neighbor"
    hood: str = ""
    dismissed: bool = False
    global_idx: int | None = None
    owner_badge: str = ""


def _agent_neighbor_selector_keys(count: int) -> list[str]:
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
    if status == "QUEUED":
        return "bold #5F87FF"
    if status == "WAITING":
        return "bold #AF87FF"
    if status == PENDING_EPIC_STATUS:
        return "bold #D787FF"
    if agent_is_asking(status):
        return "bold #FFAF00"
    return "bold #87D7FF"


def _agent_neighbor_option_text(
    selector: str | None,
    choice: AgentNeighborChoice,
    *,
    tribe_colors: Mapping[str, str] | None = None,
) -> Text:
    """Render one neighbor choice as compact OptionList text."""
    text = Text()
    if selector is None:
        text.append("   ", style="dim")
    else:
        text.append(f"{selector}  ", style="bold #D7AF5F")
    dim_prefix = "dim " if choice.dismissed else ""
    text.append(
        _short_text(choice.agent_name, max_len=_MAX_AGENT_NAME_LEN),
        style=f"{dim_prefix}bold #00D7AF",
    )
    if choice.owner_badge:
        text.append(" [")
        text.append(
            choice.owner_badge,
            style=f"{dim_prefix}{_OWNER_BADGE_STYLE.removeprefix('bold ')}"
            if dim_prefix
            else _OWNER_BADGE_STYLE,
        )
        text.append("]")
    text.append("  ")
    text.append(choice.status, style=f"{dim_prefix}{_status_style(choice.status)}")
    text.append("  ")
    tribe_name = choice.panel_label.removeprefix("@")
    text.append(
        _short_text(choice.panel_label, max_len=_MAX_PANEL_LABEL_LEN),
        style=compose_tribe_identity_style(
            (
                tribe_colors.get(tribe_name, TRIBE_IDENTITY_FALLBACK_COLOR)
                if tribe_colors is not None
                else TRIBE_IDENTITY_FALLBACK_COLOR
            ),
            dim=choice.dismissed,
        ),
    )
    if choice.time_hint:
        text.append("  ")
        text.append(
            _short_text(choice.time_hint, max_len=_MAX_TIME_HINT_LEN),
            style="dim",
        )
    if choice.display_name and choice.display_name != choice.agent_name:
        text.append("  ")
        text.append(
            _short_text(choice.display_name, max_len=_MAX_DISPLAY_NAME_LEN),
            style="dim #87D7FF",
        )
    if choice.dismissed:
        text.append("  ")
        text.append("dismissed", style="bold #FFAF00")
    return text


def _agent_neighbor_header_text(label: str) -> Text:
    """Render a non-selectable section header."""
    text = Text()
    text.append(f"-- {label} ", style="dim bold")
    text.append("-" * 20, style="dim")
    return text


def _choice_index_from_option_id(option_id: str | None) -> int | None:
    if option_id is None or not option_id.startswith("choice-"):
        return None
    try:
        return int(option_id.removeprefix("choice-"))
    except ValueError:
        return None


class AgentNeighborModal(
    OptionListNavigationMixin,
    ModalScreen[int | None],
):
    """Keyboard-first chooser for related Agents-tab rows."""

    _option_list_id = "agent-neighbor-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_highlighted", "Jump"),
    ]

    def __init__(
        self,
        agent_label: str,
        choices: list[AgentNeighborChoice],
    ) -> None:
        super().__init__()
        self._agent_label = agent_label
        self._choices = choices
        self._tribe_colors = named_tribe_identity_colors(
            {choice.panel_label.removeprefix("@") for choice in choices}
        )
        selectors = _agent_neighbor_selector_keys(len(choices))
        self._selector_by_index = selectors
        self._index_by_selector = {key: index for index, key in enumerate(selectors)}

    def compose(self) -> ComposeResult:
        with Container(id="agent-neighbor-container"):
            yield Label(self._title_text(), id="agent-neighbor-title")
            yield OptionList(*self._create_options(), id=self._option_list_id)
            yield Static(self._hint_text(), id="agent-neighbor-hints")

    def _title_text(self) -> str:
        ancestor_count = sum(
            1 for choice in self._choices if choice.group == "ancestor"
        )
        descendant_count = sum(
            1 for choice in self._choices if choice.group == "descendant"
        )
        neighbor_count = sum(
            1 for choice in self._choices if choice.group == "neighbor"
        )
        summary_parts: list[str] = []
        if ancestor_count:
            plural = "" if ancestor_count == 1 else "s"
            summary_parts.append(f"{ancestor_count} ancestor{plural}")
        if descendant_count:
            plural = "" if descendant_count == 1 else "s"
            summary_parts.append(f"{descendant_count} descendant{plural}")
        if neighbor_count:
            plural = "" if neighbor_count == 1 else "s"
            summary_parts.append(f"{neighbor_count} neighbor{plural}")
        agent_label = _short_text(self._agent_label, max_len=_MAX_TITLE_AGENT_LEN)
        summary = f"  [{' - '.join(summary_parts)}]" if summary_parts else ""
        return f"Neighbors of {agent_label}{summary}"

    def _hint_text(self) -> str:
        return "enter jump/revive  a-z select  j/k move  q/esc close"

    def _create_options(self) -> list[Option]:
        options: list[Option] = []
        ancestor_choices = [
            (index, choice)
            for index, choice in enumerate(self._choices)
            if choice.group == "ancestor"
        ]
        descendant_choices = [
            (index, choice)
            for index, choice in enumerate(self._choices)
            if choice.group == "descendant"
        ]
        neighbor_choices = [
            (index, choice)
            for index, choice in enumerate(self._choices)
            if choice.group == "neighbor"
        ]

        if ancestor_choices:
            options.append(
                Option(
                    _agent_neighbor_header_text(f"Ancestors ({len(ancestor_choices)})"),
                    id="header-ancestors",
                    disabled=True,
                )
            )
            self._append_choice_options(options, ancestor_choices)
        if descendant_choices:
            options.append(
                Option(
                    _agent_neighbor_header_text(
                        f"Descendants ({len(descendant_choices)})"
                    ),
                    id="header-descendants",
                    disabled=True,
                )
            )
            self._append_choice_options(options, descendant_choices)
        if neighbor_choices:
            sections: list[list[tuple[int, AgentNeighborChoice]]] = []
            for indexed_choice in neighbor_choices:
                if not sections or sections[-1][-1][1].hood != indexed_choice[1].hood:
                    sections.append([])
                sections[-1].append(indexed_choice)
            for section_idx, section in enumerate(sections):
                hood = section[0][1].hood
                header = (
                    f"Neighbors - {hood} hood ({len(section)})"
                    if hood
                    else f"Neighbors ({len(section)})"
                )
                options.append(
                    Option(
                        _agent_neighbor_header_text(header),
                        id=f"header-neighbors-{section_idx}",
                        disabled=True,
                    )
                )
                self._append_choice_options(options, section)
        return options

    def _append_choice_options(
        self,
        options: list[Option],
        indexed_choices: list[tuple[int, AgentNeighborChoice]],
    ) -> None:
        for index, choice in indexed_choices:
            selector = (
                self._selector_by_index[index]
                if index < len(self._selector_by_index)
                else None
            )
            options.append(
                Option(
                    _agent_neighbor_option_text(
                        selector,
                        choice,
                        tribe_colors=self._tribe_colors,
                    ),
                    id=f"choice-{index}",
                )
            )

    def on_mount(self) -> None:
        self.query_one(f"#{self._option_list_id}", OptionList).focus()

    def on_key(self, event: events.Key) -> None:
        if event.key not in self._index_by_selector:
            return
        self.dismiss(self._index_by_selector[event.key])
        event.prevent_default()
        event.stop()

    def action_select_highlighted(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        index = option_list.highlighted
        if index is None:
            return
        choice_idx = _choice_index_from_option_id(
            str(option_list.get_option_at_index(index).id)
        )
        if choice_idx is None or not 0 <= choice_idx < len(self._choices):
            return
        self.dismiss(choice_idx)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = str(event.option.id) if event.option else None
        choice_idx = _choice_index_from_option_id(option_id)
        if choice_idx is not None:
            self.dismiss(choice_idx)
