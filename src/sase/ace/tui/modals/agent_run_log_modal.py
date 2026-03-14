"""Agent Run Log modal for viewing agent history of a CL."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.dismissed_agents import load_dismissed_agents, load_dismissed_bundles
from sase.ace.hints import build_editor_args
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_loader import load_all_agents
from sase.ace.tui.widgets.prompt_panel._helpers import append_model_field

from .base import OptionListNavigationMixin

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import AgentType


def _load_agents_for_cl(
    cl_name: str,
) -> tuple[list[Agent], set[tuple[AgentType, str, str | None]]]:
    """Load agents for a specific CL, including dismissed ones.

    Also includes agents that created this CL/PR via meta_new_cl or
    meta_new_pr output variables in embedded xprompt workflows.

    Returns:
        Tuple of (agents, dismissed_identities) where agents includes both
        active and dismissed agents (excluding workflow children), and
        dismissed_identities is the set of all dismissed agent identity tuples.
    """
    from sase.ace.tui.actions.agents._notification_actions import (
        get_meta_changespec_name,
    )

    all_agents = load_all_agents()
    active: list[Agent] = []
    active_ids: set[int] = set()
    for a in all_agents:
        if a.is_workflow_child:
            continue
        if a.cl_name == cl_name:
            active.append(a)
            active_ids.add(id(a))
            continue
        # Include project agents that created this CL/PR
        cs_name = get_meta_changespec_name(a)
        if cs_name == cl_name:
            active.append(a)
            active_ids.add(id(a))

    dismissed_ids = load_dismissed_agents()

    # Build secondary index for robust matching (same as _load_agents in _core.py)
    dismissed_suffixes: set[str] = {
        raw_suffix for _, _, raw_suffix in dismissed_ids if raw_suffix is not None
    }

    # Load dismissed bundles for this CL, deduplicating against active agents
    active_identities = {a.identity for a in active}
    active_suffixes = {a.raw_suffix for a in active if a.raw_suffix is not None}

    dismissed_for_cl: list[Agent] = []
    for agent in load_dismissed_bundles():
        if agent.is_workflow_child:
            continue
        # Match by cl_name or by meta CL/PR creation
        if agent.cl_name != cl_name and get_meta_changespec_name(agent) != cl_name:
            continue
        # Skip if already present as an active agent
        if agent.identity in active_identities:
            continue
        if agent.raw_suffix is not None and agent.raw_suffix in active_suffixes:
            continue
        # Only include if actually in the dismissed set
        if agent.identity in dismissed_ids or (
            agent.raw_suffix is not None and agent.raw_suffix in dismissed_suffixes
        ):
            dismissed_for_cl.append(agent)

    return active + dismissed_for_cl, dismissed_ids


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


def _status_icon(status: str, *, dismissed: bool = False) -> tuple[str, str]:
    """Return (icon, style) for an agent status."""
    if dismissed:
        return "\u25cb", "dim"  # ○ empty circle for dismissed
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
        ("e", "open_chat", "Open Chat"),
        ("upper_r", "revive_agent", "Revive"),
        ("ctrl+d", "scroll_detail_down", "Scroll Down"),
        ("ctrl+u", "scroll_detail_up", "Scroll Up"),
    ]

    def __init__(self, cl_name: str) -> None:
        super().__init__()
        self._cl_name = cl_name
        agents, dismissed_ids = _load_agents_for_cl(cl_name)
        self._agents: list[Agent] = agents
        self._dismissed_identities = dismissed_ids
        self._dismissed_suffixes: set[str] = {
            raw_suffix for _, _, raw_suffix in dismissed_ids if raw_suffix is not None
        }
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
                "j/k: navigate  enter: jump to Agents  e: open chat  R: revive  Ctrl+D/U: scroll  Esc: close",
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

    def _is_dismissed(self, agent: Agent) -> bool:
        """Check if an agent is dismissed."""
        return agent.identity in self._dismissed_identities or (
            agent.raw_suffix is not None
            and agent.raw_suffix in self._dismissed_suffixes
        )

    def _create_agent_label(self, agent: Agent) -> Text:
        """Create styled label for an agent entry."""
        dismissed = self._is_dismissed(agent)
        text = Text()
        icon, icon_style = _status_icon(agent.status, dismissed=dismissed)
        text.append(f"  {icon}", style=icon_style)

        if dismissed:
            text.append(f"[{agent.display_type}] ", style="dim")
            text.append(f"{agent.start_time_short} ", style="dim")
            text.append("DISMISSED", style="dim italic")
            if agent.agent_name:
                text.append(f" {agent.agent_name}", style="dim")
        else:
            text.append(f"[{agent.display_type}] ", style="bold #87D7FF")
            text.append(f"{agent.start_time_short} ", style="dim")
            status_style = {
                "RUNNING": "bold #FFD700",
                "DONE": "green",
                "FAILED": "bold red",
            }.get(agent.status, "dim")
            text.append(agent.status, style=status_style)
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
        """Move to next non-header option, wrapping to top at end."""
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
        # Wrap to first non-header item
        self._skip_to_first_item(option_list)

    def action_prev_option(self) -> None:
        """Move to previous non-header option, wrapping to bottom at start."""
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
        # Wrap to last non-header item
        for i in range(option_list.option_count - 1, -1, -1):
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

        dismissed = self._is_dismissed(agent)

        # AGENT DETAILS section
        text.append("AGENT DETAILS\n", style="bold underline #87D7FF")
        text.append("Status: ", style="bold #87D7FF")
        if dismissed:
            text.append(f"DISMISSED ({agent.status})\n", style="dim italic")
        else:
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

        text.append("Timestamps: ", style="bold #87D7FF")
        text.append(f"{agent.timestamps_display}\n")

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

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle enter/click on an option — jump to Agents tab."""
        event.stop()
        self.action_jump_to_agent_tab()

    def action_jump_to_agent_tab(self) -> None:
        """Jump to the Agents tab with the highlighted agent selected."""
        agent = self._get_highlighted_agent()
        if agent is None:
            return

        # If dismissed, revive it first so it appears on the Agents tab
        if self._is_dismissed(agent):
            self.app._do_revive_agent(agent)  # type: ignore[attr-defined]

        # Capture identifying info before dismissing
        target_identity = agent.identity
        target_raw_suffix = agent.raw_suffix

        # Dismiss the modal and switch to Agents tab
        self.dismiss()
        app = self.app
        app._save_current_tab_position()  # type: ignore[attr-defined]
        app.current_tab = "agents"  # type: ignore[attr-defined]

        # Find and select the matching agent
        for idx, a in enumerate(app._agents):  # type: ignore[attr-defined]
            if a.identity == target_identity:
                app.current_idx = idx  # type: ignore[attr-defined]
                return
        # Fallback: match by raw_suffix (identity may differ after revive)
        if target_raw_suffix:
            for idx, a in enumerate(app._agents):  # type: ignore[attr-defined]
                if a.raw_suffix == target_raw_suffix:
                    app.current_idx = idx  # type: ignore[attr-defined]
                    return

        app.notify("Agent not found on Agents tab", severity="warning")  # type: ignore[attr-defined]

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

    def action_revive_agent(self) -> None:
        """Revive the highlighted dismissed agent."""
        agent = self._get_highlighted_agent()
        if agent is None:
            return

        if not self._is_dismissed(agent):
            self.notify("Agent is not dismissed", severity="warning")
            return

        # Delegate to the app's revive logic (AgentRevivalMixin)
        self.app._do_revive_agent(agent)  # type: ignore[attr-defined]

        # Refresh modal data to reflect the revive
        self._refresh_agents()

    def _refresh_agents(self) -> None:
        """Reload agents and refresh the option list."""
        # Capture currently highlighted agent suffix for re-selection
        current_agent = self._get_highlighted_agent()
        current_suffix = (
            str(current_agent.raw_suffix or id(current_agent))
            if current_agent
            else None
        )

        # Reload data
        agents, dismissed_ids = _load_agents_for_cl(self._cl_name)
        self._agents = agents
        self._dismissed_identities = dismissed_ids
        self._dismissed_suffixes = {
            raw_suffix for _, _, raw_suffix in dismissed_ids if raw_suffix is not None
        }
        self._grouped = _group_agents_by_date(self._agents)

        # Update title
        try:
            title = self.query_one("#agent-log-title", Label)
            title.update(
                f"Agent Run Log for: {self._cl_name}  [{len(self._agents)} runs]"
            )
        except Exception:
            pass

        # Rebuild option list
        option_list = self.query_one("#agent-log-list", OptionList)
        option_list.clear_options()
        for opt in self._create_options():
            option_list.add_option(opt)

        # Try to re-select the same agent
        if current_suffix:
            target_id = f"agent__{current_suffix}"
            for i in range(option_list.option_count):
                try:
                    opt = option_list.get_option_at_index(i)
                    if opt.id and str(opt.id) == target_id:
                        option_list.highlighted = i
                        agent = self._get_agent_for_option(target_id)
                        if agent:
                            self._update_detail(agent)
                        return
                except Exception:
                    continue

        # Fallback: select first non-header item
        self._skip_to_first_item(option_list)
        flat = self._get_flat_agents()
        if flat:
            self._update_detail(flat[0])

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
