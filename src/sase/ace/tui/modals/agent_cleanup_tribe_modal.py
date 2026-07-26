"""Tribe-scoped agent cleanup chooser for the ace TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.core.agent_cleanup_facade import agents_to_cleanup_targets, plan_agent_cleanup
from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    CLEANUP_MODE_KILL_AND_DISMISS,
    CLEANUP_SCOPE_CUSTOM_SELECTION,
    CLEANUP_SCOPE_TRIBE,
    AgentCleanupIdentityWire,
    AgentCleanupPlanWire,
    AgentCleanupRequestWire,
)
from sase.ace.tui.models.tribe_display import (
    compose_tribe_identity_style,
    named_tribe_identity_colors,
)

from .agent_cleanup_types import AgentCleanupTribeResult
from .base import OptionListNavigationMixin

if TYPE_CHECKING:
    from ..models import Agent


@dataclass(frozen=True)
class _TribeRow:
    tribe: str
    plan: AgentCleanupPlanWire


class AgentCleanupTribeModal(
    OptionListNavigationMixin, ModalScreen[AgentCleanupTribeResult | None]
):
    """Choose one or more tribes and preview cleanup plans."""

    _option_list_id = "agent-cleanup-tribe-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("space", "toggle_mark", "Mark"),
        ("m", "toggle_mark", "Mark"),
        ("enter", "choose_highlighted", "Choose"),
    ]

    def __init__(self, *, tribes: tuple[str, ...], targets: list[Agent]) -> None:
        super().__init__()
        self._targets = list(targets)
        self._rows = [
            self._build_row(tribe) for tribe in sorted(set(tribes), key=str.lower)
        ]
        self._tribe_colors = named_tribe_identity_colors(
            {row.tribe for row in self._rows}
        )
        self._marked_tribes: set[str] = set()

    def compose(self) -> ComposeResult:
        with Container(id="agent-cleanup-tribe-container"):
            yield Label("Cleanup by Tribe", id="agent-cleanup-title")
            yield OptionList(
                *[
                    Option(
                        self._tribe_row_label(row),
                        id=f"tribe:{row.tribe}",
                        disabled=not self._row_enabled(row),
                    )
                    for row in self._rows
                ],
                id="agent-cleanup-tribe-list",
            )
            yield Static(
                self._hint_text(),
                id="agent-cleanup-hints",
            )

    def action_choose_highlighted(self) -> None:
        if self._marked_tribes:
            self.dismiss(
                AgentCleanupTribeResult(tribes=self._marked_tribes_in_row_order())
            )
            return

        option_list = self.query_one("#agent-cleanup-tribe-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None or highlighted < 0:
            return
        option = option_list.get_option_at_index(highlighted)
        if option.disabled or option.id is None:
            return
        tribe = str(option.id).removeprefix("tribe:")
        self.dismiss(AgentCleanupTribeResult(tribes=(tribe,)))

    def action_toggle_mark(self) -> None:
        option_list = self.query_one("#agent-cleanup-tribe-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None or highlighted < 0 or highlighted >= len(self._rows):
            return
        row = self._rows[highlighted]
        if not self._row_enabled(row):
            self._set_hint("Tribe has no cleanup targets")
            return
        if row.tribe in self._marked_tribes:
            self._marked_tribes.remove(row.tribe)
        else:
            self._marked_tribes.add(row.tribe)
        self._refresh_row(highlighted)
        if self._rows:
            option_list.highlighted = (highlighted + 1) % len(self._rows)
        self._update_hint()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.disabled or event.option.id is None:
            return
        if self._marked_tribes:
            self.dismiss(
                AgentCleanupTribeResult(tribes=self._marked_tribes_in_row_order())
            )
            return
        tribe = str(event.option.id).removeprefix("tribe:")
        self.dismiss(AgentCleanupTribeResult(tribes=(tribe,)))

    def _build_row(self, tribe: str) -> _TribeRow:
        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_TRIBE,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            tribe=tribe,
            include_pidless_as_dismissable=True,
        )
        plan = plan_agent_cleanup(agents_to_cleanup_targets(self._targets), request)
        return _TribeRow(tribe=tribe, plan=plan)

    @staticmethod
    def _row_enabled(row: _TribeRow) -> bool:
        return bool(row.plan.kill_items or row.plan.dismiss_items)

    def _tribe_row_label(self, row: _TribeRow) -> Text:
        text = Text()
        enabled = self._row_enabled(row)
        marked = row.tribe in self._marked_tribes
        marker_style = "bold green" if marked else "dim"
        tribe_style = compose_tribe_identity_style(
            self._tribe_colors[row.tribe],
            bold=enabled,
            dim=not enabled,
        )
        detail_style = "dim" if enabled else "dim italic"
        text.append("[x] " if marked else "[ ] ", style=marker_style)
        text.append(f"@{row.tribe}", style=tribe_style)
        counts = row.plan.counts
        text.append(
            f"\n   {counts.kill} kill  {counts.dismiss} dismiss  "
            f"{counts.cascaded_workflow_children} child cascade",
            style=detail_style,
        )
        return text

    def _marked_tribes_in_row_order(self) -> tuple[str, ...]:
        return tuple(
            row.tribe for row in self._rows if row.tribe in self._marked_tribes
        )

    def _marked_plan(self) -> AgentCleanupPlanWire | None:
        identities = self._marked_identities()
        if not identities:
            return None
        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_CUSTOM_SELECTION,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            identities=identities,
            include_pidless_as_dismissable=True,
        )
        return plan_agent_cleanup(agents_to_cleanup_targets(self._targets), request)

    def _marked_identities(self) -> tuple[AgentCleanupIdentityWire, ...]:
        seen: set[AgentCleanupIdentityWire] = set()
        identities: list[AgentCleanupIdentityWire] = []
        for row in self._rows:
            if row.tribe not in self._marked_tribes:
                continue
            for identity in row.plan.selected_identities:
                if identity in seen:
                    continue
                seen.add(identity)
                identities.append(identity)
        return tuple(identities)

    def _hint_text(self) -> str:
        base = "j/k move  space/m mark  enter preview  q close"
        mark_count = len(self._marked_tribes)
        if not mark_count:
            return base
        plan = self._marked_plan()
        if plan is None:
            return f"{base}  marked: {mark_count}"
        counts = plan.counts
        return (
            f"{base}  marked: {mark_count}  {counts.kill} kill  "
            f"{counts.dismiss} dismiss  {counts.cascaded_workflow_children} child cascade"
        )

    def _refresh_row(self, index: int) -> None:
        option_list = self.query_one("#agent-cleanup-tribe-list", OptionList)
        option_list.replace_option_prompt_at_index(
            index,
            self._tribe_row_label(self._rows[index]),
        )
        option_list.highlighted = index

    def _set_hint(self, text: str) -> None:
        try:
            self.query_one("#agent-cleanup-hints", Static).update(text)
        except Exception:
            pass

    def _update_hint(self) -> None:
        self._set_hint(self._hint_text())


__all__ = ["AgentCleanupTribeModal"]
