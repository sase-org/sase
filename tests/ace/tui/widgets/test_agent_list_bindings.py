"""Regression tests for AgentList keybinding behavior."""

from __future__ import annotations

from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import OptionList

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_list import AgentList


def _make_plain_agent(
    cl_name: str = "test", raw_suffix: str = "20240101120000"
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/p.gp",
        status="RUNNING",
        start_time=datetime(2024, 1, 1, 12, 0, 0),
        raw_suffix=raw_suffix,
    )


def test_mark_prefix_renders_when_marked() -> None:
    """A marked agent's Option text starts with the green [✓] prefix."""
    agent = _make_plain_agent()
    widget = AgentList()
    option = widget._format_agent_option(
        agent,
        0,
        is_selected=False,
        is_marked=True,
    )
    plain = option.prompt.plain  # type: ignore[union-attr]
    assert "[✓] " in plain


def test_mark_prefix_absent_when_unmarked() -> None:
    """Without is_marked, the [✓] prefix is not rendered."""
    agent = _make_plain_agent()
    widget = AgentList()
    option = widget._format_agent_option(
        agent,
        0,
        is_selected=False,
        is_marked=False,
    )
    assert "[✓]" not in option.prompt.plain  # type: ignore[union-attr]


def test_tag_badge_omitted_for_tagged_agent_row() -> None:
    """A tagged agent keeps tag text out of the row prompt."""
    agent = _make_plain_agent()
    agent.tag = "release-blockers"
    widget = AgentList()
    option = widget._format_agent_option(agent, 0, is_selected=False)
    plain = option.prompt.plain  # type: ignore[union-attr]
    assert "@release-blockers" not in plain


def test_plain_untagged_agent_omits_at_annotation() -> None:
    agent = _make_plain_agent()
    widget = AgentList()
    option = widget._format_agent_option(agent, 0, is_selected=False)
    plain = option.prompt.plain  # type: ignore[union-attr]
    # A plain agent without an agent_name and without a tag must not contain '@'.
    assert "@" not in plain


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
        agent_list.update_list([_make_agent()], current_idx=0)
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
