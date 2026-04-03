"""Regression tests for AgentList keybinding behavior."""

from __future__ import annotations

from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import OptionList

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_list import AgentList


def _make_agent() -> Agent:
    """Create a minimal running agent."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="pat_ui_integration",
        project_file="/tmp/pat/pat.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 3, 14, 5, 18),
    )


class _EnterPassthroughApp(App[None]):
    """Minimal app to verify Enter reaches app-level bindings."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("enter", "jump_to_agent_changespec", show=False)]

    def __init__(self) -> None:
        super().__init__()
        self.jump_count = 0
        self.option_selected_count = 0

    def compose(self) -> ComposeResult:
        yield AgentList(id="agent-list")

    def action_jump_to_agent_changespec(self) -> None:
        self.jump_count += 1

    def on_option_list_option_selected(self, _: OptionList.OptionSelected) -> None:
        self.option_selected_count += 1

    def on_mount(self) -> None:
        agent_list = self.query_one(AgentList)
        agent_list.update_list([_make_agent()], current_idx=0, has_focus=True)
        agent_list.focus()


def test_agent_list_merged_bindings_exclude_enter() -> None:
    """Merged AgentList bindings must not include Enter->select."""
    merged = AgentList._merge_bindings()
    assert "enter" not in merged.key_to_bindings
    assert "up" in merged.key_to_bindings
    assert "down" in merged.key_to_bindings


async def test_enter_passthrough_reaches_app_binding() -> None:
    """Pressing Enter on AgentList triggers app action, not OptionList select."""
    async with _EnterPassthroughApp().run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert pilot.app.jump_count == 1
        assert pilot.app.option_selected_count == 0
