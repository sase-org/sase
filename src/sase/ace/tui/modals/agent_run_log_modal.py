"""Agent Run Log modal for viewing agent history of a CL."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.hints import build_editor_args
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_loader import load_all_agents
from sase.ace.tui.widgets.prompt_panel._helpers import append_model_field

from .base import OptionListNavigationMixin


def _load_agents_for_cl(cl_name: str) -> list[Agent]:
    """Load agents for a specific CL, excluding workflow children."""
    all_agents = load_all_agents()
    return [a for a in all_agents if a.cl_name == cl_name and not a.is_workflow_child]


def _group_agents_by_date(
    agents: list[Agent],
) -> list[tuple[str, list[Agent]]]:
    """Group agents by date category (Running, Today, Yesterday, older dates)."""
    now = datetime.now()
    today = now.date()

    running: list[Agent] = []
    by_date: dict[str, list[Agent]] = {}

    for agent in agents:
        if agent.status == "RUNNING":
            running.append(agent)
            continue

        if agent.start_time is None:
            by_date.setdefault("Unknown", []).append(agent)
            continue

        agent_date = agent.start_time.date()
        if agent_date == today:
            by_date.setdefault("Today", []).append(agent)
        elif (today - agent_date).days == 1:
            by_date.setdefault("Yesterday", []).append(agent)
        else:
            date_str = agent_date.strftime("%Y-%m-%d")
            by_date.setdefault(date_str, []).append(agent)

    groups: list[tuple[str, list[Agent]]] = []
    if running:
        groups.append(("Running", running))

    # Add date groups in order: Today, Yesterday, then older dates descending
    for key in ("Today", "Yesterday"):
        if key in by_date:
            groups.append((key, by_date.pop(key)))

    # Remaining dates in reverse chronological order
    for key in sorted(by_date.keys(), reverse=True):
        groups.append((key, by_date[key]))

    return groups


def _status_icon(status: str) -> tuple[str, str]:
    """Return (icon, style) for an agent status."""
    if status == "RUNNING":
        return "\u26a1", "bold #FFD700"
    if status == "DONE":
        return "\u2713", "bold green"
    if status == "FAILED":
        return "\u2717", "bold red"
    return "\u00b7", "dim"


class AgentRunLogModal(OptionListNavigationMixin, ModalScreen[None]):
    """Modal for viewing agent run history of a CL."""

    _option_list_id = "agent-log-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "open_chat", "Open Chat"),
        ("e", "open_chat", "Open Chat"),
        ("ctrl+d", "scroll_detail_down", "Scroll Down"),
        ("ctrl+u", "scroll_detail_up", "Scroll Up"),
    ]

    def __init__(self, cl_name: str) -> None:
        super().__init__()
        self._cl_name = cl_name
        self._agents: list[Agent] = _load_agents_for_cl(cl_name)
        self._grouped: list[tuple[str, list[Agent]]] = _group_agents_by_date(
            self._agents
        )

    def compose(self) -> ComposeResult:
        total = len(self._agents)
        with Container(id="agent-log-container"):
            yield Label(
                f"Agent Run Log for: {self._cl_name}  [{total} runs]",
                id="agent-log-title",
            )
            with Horizontal(id="agent-log-panels"):
                with Vertical(id="agent-log-list-panel"):
                    yield OptionList(
                        *self._create_options(),
                        id="agent-log-list",
                    )
                with Vertical(id="agent-log-detail-panel"):
                    with VerticalScroll(id="agent-log-detail-scroll"):
                        yield Static("", id="agent-log-detail")
            yield Static(
                "j/k: navigate  enter/e: open chat  Ctrl+D/U: scroll  Esc: close",
                id="agent-log-hints",
            )

    def _create_options(self) -> list[Option]:
        """Create OptionList items with date-group headers."""
        options: list[Option] = []
        for group_name, agents in self._grouped:
            header_text = Text(
                f"\u2500\u2500 {group_name} \u2500\u2500", style="bold dim"
            )
            options.append(
                Option(header_text, id=f"__header__{group_name}", disabled=True)
            )
            for agent in agents:
                options.append(
                    Option(
                        self._create_agent_label(agent),
                        id=f"agent__{agent.raw_suffix or id(agent)}",
                    )
                )
        return options

    def _create_agent_label(self, agent: Agent) -> Text:
        """Create styled label for an agent entry."""
        text = Text()
        icon, icon_style = _status_icon(agent.status)
        text.append(f"  {icon}", style=icon_style)
        text.append(f"[{agent.display_type}] ", style="bold #87D7FF")
        text.append(f"{agent.start_time_short} ", style="dim")

        # Status with color
        status_style = {
            "RUNNING": "bold #FFD700",
            "DONE": "green",
            "FAILED": "bold red",
        }.get(agent.status, "dim")
        text.append(agent.status, style=status_style)

        # Agent name if available
        if agent.agent_name:
            text.append(f" {agent.agent_name}", style="#AF87D7")

        return text

    def _get_flat_agents(self) -> list[Agent]:
        """Get flat list of agents from grouped data."""
        result: list[Agent] = []
        for _, agents in self._grouped:
            result.extend(agents)
        return result

    def _get_agent_for_option(self, opt_id: str) -> Agent | None:
        """Find agent matching an option ID."""
        if opt_id.startswith("__header__"):
            return None
        suffix = opt_id.removeprefix("agent__")
        for agent in self._get_flat_agents():
            if str(agent.raw_suffix or id(agent)) == suffix:
                return agent
        return None

    def on_mount(self) -> None:
        flat = self._get_flat_agents()
        if flat:
            self._update_detail(flat[0])
            option_list = self.query_one("#agent-log-list", OptionList)
            self._skip_to_first_item(option_list)
        else:
            try:
                detail = self.query_one("#agent-log-detail", Static)
                detail.update(
                    Text("No agent runs found for this CL.", style="dim italic")
                )
            except Exception:
                pass

    def _skip_to_first_item(self, option_list: OptionList) -> None:
        """Skip to the first non-header item."""
        for i in range(option_list.option_count):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    def action_next_option(self) -> None:
        """Move to next non-header option."""
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        current = option_list.highlighted
        if current is None:
            self._skip_to_first_item(option_list)
            return
        for i in range(current + 1, option_list.option_count):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    def action_prev_option(self) -> None:
        """Move to previous non-header option."""
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        current = option_list.highlighted
        if current is None:
            return
        for i in range(current - 1, -1, -1):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option and event.option.id:
            agent = self._get_agent_for_option(str(event.option.id))
            if agent is not None:
                self._update_detail(agent)

    def _get_highlighted_agent(self) -> Agent | None:
        """Get the currently highlighted agent."""
        option_list = self.query_one("#agent-log-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            opt = option_list.get_option_at_index(highlighted)
            if opt.id:
                return self._get_agent_for_option(str(opt.id))
        except Exception:
            pass
        return None

    def _update_detail(self, agent: Agent) -> None:
        """Update the detail panel for an agent."""
        try:
            detail = self.query_one("#agent-log-detail", Static)
        except Exception:
            return

        text = Text()

        # AGENT DETAILS section
        text.append("AGENT DETAILS\n", style="bold underline #87D7FF")
        text.append("Status: ", style="bold #87D7FF")
        status_style = {
            "RUNNING": "bold #FFD700",
            "DONE": "green",
            "FAILED": "bold red",
        }.get(agent.status, "")
        text.append(f"{agent.status}\n", style=status_style)

        append_model_field(text, agent.model, agent.llm_provider)

        if agent.vcs_provider:
            text.append("VCS: ", style="bold #87D7FF")
            text.append(f"{agent.vcs_provider}\n")

        text.append("Timestamp: ", style="bold #87D7FF")
        text.append(f"{agent.start_time_display}\n")

        text.append("Duration: ", style="bold #87D7FF")
        text.append(f"{agent.duration_display}\n")

        if agent.workspace_num is not None:
            text.append("Workspace: ", style="bold #87D7FF")
            text.append(f"#{agent.workspace_num}\n")

        if agent.agent_name:
            text.append("Name: ", style="bold #87D7FF")
            text.append(f"{agent.agent_name}\n")

        if agent.workflow:
            text.append("Workflow: ", style="bold #87D7FF")
            text.append(f"{agent.workflow}\n")

        if agent.error_message:
            text.append("Error: ", style="bold red")
            text.append(f"{agent.error_message}\n", style="red")

        # AGENT XPROMPT section
        xprompt_content = agent.get_raw_xprompt_content()
        if xprompt_content:
            text.append("\n")
            text.append("\u2500" * 40 + "\n", style="dim")
            text.append("AGENT XPROMPT\n", style="bold underline #87D7FF")
            # Truncate if very long
            lines = xprompt_content.split("\n")
            if len(lines) > 50:
                xprompt_content = "\n".join(lines[:50]) + "\n... (truncated)"
            text.append(f"{xprompt_content}\n")

        # AGENT CHAT section
        response_content = agent.get_response_content()
        if response_content:
            text.append("\n")
            text.append("\u2500" * 40 + "\n", style="dim")
            text.append("AGENT CHAT\n", style="bold underline #87D7FF")

            # First 200 lines, syntax-highlighted
            lines = response_content.split("\n")
            preview = "\n".join(lines[:200])
            if len(lines) > 200:
                preview += "\n... (truncated, press Enter to view full chat)"

            text.append(f"{preview}\n")

        detail.update(text)

    def action_open_chat(self) -> None:
        """Open the highlighted agent's chat in $EDITOR."""
        agent = self._get_highlighted_agent()
        if agent is None:
            return

        if agent.response_path is None:
            self.notify("No chat file available", severity="warning")
            return

        expanded_path = os.path.expanduser(agent.response_path)
        if not os.path.exists(expanded_path):
            self.notify("Chat file not found", severity="warning")
            return

        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [expanded_path])

        with self.app.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

    def action_scroll_detail_down(self) -> None:
        """Scroll the detail panel down by half a page."""
        scroll = self.query_one("#agent-log-detail-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_detail_up(self) -> None:
        """Scroll the detail panel up by half a page."""
        scroll = self.query_one("#agent-log-detail-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)
