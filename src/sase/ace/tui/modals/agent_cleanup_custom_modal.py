"""Custom agent cleanup selector for the ace TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.core.agent_cleanup_facade import (
    agent_to_cleanup_target,
    agents_to_cleanup_targets,
    plan_agent_cleanup,
)
from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    CLEANUP_MODE_KILL_AND_DISMISS,
    CLEANUP_SCOPE_CUSTOM_SELECTION,
    DISMISSABLE_STATUSES,
    AgentCleanupPlanWire,
    AgentCleanupRequestWire,
)

from .agent_cleanup_types import (
    AgentCleanupAgentIdentity,
    AgentCleanupCustomResult,
    StatusFilter,
)

if TYPE_CHECKING:
    from ..models import Agent


class AgentCleanupCustomModal(ModalScreen[AgentCleanupCustomResult | None]):
    """Custom selector for low-keystroke cleanup selection."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("d", "filter_done", "Done"),
        ("r", "filter_running", "Running"),
        ("f", "filter_failed", "Failed"),
        ("w", "filter_waiting", "Waiting"),
        ("t", "cycle_tribe_filter", "Tribe"),
        ("/", "focus_text_filter", "Text"),
        ("space", "toggle_row", "Toggle"),
        ("a", "toggle_all_filtered", "All"),
        ("enter", "confirm", "Confirm"),
    ]

    def __init__(
        self,
        *,
        candidates: list[Agent],
        targets: list[Agent],
        focused_panel_label: str,
    ) -> None:
        super().__init__()
        self._candidates = list(candidates)
        self._targets = list(targets)
        self._focused_panel_label = focused_panel_label
        self._parent_tribes = {
            agent.raw_suffix: agent.tribe
            for agent in self._targets
            if agent.raw_suffix and not agent.is_workflow_child
        }
        self._selected: set[AgentCleanupAgentIdentity] = set()
        self._status_filter: StatusFilter | None = None
        self._tribe_filter: str | None = None
        self._text_filter = ""
        self._known_tribes = self._candidate_tribes()
        self._filtered_agents: list[Agent] = []
        self._plan = self._recompute_plan()

    def compose(self) -> ComposeResult:
        with Container(id="agent-cleanup-custom-container"):
            yield Label(
                f"Custom Cleanup - {self._focused_panel_label}",
                id="agent-cleanup-title",
            )
            yield Static(self._summary_text(), id="agent-cleanup-custom-summary")
            yield OptionList(id="agent-cleanup-custom-list")
            yield Input(placeholder="text filter", id="agent-cleanup-search")
            yield Static(self._hint_text(), id="agent-cleanup-hints")

    def on_mount(self) -> None:
        self._refresh_rows()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_filter_done(self) -> None:
        self._set_status_filter("done")

    def action_filter_running(self) -> None:
        self._set_status_filter("running")

    def action_filter_failed(self) -> None:
        self._set_status_filter("failed")

    def action_filter_waiting(self) -> None:
        self._set_status_filter("waiting")

    def action_cycle_tribe_filter(self) -> None:
        if not self._known_tribes:
            self._tribe_filter = None
        elif self._tribe_filter is None:
            self._tribe_filter = self._known_tribes[0]
        else:
            idx = self._known_tribes.index(self._tribe_filter)
            self._tribe_filter = (
                None
                if idx == len(self._known_tribes) - 1
                else self._known_tribes[idx + 1]
            )
        self._refresh_plan_and_rows()

    def action_focus_text_filter(self) -> None:
        try:
            self.query_one("#agent-cleanup-search", Input).focus()
        except Exception:
            pass

    def action_toggle_row(self) -> None:
        agent = self._highlighted_agent()
        if agent is None:
            return
        identity = agent.identity
        if identity in self._selected:
            self._selected.discard(identity)
        else:
            self._selected.add(identity)
        self._refresh_plan_and_rows()

    def action_toggle_all_filtered(self) -> None:
        filtered = {agent.identity for agent in self._filtered_agents}
        if not filtered:
            return
        if filtered <= self._selected:
            self._selected -= filtered
        else:
            self._selected |= filtered
        self._refresh_plan_and_rows()

    def action_confirm(self) -> None:
        self._plan = self._recompute_plan()
        if not self._plan.kill_items and not self._plan.dismiss_items:
            self._set_hint("No selected agents can be cleaned up")
            return
        self.dismiss(AgentCleanupCustomResult(identities=tuple(self._selected)))

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        self.action_toggle_row()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "agent-cleanup-search":
            return
        self._text_filter = event.value.strip().lower()
        self._refresh_plan_and_rows()

    def _set_status_filter(self, value: StatusFilter) -> None:
        self._status_filter = None if self._status_filter == value else value
        self._refresh_plan_and_rows()

    def _refresh_plan_and_rows(self) -> None:
        self._plan = self._recompute_plan()
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        try:
            summary = self.query_one("#agent-cleanup-custom-summary", Static)
            summary.update(self._summary_text())
            option_list = self.query_one("#agent-cleanup-custom-list", OptionList)
            option_list.clear_options()
            for idx, agent in enumerate(self._filtered_agents):
                option_list.add_option(
                    Option(self._agent_row_label(agent), id=str(idx))
                )
            self.query_one("#agent-cleanup-hints", Static).update(self._hint_text())
        except Exception:
            pass

    def _set_hint(self, text: str) -> None:
        try:
            self.query_one("#agent-cleanup-hints", Static).update(text)
        except Exception:
            pass

    def _highlighted_agent(self) -> Agent | None:
        try:
            option_list = self.query_one("#agent-cleanup-custom-list", OptionList)
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None or highlighted >= len(self._filtered_agents):
            return None
        return self._filtered_agents[highlighted]

    def _recompute_plan(self) -> AgentCleanupPlanWire:
        self._filtered_agents = [a for a in self._candidates if self._matches(a)]
        selected_agents = [a for a in self._targets if a.identity in self._selected]
        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_CUSTOM_SELECTION,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            identities=tuple(
                agent_to_cleanup_target(a).identity for a in selected_agents
            ),
            include_pidless_as_dismissable=True,
        )
        return plan_agent_cleanup(agents_to_cleanup_targets(self._targets), request)

    def _matches(self, agent: Agent) -> bool:
        if self._status_filter == "done" and agent.status not in DISMISSABLE_STATUSES:
            return False
        if self._status_filter == "running" and (
            agent.pid is None or agent.status in DISMISSABLE_STATUSES
        ):
            return False
        if self._status_filter == "failed" and agent.status != "FAILED":
            return False
        if self._status_filter == "waiting" and agent.status != "WAITING":
            return False
        if (
            self._tribe_filter is not None
            and self._effective_tribe(agent) != self._tribe_filter
        ):
            return False
        if self._text_filter and self._text_filter not in self._search_text(agent):
            return False
        return True

    def _search_text(self, agent: Agent) -> str:
        parts = [
            agent.display_name,
            agent.agent_name or "",
            agent.cl_name,
            agent.status,
            agent.workflow or "",
            self._effective_tribe(agent) or "",
        ]
        return " ".join(parts).lower()

    def _candidate_tribes(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    effective_tribe
                    for agent in self._candidates
                    if (effective_tribe := self._effective_tribe(agent))
                },
                key=str.lower,
            )
        )

    def _effective_tribe(self, agent: Agent) -> str | None:
        if agent.is_workflow_child and agent.parent_timestamp:
            return self._parent_tribes.get(agent.parent_timestamp, agent.tribe)
        return agent.tribe

    def _summary_text(self) -> Text:
        counts = self._plan.counts
        text = Text()
        text.append(f"{len(self._selected)} selected", style="bold cyan")
        text.append(f"  {counts.kill} kill", style="yellow")
        text.append(f"  {counts.dismiss} dismiss", style="green")
        if counts.cascaded_workflow_children:
            text.append(
                f"  {counts.cascaded_workflow_children} child cascade",
                style="magenta",
            )
        filter_label = self._filter_label()
        if filter_label:
            text.append(f"\nfilter: {filter_label}", style="dim")
        return text

    def _hint_text(self) -> str:
        return "d/r/f/w filters  t tribe  / text  space toggle  a all  enter preview"

    def _filter_label(self) -> str:
        parts: list[str] = []
        if self._status_filter:
            parts.append(self._status_filter)
        if self._tribe_filter:
            parts.append(f"@{self._tribe_filter}")
        if self._text_filter:
            parts.append(f"/{self._text_filter}")
        return " ".join(parts)

    def _agent_row_label(self, agent: Agent) -> Text:
        selected = agent.identity in self._selected
        text = Text()
        text.append("[x] " if selected else "[ ] ", style="cyan" if selected else "dim")
        text.append(agent.display_name, style="bold" if selected else "")
        if agent.agent_name:
            text.append(f" @{agent.agent_name}", style="cyan")
        effective_tribe = self._effective_tribe(agent)
        if effective_tribe:
            text.append(f"  @{effective_tribe}", style="magenta")
        text.append(f"\n   {agent.status}", style="dim")
        if agent.pid is not None:
            text.append(f"  pid {agent.pid}", style="dim")
        return text


__all__ = ["AgentCleanupCustomModal"]
