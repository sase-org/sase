"""Keyboard-first Update panel modal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.update_panel_state import (
    UpdateOptionChip,
    UpdateOptionRow,
    UpdateOptionScope,
    UpdatePanelState,
)
from sase.ace.tui.widgets.update_accents import CORE_UPDATE_ACCENT, UPDATE_GLYPH

from .base import OptionListNavigationMixin

_HINTS = "e s p a select · j/k move · ⏎ run · r re-check · q close"
_RECHECKING_LABEL = "re-checking…"
_ROW_WIDTH = 68


@dataclass(frozen=True, slots=True)
class UpdatePanelResult:
    """Chosen Update panel row.

    ``scope`` is the panel-state row id (``everything``, ``sase``,
    ``providers``, or ``agents``).
    """

    scope: UpdateOptionScope


class UpdatePanel(OptionListNavigationMixin, ModalScreen[UpdatePanelResult | None]):
    """Pure presentation of an ``UpdatePanelState``; no I/O of its own."""

    class RecheckRequested(Message):
        """Ask the app to refresh cached update evidence."""

    _option_list_id = "update-panel-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("e", "choose_everything", "Everything"),
        ("s", "choose_sase", "SASE"),
        ("p", "choose_providers", "Providers"),
        ("a", "choose_agents", "Agents"),
        ("enter", "choose_highlighted", "Run"),
        ("r", "recheck", "Re-check"),
    ]

    def __init__(self, state: UpdatePanelState) -> None:
        super().__init__()
        self._state = state
        self._chose = False

    def compose(self) -> ComposeResult:
        with Container(id="update-panel-container"):
            yield OptionList(*self._options(), id="update-panel-list")
            yield Static(_HINTS, id="update-panel-hints")

    def on_mount(self) -> None:
        self._paint_chrome()

    def set_state(self, state: UpdatePanelState) -> None:
        """Replace the projected state, keeping the highlighted row index."""
        self._state = state
        if not self.is_mounted:
            return
        option_list = self.query_one("#update-panel-list", OptionList)
        highlighted = option_list.highlighted
        option_list.clear_options()
        option_list.add_options(self._options())
        count = option_list.option_count
        if highlighted is not None and count:
            option_list.highlighted = min(highlighted, count - 1)
        self._paint_chrome()

    def action_choose_everything(self) -> None:
        self._choose_scope("everything")

    def action_choose_sase(self) -> None:
        self._choose_scope("sase")

    def action_choose_providers(self) -> None:
        self._choose_scope("providers")

    def action_choose_agents(self) -> None:
        self._choose_scope("agents")

    def action_choose_highlighted(self) -> None:
        option_list = self.query_one("#update-panel-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return
        option = option_list.get_option_at_index(highlighted)
        if option.id is None:
            return
        self._choose_id(str(option.id))

    def action_recheck(self) -> None:
        self.post_message(self.RecheckRequested())

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if self._chose or event.option.id is None:
            return
        self._choose_id(str(event.option.id))

    def _choose_id(self, option_id: str) -> None:
        for row in self._state.rows:
            if row.scope == option_id:
                self._choose_scope(row.scope)
                return

    def _choose_scope(self, scope: UpdateOptionScope) -> None:
        if self._chose:
            return
        if not any(row.scope == scope for row in self._state.rows):
            return
        self._chose = True
        self.dismiss(UpdatePanelResult(scope=scope))

    def _paint_chrome(self, container: Container | None = None) -> None:
        if container is None:
            container = self.query_one("#update-panel-container", Container)
        title = Text()
        title.append(UPDATE_GLYPH, style="bold")
        title.append(" Update")
        container.border_title = title
        label = (
            _RECHECKING_LABEL if self._state.rechecking else self._state.freshness_label
        )
        if self._state.stale:
            container.border_subtitle = Text(label, style=CORE_UPDATE_ACCENT)
        else:
            container.border_subtitle = label
        container.set_class(self._state.stale, "-stale")

    def _options(self) -> list[Option]:
        return [Option(self._row_prompt(row), id=row.scope) for row in self._state.rows]

    def _row_prompt(self, row: UpdateOptionRow) -> Text:
        accent = self._rich_accent(row.accent)
        prompt = Text()
        prompt.append(f"{row.key}  ", style=f"bold {accent}".strip())
        prompt.append(row.title, style="bold")
        chip = Text(row.chip.text, style=_chip_style(row.chip, accent))
        gap = max(1, _ROW_WIDTH - prompt.cell_len - chip.cell_len)
        prompt.append(" " * gap)
        prompt.append_text(chip)
        prompt.append("\n")
        prompt.append(row.description, style="dim")
        if row.detail:
            prompt.append("\n")
            detail_style = f"dim {accent}".strip() if accent else "dim"
            prompt.append(row.detail, style=detail_style)
        return prompt

    def _rich_accent(self, accent: str) -> str:
        if not accent.startswith("$"):
            return accent
        # $primary is also OptionList's highlight color, so applying it
        # to the default Everything row makes the key badge and chip
        # vanish. Leave theme-primary accents uncolored.
        if accent == "$primary":
            return ""
        name = accent[1:]
        variables = getattr(self.app, "theme_variables", None)
        if isinstance(variables, Mapping):
            value = variables.get(name)
            if value:
                return str(value)
        return ""


def _chip_style(chip: UpdateOptionChip, accent: str) -> str:
    if chip.kind == "available":
        return f"bold {accent}".strip()
    if chip.kind == "current":
        return "dim green"
    if chip.kind == "failed":
        return "red"
    return "dim"


__all__ = ["UpdatePanel", "UpdatePanelResult"]
