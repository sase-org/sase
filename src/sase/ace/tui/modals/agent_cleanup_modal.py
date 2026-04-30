"""Agent cleanup command panel for the ace TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
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
    CLEANUP_SCOPE_TAG,
    DISMISSABLE_STATUSES,
    AgentCleanupPlanWire,
    AgentCleanupRequestWire,
)

if TYPE_CHECKING:
    from ..models import Agent

AgentCleanupAction = Literal[
    "dismiss_panel_done",
    "dismiss_all_done",
    "kill_panel",
    "kill_all",
    "marked",
    "group",
    "tag",
    "custom",
]
AgentCleanupAgentIdentity = tuple[Any, str, str | None]
_StatusFilter = Literal["done", "running", "failed", "waiting"]


@dataclass(frozen=True)
class AgentCleanupResult:
    """Selected cleanup action."""

    action: AgentCleanupAction


@dataclass(frozen=True)
class AgentCleanupTagResult:
    """Selected tag for tag-scoped cleanup."""

    tag: str


@dataclass(frozen=True)
class AgentCleanupCustomResult:
    """Selected agent identities for custom cleanup."""

    identities: tuple[AgentCleanupAgentIdentity, ...]


@dataclass(frozen=True)
class AgentCleanupPanelState:
    """Counts and availability for the cleanup panel shell."""

    focused_panel_label: str
    panel_running_count: int
    panel_completed_count: int
    panel_failed_count: int
    all_running_count: int
    all_completed_count: int
    all_failed_count: int
    marked_count: int
    group_count: int
    tag_count: int


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
                "m marked  g group  q close",
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
                "custom",
                "c",
                "Custom selection",
                f"{panel_cleanup_count} candidates in {state.focused_panel_label}",
                panel_cleanup_count > 0,
            ),
        ]


@dataclass(frozen=True)
class _TagRow:
    tag: str
    plan: AgentCleanupPlanWire


class AgentCleanupTagModal(ModalScreen[AgentCleanupTagResult | None]):
    """Choose a tag and preview its cleanup plan."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "choose_highlighted", "Choose"),
    ]

    def __init__(self, *, tags: tuple[str, ...], targets: list[Agent]) -> None:
        super().__init__()
        self._targets = list(targets)
        self._rows = [self._build_row(tag) for tag in sorted(set(tags), key=str.lower)]

    def compose(self) -> ComposeResult:
        with Container(id="agent-cleanup-tag-container"):
            yield Label("Cleanup by Tag", id="agent-cleanup-title")
            yield OptionList(
                *[
                    Option(
                        self._tag_row_label(row),
                        id=f"tag:{row.tag}",
                        disabled=not self._row_enabled(row),
                    )
                    for row in self._rows
                ],
                id="agent-cleanup-tag-list",
            )
            yield Static(
                "enter choose  q close",
                id="agent-cleanup-hints",
            )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_choose_highlighted(self) -> None:
        option_list = self.query_one("#agent-cleanup-tag-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return
        option = option_list.get_option_at_index(highlighted)
        if option.disabled or option.id is None:
            return
        tag = str(option.id).removeprefix("tag:")
        self.dismiss(AgentCleanupTagResult(tag=tag))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.disabled or event.option.id is None:
            return
        tag = str(event.option.id).removeprefix("tag:")
        self.dismiss(AgentCleanupTagResult(tag=tag))

    def _build_row(self, tag: str) -> _TagRow:
        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_TAG,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            tag=tag,
            include_pidless_as_dismissable=True,
        )
        plan = plan_agent_cleanup(agents_to_cleanup_targets(self._targets), request)
        return _TagRow(tag=tag, plan=plan)

    @staticmethod
    def _row_enabled(row: _TagRow) -> bool:
        return bool(row.plan.kill_items or row.plan.dismiss_items)

    def _tag_row_label(self, row: _TagRow) -> Text:
        text = Text()
        enabled = self._row_enabled(row)
        tag_style = "bold cyan" if enabled else "dim"
        detail_style = "dim" if enabled else "dim italic"
        text.append(f"@{row.tag}", style=tag_style)
        counts = row.plan.counts
        text.append(
            f"\n   {counts.kill} kill  {counts.dismiss} dismiss  "
            f"{counts.cascaded_workflow_children} child cascade",
            style=detail_style,
        )
        return text


class AgentCleanupCustomModal(ModalScreen[AgentCleanupCustomResult | None]):
    """Custom selector for low-keystroke cleanup selection."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("d", "filter_done", "Done"),
        ("r", "filter_running", "Running"),
        ("f", "filter_failed", "Failed"),
        ("w", "filter_waiting", "Waiting"),
        ("t", "cycle_tag_filter", "Tag"),
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
        self._parent_tags = {
            agent.raw_suffix: agent.tag
            for agent in self._targets
            if agent.raw_suffix and not agent.is_workflow_child
        }
        self._selected: set[AgentCleanupAgentIdentity] = set()
        self._status_filter: _StatusFilter | None = None
        self._tag_filter: str | None = None
        self._text_filter = ""
        self._known_tags = self._candidate_tags()
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

    def action_cycle_tag_filter(self) -> None:
        if not self._known_tags:
            self._tag_filter = None
        elif self._tag_filter is None:
            self._tag_filter = self._known_tags[0]
        else:
            idx = self._known_tags.index(self._tag_filter)
            self._tag_filter = (
                None if idx == len(self._known_tags) - 1 else self._known_tags[idx + 1]
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

    def _set_status_filter(self, value: _StatusFilter) -> None:
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
            self._tag_filter is not None
            and self._effective_tag(agent) != self._tag_filter
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
            self._effective_tag(agent) or "",
        ]
        return " ".join(parts).lower()

    def _candidate_tags(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    effective_tag
                    for agent in self._candidates
                    if (effective_tag := self._effective_tag(agent))
                },
                key=str.lower,
            )
        )

    def _effective_tag(self, agent: Agent) -> str | None:
        if agent.is_workflow_child and agent.parent_timestamp:
            return self._parent_tags.get(agent.parent_timestamp, agent.tag)
        return agent.tag

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
        return "d/r/f/w filters  t tag  / text  space toggle  a all  enter preview"

    def _filter_label(self) -> str:
        parts: list[str] = []
        if self._status_filter:
            parts.append(self._status_filter)
        if self._tag_filter:
            parts.append(f"@{self._tag_filter}")
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
        effective_tag = self._effective_tag(agent)
        if effective_tag:
            text.append(f"  @{effective_tag}", style="magenta")
        text.append(f"\n   {agent.status}", style="dim")
        if agent.pid is not None:
            text.append(f"  pid {agent.pid}", style="dim")
        return text
