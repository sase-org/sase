"""Target-picker Enter must stay on the prompt, not the filtered agent list."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._prompt_input_bar_dispatch import (
    PromptInputBarDispatchMixin,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _FilteredRemoteList(OptionList):
    """Stand-in for a filtered remote Agents list that bulk-stops on Enter."""

    BINDINGS = [("enter", "bulk_stop", "Stop")]

    def action_bulk_stop(self) -> None:
        app = self.app
        if isinstance(app, DispatchPickerFocusApp):
            app.bulk_stops += 1


class DispatchPickerFocusApp(App[None]):
    """Prompt plus an underlying filtered remote list competing for Enter."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "#gh:sase") -> None:
        super().__init__()
        self._initial_value = initial_value
        self.submitted: list[str] = []
        self.bulk_stops = 0

    def compose(self) -> ComposeResult:
        yield _FilteredRemoteList(
            Option("apollo-worker", id="apollo-worker"),
            id="filtered-remote-list",
        )
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode="prompt",
            id="prompt-input-bar",
        )

    def on_prompt_input_bar_submitted(self, event: object) -> None:
        value = getattr(event, "value", "")
        if isinstance(value, str):
            self.submitted.append(value)


def _seed_remote_targets(bar: PromptInputBar) -> None:
    bar._dispatch_catalog_loading = False
    bar._dispatch_catalog_loaded = True
    bar._dispatch_target_rows = {
        "apollo": {
            "alias": "apollo",
            "status": "ok",
            "endpoint": "https://apollo.example",
        }
    }


def _remote_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="remote",
        project_file="/fleet/apollo/project.yml",
        status="running",
        start_time=None,
        agent_name="worker",
        raw_suffix="apollo-worker",
        fleet_origin_alias="apollo",
        fleet_origin_installation_id="sase_inst_v1_" + "a" * 64,
        fleet_exact_locator={"schema_version": 1},
        fleet_capabilities={"resource": ["lifecycle.stop"]},
    )


class _PromptOwnerApp:
    """Harness for Agents-row action availability while a prompt is mounted."""

    current_tab = "agents"
    screen = object()

    def __init__(self, *, prompt_active: bool, agent: Agent) -> None:
        self._prompt_active = prompt_active
        self._agent = agent

    def _prompt_input_active(self) -> bool:
        return self._prompt_active

    def _get_selected_agent(self) -> Agent:
        return self._agent


@pytest.fixture
def no_catalog_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        PromptInputBarDispatchMixin,
        "_warm_dispatch_target_catalog",
        lambda self: None,
    )


async def test_picker_cancel_restores_prompt_owner_and_enter_submits(
    no_catalog_worker: None,
) -> None:
    app = DispatchPickerFocusApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = app.query_one(PromptTextArea)
        remote_list = app.query_one(_FilteredRemoteList)
        _seed_remote_targets(bar)

        remote_list.focus()
        await pilot.pause()
        text_area.focus()
        await pilot.pause()
        assert app.focused is text_area

        bar.request_dispatch_target_picker()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert app.focused is text_area
        await pilot.press("enter")
        await pilot.pause()

        assert app.bulk_stops == 0
        assert app.submitted == ["#gh:sase"]


async def test_picker_select_keeps_prompt_owner_and_enter_submits(
    no_catalog_worker: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = DispatchPickerFocusApp("%dispatch:apollo\n#gh:sase")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = app.query_one(PromptTextArea)
        remote_list = app.query_one(_FilteredRemoteList)
        _seed_remote_targets(bar)

        remote_list.focus()
        await pilot.pause()
        text_area.focus()
        await pilot.pause()

        bar.request_dispatch_target_picker()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert app.focused is text_area
        assert "%dispatch:apollo" in text_area.text
        monkeypatch.setattr(
            bar, "_maybe_preflight_dispatch_submission", lambda _prepared: False
        )
        await pilot.press("enter")
        await pilot.pause()

        assert app.bulk_stops == 0
        assert app.submitted
        assert "%dispatch:apollo" in app.submitted[0]
        assert "#gh:sase" in app.submitted[0]


def test_mounted_prompt_disables_remote_stop_and_row_enter() -> None:
    agent = _remote_agent()
    prompt_open = _PromptOwnerApp(prompt_active=True, agent=agent)
    prompt_closed = _PromptOwnerApp(prompt_active=False, agent=agent)

    def allow(_action: str, _params: tuple[object, ...]) -> bool:
        return True

    assert check_app_action(prompt_open, "kill_agent", (), allow) is False
    assert check_app_action(prompt_open, "jump_to_agent_patch", (), allow) is False
    assert check_app_action(prompt_closed, "kill_agent", (), allow) is True
