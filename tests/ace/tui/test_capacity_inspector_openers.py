"""Tests for the capacity inspector's chip, leader, and palette entry points."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
from sase.ace.tui.actions.axe_service import AxeServiceMixin
from sase.ace.tui.commands.catalog import build_command_catalog
from sase.ace.tui.commands.execute import execute_command
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.capacity_inspector_modal import CapacityInspectorModal
from sase.ace.tui.widgets import AgentLoadIndicator
from tests.test_machine_capacity_report import (
    _report_from_records,
    _screenshot_records,
)


def _option_text(option: object) -> str:
    prompt = option.prompt
    return prompt.plain if isinstance(prompt, Text) else str(prompt)


class _InspectorOpenerApp(LeaderModeMixin, AxeServiceMixin, App[None]):
    def __init__(self) -> None:
        super().__init__()
        self._machine_capacity_report = _report_from_records(_screenshot_records())
        self._keymap_registry = load_keymap_registry({})
        self._leader_mode_active = False
        self._last_leader_key: str | None = None
        self.current_tab = "agents"

    def compose(self) -> ComposeResult:
        yield AgentLoadIndicator(id="agent-load-indicator")

    def on_mount(self) -> None:
        self.query_one("#agent-load-indicator", AgentLoadIndicator).update_load(
            8,
            5,
            running_nodes=6,
            report=self._machine_capacity_report,
        )

    def _refresh_current_tab(self) -> None:
        pass


@pytest.mark.parametrize("opener", ("chip", "leader", "palette"))
async def test_capacity_inspector_opens_from_each_entry_point(opener: str) -> None:
    app = _InspectorOpenerApp()

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        if opener == "chip":
            await pilot.click("#agent-load-indicator")
        elif opener == "leader":
            app._handle_leader_key("l")
        else:
            command = next(
                item
                for item in build_command_catalog(app._keymap_registry)
                if item.id == "leader.capacity_inspector"
            )
            assert command.label == "Show capacity inspector"
            execute_command(app, command)
        await pilot.pause()

        assert isinstance(app.screen_stack[-1], CapacityInspectorModal)


async def test_inspector_selection_jumps_to_the_named_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    navigate = MagicMock(return_value=True)
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.navigate_to_agent_tab",
        navigate,
    )
    app = _InspectorOpenerApp()

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        app.action_show_capacity_inspector()
        await pilot.pause()
        modal = app.screen_stack[-1]
        options = modal.query_one("#capacity-inspector-options", OptionList)
        target_index = next(
            index
            for index, option in enumerate(options.options)
            if "worker-a" in _option_text(option)
        )
        options.highlighted = target_index
        await pilot.press("enter")
        await pilot.pause()

    navigate.assert_called_once_with(app, "worker-a")
