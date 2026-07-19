"""Agent cleanup action chooser for the ace TUI."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from .agent_cleanup_types import (
    AgentCleanupAction,
    AgentCleanupPanelState,
    AgentCleanupResult,
)


@dataclass(frozen=True)
class _ActionRow:
    action: AgentCleanupAction
    key: str
    title: str
    detail: str
    enabled: bool


class AgentCleanupModal(ModalScreen[AgentCleanupResult | None]):
    """Keyboard-first panel for bulk agent cleanup actions."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("d", "dismiss_panel_done", "Dismiss Panel Done"),
        ("D", "dismiss_all_done", "Dismiss All Done"),
        ("k", "kill_panel", "Kill Panel"),
        ("K", "kill_all", "Kill All"),
        ("m", "marked", "Marked"),
        ("g", "group", "Group"),
        ("t", "tag", "Tag"),
        ("C", "clan", "Clan"),
        ("c", "custom", "Custom"),
        ("enter", "choose_highlighted", "Choose"),
    ]

    def __init__(self, state: AgentCleanupPanelState) -> None:
        super().__init__()
        self._state = state
        self._rows = self._build_rows(state)

    def compose(self) -> ComposeResult:
        with Container(id="agent-cleanup-container"):
            yield Label("Agent Cleanup", id="agent-cleanup-title")
            with Horizontal(id="agent-cleanup-summary"):
                yield Static(
                    self._summary_block(
                        "Panel",
                        self._state.focused_panel_label,
                        self._state.panel_running_count,
                        self._state.panel_completed_count,
                        self._state.panel_failed_count,
                    ),
                    classes="agent-cleanup-summary-card",
                )
                yield Static(
                    self._summary_block(
                        "All",
                        "loaded panels",
                        self._state.all_running_count,
                        self._state.all_completed_count,
                        self._state.all_failed_count,
                    ),
                    classes="agent-cleanup-summary-card",
                )
                yield Static(
                    self._context_block(),
                    classes="agent-cleanup-summary-card",
                )
            with Vertical(id="agent-cleanup-actions"):
                yield OptionList(
                    *[
                        Option(
                            self._row_label(row),
                            id=row.action,
                            disabled=not row.enabled,
                        )
                        for row in self._rows
                    ],
                    id="agent-cleanup-list",
                )
            yield Static(
                "d/D dismiss completed  k/K kill running + dismiss completed  "
                "m marked  g group  t tag  C clan  c custom  q close",
                id="agent-cleanup-hints",
            )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_dismiss_panel_done(self) -> None:
        self._choose("dismiss_panel_done")

    def action_dismiss_all_done(self) -> None:
        self._choose("dismiss_all_done")

    def action_kill_panel(self) -> None:
        self._choose("kill_panel")

    def action_kill_all(self) -> None:
        self._choose("kill_all")

    def action_marked(self) -> None:
        self._choose("marked")

    def action_group(self) -> None:
        self._choose("group")

    def action_tag(self) -> None:
        self._choose("tag")

    def action_clan(self) -> None:
        self._choose("clan")

    def action_custom(self) -> None:
        self._choose("custom")

    def action_choose_highlighted(self) -> None:
        option_list = self.query_one("#agent-cleanup-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return
        option = option_list.get_option_at_index(highlighted)
        if option.disabled or option.id is None:
            return
        self._choose(str(option.id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.disabled or event.option.id is None:
            return
        self._choose(str(event.option.id))

    def _choose(self, action: str) -> None:
        row = self._row_by_action(action)
        if row is None or not row.enabled:
            self._set_hint("Unavailable")
            return
        self.dismiss(AgentCleanupResult(action=row.action))

    def _set_hint(self, text: str) -> None:
        try:
            self.query_one("#agent-cleanup-hints", Static).update(text)
        except Exception:
            pass

    def _row_by_action(self, action: str) -> _ActionRow | None:
        for row in self._rows:
            if row.action == action:
                return row
        return None

    @staticmethod
    def _summary_block(
        title: str, subtitle: str, running: int, completed: int, failed: int
    ) -> Text:
        text = Text()
        text.append(title, style="bold")
        text.append(f"\n{subtitle}", style="dim")
        text.append(f"\n{running} running", style="yellow")
        text.append(f"  {completed} done", style="green")
        if failed:
            text.append(f"  {failed} failed", style="red")
        return text

    def _context_block(self) -> Text:
        text = Text()
        text.append("Context", style="bold")
        text.append(f"\n{self._state.marked_count} marked", style="cyan")
        text.append(f"  {self._state.group_count} in group", style="magenta")
        text.append(f"\n{self._state.tag_count} tag panels", style="dim")
        text.append(f" · {self._state.clan_count} clans", style="dim cyan")
        return text

    @staticmethod
    def _row_label(row: _ActionRow) -> Text:
        text = Text()
        key_style = "bold cyan" if row.enabled else "dim"
        title_style = "bold" if row.enabled else "dim"
        detail_style = "dim" if row.enabled else "dim italic"
        text.append(f"{row.key}  ", style=key_style)
        text.append(row.title, style=title_style)
        text.append(f"\n   {row.detail}", style=detail_style)
        return text

    @staticmethod
    def _build_rows(state: AgentCleanupPanelState) -> list[_ActionRow]:
        panel_cleanup_count = state.panel_running_count + state.panel_completed_count
        all_cleanup_count = state.all_running_count + state.all_completed_count
        return [
            _ActionRow(
                "dismiss_panel_done",
                "d",
                "Dismiss completed in panel",
                f"{state.panel_completed_count} completed in {state.focused_panel_label}",
                state.panel_completed_count > 0,
            ),
            _ActionRow(
                "dismiss_all_done",
                "D",
                "Dismiss completed everywhere",
                f"{state.all_completed_count} completed across loaded panels",
                state.all_completed_count > 0,
            ),
            _ActionRow(
                "kill_panel",
                "k",
                "Kill and dismiss panel",
                f"{panel_cleanup_count} affected in {state.focused_panel_label}",
                panel_cleanup_count > 0,
            ),
            _ActionRow(
                "kill_all",
                "K",
                "Kill and dismiss everywhere",
                f"{all_cleanup_count} affected across loaded panels",
                all_cleanup_count > 0,
            ),
            _ActionRow(
                "marked",
                "m",
                "Kill and dismiss marked",
                f"{state.marked_count} marked",
                state.marked_count > 0,
            ),
            _ActionRow(
                "group",
                "g",
                "Kill and dismiss focused group",
                f"{state.group_count} agents in focused group",
                state.group_count > 0,
            ),
            _ActionRow(
                "tag",
                "t",
                "Choose tag",
                f"{state.tag_count} known tag panels",
                state.tag_count > 0,
            ),
            _ActionRow(
                "clan",
                "C",
                "Choose clan",
                AgentCleanupModal._clan_detail(state),
                state.clan_count > 0,
            ),
            _ActionRow(
                "custom",
                "c",
                "Custom selection",
                f"{panel_cleanup_count} candidates in {state.focused_panel_label}",
                panel_cleanup_count > 0,
            ),
        ]

    @staticmethod
    def _clan_detail(state: AgentCleanupPanelState) -> str:
        count = state.clan_count
        plural = "clan" if count == 1 else "clans"
        detail = f"{count} {plural} in {state.focused_panel_label}"
        if state.focused_clan_label:
            detail += f" · focused: {state.focused_clan_label}"
        return detail


__all__ = ["AgentCleanupModal"]
