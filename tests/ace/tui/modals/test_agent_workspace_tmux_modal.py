"""Tests for the agent tmux workspace chooser modal."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.agent_workspace_tmux_modal import (
    AgentWorkspaceTmuxChoice,
    AgentWorkspaceTmuxModal,
    _agent_workspace_tmux_option_text,
    _workspace_tmux_selector_keys,
    build_agent_workspace_tmux_choices,
)
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent


class _TestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _choices(linked: int = 2) -> list[AgentWorkspaceTmuxChoice]:
    choices = [
        AgentWorkspaceTmuxChoice(
            kind="current",
            label="workspaces_lane",
            window_name="",
            project_name="sase",
            workspace_dir="/home/u/.sase/sase_12",
        )
    ]
    for index in range(linked):
        choices.append(
            AgentWorkspaceTmuxChoice(
                kind="linked",
                label=f"repo-{index}",
                window_name=f"repo-{index}_12",
                workspace_dir=f"/w/repo-{index}_12",
                reason=f"reason {index}",
            )
        )
    return choices


def _agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="workspaces_lane",
        project_file="/home/u/.sase/projects/sase/sase.sase",
        status="RUNNING",
        start_time=None,
    )


def test_workspace_tmux_selector_keys_skip_navigation_and_cover_cap() -> None:
    # MAX_KEPT_OPENED_WORKSPACES (50) + CURRENT == 51 single-key selectors.
    keys = _workspace_tmux_selector_keys(51)

    assert len(keys) == 51
    assert len(set(keys)) == 51
    for reserved in ("j", "k", "q", "J", "K", "Q"):
        assert reserved not in keys
    assert keys[:3] == ["a", "b", "c"]
    assert any(key.isdigit() for key in keys)
    assert any(key.isupper() for key in keys)


def test_build_choices_current_first_and_dedupes_linked() -> None:
    agent = _agent()
    events = (
        OpenedWorkspaceDisplayEvent(
            name="sase-core",
            workspace_dir="/w/sase-core_12",
            reason="Need Rust backend context",
            opened_at="2026-06-14T14:24:08+00:00",
            agent_label="code",
        ),
        OpenedWorkspaceDisplayEvent(
            name="sase-core",
            workspace_dir="/w/sase-core_12",
            reason="older duplicate",
            opened_at="2026-06-14T10:00:00+00:00",
        ),
        OpenedWorkspaceDisplayEvent(
            name="bob",
            workspace_dir="/w/bob_12",
            reason="Compare Obsidian workflow",
            opened_at="2026-06-13T10:00:00+00:00",
        ),
    )
    choices = build_agent_workspace_tmux_choices(
        agent, events, current_workspace_dir="/home/u/.sase/sase_12"
    )

    assert [c.kind for c in choices] == ["current", "linked", "linked"]
    assert choices[0].label == "workspaces_lane"
    assert choices[0].project_name == "sase"
    # Linked dedupe keeps the newest event's reason/role.
    assert choices[1].label == "sase-core"
    assert choices[1].window_name == "sase-core_12"
    assert choices[1].reason == "Need Rust backend context"
    assert choices[1].agent_label == "code"
    assert choices[2].label == "bob"


def test_build_choices_window_name_falls_back_to_repo_name() -> None:
    agent = _agent()
    events = (
        OpenedWorkspaceDisplayEvent(
            name="sase-core",
            workspace_dir="",
            reason="",
            opened_at="2026-06-14T14:24:08+00:00",
        ),
    )
    choices = build_agent_workspace_tmux_choices(agent, events)

    # An event without a workspace_dir cannot be opened, so it is dropped.
    assert [c.kind for c in choices] == ["current"]


def test_option_text_includes_type_label_path_and_reason() -> None:
    choices = _choices()
    current = _agent_workspace_tmux_option_text("a", choices[0]).plain
    linked = _agent_workspace_tmux_option_text("b", choices[1]).plain

    assert "a" in current
    assert "CURRENT" in current
    assert "workspaces_lane" in current
    assert "sase" in current

    assert "b" in linked
    assert "LINKED" in linked
    assert "repo-0" in linked
    assert "repo-0_12" in linked
    assert "reason 0" in linked


async def test_modal_enter_selects_highlighted_row() -> None:
    choices = _choices()
    result: object | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = AgentWorkspaceTmuxModal(choices)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#agent-workspace-tmux-list", OptionList)
        option_list.highlighted = 2
        await pilot.press("enter")
        await pilot.pause()

    assert result == 2


async def test_modal_letter_quick_selects_row() -> None:
    choices = _choices()
    result: object | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = AgentWorkspaceTmuxModal(choices)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("b")
        await pilot.pause()

    assert result == 1


async def test_modal_digit_and_uppercase_quick_select() -> None:
    # 24 choices exercises selectors past the lowercase pool into digits, and a
    # larger list reaches the uppercase pool.
    choices = _choices(linked=40)
    selectors = _workspace_tmux_selector_keys(len(choices))

    digit_index = next(i for i, key in enumerate(selectors) if key.isdigit())
    upper_index = next(i for i, key in enumerate(selectors) if key.isupper())

    for index in (digit_index, upper_index):
        result: object | None = "sentinel"
        async with _TestApp().run_test() as pilot:

            def on_dismiss(value: object | None) -> None:
                nonlocal result
                result = value

            modal = AgentWorkspaceTmuxModal(choices)
            pilot.app.push_screen(modal, callback=on_dismiss)
            await pilot.pause()

            await pilot.press(selectors[index])
            await pilot.pause()

        assert result == index


async def test_modal_j_k_move_highlight() -> None:
    async with _TestApp().run_test() as pilot:
        modal = AgentWorkspaceTmuxModal(_choices())
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#agent-workspace-tmux-list", OptionList)
        assert option_list.highlighted == 0

        await pilot.press("j")
        await pilot.pause()
        assert option_list.highlighted == 1

        await pilot.press("k")
        await pilot.pause()
        assert option_list.highlighted == 0


async def test_modal_escape_and_q_cancel() -> None:
    for key in ("escape", "q"):
        result: object | None = "sentinel"
        async with _TestApp().run_test() as pilot:

            def on_dismiss(value: object | None) -> None:
                nonlocal result
                result = value

            modal = AgentWorkspaceTmuxModal(_choices())
            pilot.app.push_screen(modal, callback=on_dismiss)
            await pilot.pause()

            await pilot.press(key)
            await pilot.pause()

        assert result is None
