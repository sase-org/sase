"""Tests for the two-level clan cleanup chooser."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.modals import AgentCleanupClanModal, AgentCleanupClanResult
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType


def _member(
    name: str,
    suffix: str,
    *,
    clan: str,
    generation: str = "generation",
    status: str = "RUNNING",
    pid: int | None = 10,
    agent_type: AgentType = AgentType.RUNNING,
    workflow: str | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=name,
        project_file="/tmp/project.sase",
        status=status,
        start_time=datetime(2026, 7, 19, 8, 0, 0),
        run_start_time=datetime(2026, 7, 19, 8, 0, 0),
        raw_suffix=suffix,
        agent_name=name,
        pid=pid,
        workflow=workflow,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        agent_clan=clan,
        agent_clan_generation=generation,
        tribe="epic",
    )


def _project(*members: Agent) -> tuple[list[Agent], list[Agent]]:
    rows = project_clan_tree(list(members))
    clans = [row for row in rows if row.is_clan_container]
    targets = [row for row in rows if not row.is_clan_container]
    return clans, targets


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def test_clan_modal_builds_preview_rows_and_disables_empty_clan() -> None:
    running = _member("alpha.1", "alpha-1", clan="alpha")
    done = _member("alpha.2", "alpha-2", clan="alpha", status="DONE", pid=None)
    cascade_only = _member(
        "empty.1",
        "empty-1",
        clan="empty",
        agent_type=AgentType.WORKFLOW,
        workflow="step",
        parent_workflow="missing",
        parent_timestamp="missing-parent",
    )
    clans, targets = _project(running, done, cascade_only)

    modal = AgentCleanupClanModal(
        clans=clans,
        targets=targets,
        focused_panel_label="@epic",
    )

    rows = {row.label: row for row in modal._rows}
    assert rows["alpha"].plan.counts.kill == 1
    assert rows["alpha"].plan.counts.dismiss == 1
    assert modal._clan_enabled(rows["alpha"]) is True
    assert modal._clan_enabled(rows["empty"]) is False
    assert "[R1 D1]" in modal._clan_row_label(rows["alpha"]).plain


def test_clan_modal_preview_includes_workflow_child_cascade() -> None:
    parent = _member(
        "alpha.parent",
        "parent-ts",
        clan="alpha",
        agent_type=AgentType.WORKFLOW,
        workflow="wf",
    )
    child = _member(
        "alpha.child",
        "child-ts",
        clan="alpha",
        agent_type=AgentType.WORKFLOW,
        workflow="step",
        parent_workflow="wf",
        parent_timestamp="parent-ts",
    )
    clans, targets = _project(parent, child)

    modal = AgentCleanupClanModal(
        clans=clans,
        targets=targets,
        focused_panel_label="@epic",
    )

    assert modal._rows[0].plan.counts.kill == 1
    assert modal._rows[0].plan.counts.cascaded_workflow_children == 1
    assert "cascade 1" in modal._clan_row_label(modal._rows[0]).plain


def test_clan_modal_preview_renders_only_implicit_global_queue_waits() -> None:
    implicit = _member(
        "alpha.implicit",
        "implicit",
        clan="alpha",
        status="WAITING",
    )
    implicit.wait_runners = 9
    implicit.slot_requested_at = "2026-07-19T08:00:00Z"
    explicit = _member(
        "alpha.explicit",
        "explicit",
        clan="alpha",
        status="WAITING",
    )
    explicit.wait_runners = 0
    explicit.wait_runners_explicit = True
    explicit.slot_requested_at = "2026-07-19T08:00:01Z"
    clans, targets = _project(implicit, explicit)
    modal = AgentCleanupClanModal(
        clans=clans,
        targets=targets,
        focused_panel_label="@epic",
    )

    label = modal._clan_row_label(modal._rows[0])

    assert "[Q1 W2]" in label.plain


async def test_clan_modal_pre_highlights_focused_clan_and_folds_members() -> None:
    alpha = _member("alpha.1", "alpha-1", clan="alpha")
    beta = _member("beta.1", "beta-1", clan="beta")
    clans, targets = _project(alpha, beta)

    async with _TestApp().run_test() as pilot:
        modal = AgentCleanupClanModal(
            clans=clans,
            targets=targets,
            focused_panel_label="@epic",
            initial_clan=("beta", "generation"),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#agent-cleanup-clan-list", OptionList)
        assert "clan:beta" in str(
            option_list.get_option_at_index(option_list.highlighted or 0).id
        )

        await pilot.press("l")
        await pilot.pause()
        assert option_list.option_count == 3
        assert modal._expanded == {("beta", "generation")}

        await pilot.press("j")
        await pilot.press("h")
        await pilot.pause()
        assert option_list.option_count == 2
        assert modal._expanded == set()
        assert "clan:beta" in str(
            option_list.get_option_at_index(option_list.highlighted or 0).id
        )


async def test_clan_modal_member_toggle_updates_partial_and_all_glyphs() -> None:
    one = _member("alpha.1", "alpha-1", clan="alpha")
    two = _member("alpha.2", "alpha-2", clan="alpha", status="DONE", pid=None)
    clans, targets = _project(one, two)

    async with _TestApp().run_test() as pilot:
        modal = AgentCleanupClanModal(
            clans=clans,
            targets=targets,
            focused_panel_label="@epic",
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        option_list = modal.query_one("#agent-cleanup-clan-list", OptionList)

        await pilot.press("l", "j", "space")
        await pilot.pause()
        assert modal._selected_members == {one.identity}
        clan_prompt = option_list.get_option_at_index(0).prompt
        assert isinstance(clan_prompt, Text)
        assert clan_prompt.plain.startswith("◐ alpha")

        await pilot.press("j", "space")
        await pilot.pause()
        assert modal._selected_members == {one.identity, two.identity}
        clan_prompt = option_list.get_option_at_index(0).prompt
        assert isinstance(clan_prompt, Text)
        assert clan_prompt.plain.startswith("● alpha")

        await pilot.press("k", "k", "space")
        await pilot.pause()
        assert modal._selected_clans == {("alpha", "generation")}
        assert modal._selected_members == set()


async def test_clan_modal_toggle_all_and_confirm_returns_whole_clans(
    monkeypatch: Any,
) -> None:
    alpha = _member("alpha.1", "alpha-1", clan="alpha")
    beta = _member("beta.1", "beta-1", clan="beta", status="DONE", pid=None)
    clans, targets = _project(alpha, beta)

    async with _TestApp().run_test() as pilot:
        modal = AgentCleanupClanModal(
            clans=clans,
            targets=targets,
            focused_panel_label="@epic",
        )
        dismissed: list[AgentCleanupClanResult | None] = []
        monkeypatch.setattr(modal, "dismiss", dismissed.append)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("a", "enter")
        await pilot.pause()

        assert dismissed == [
            AgentCleanupClanResult(
                clans=(("alpha", "generation"), ("beta", "generation")),
                identities=(),
            )
        ]


async def test_clan_modal_enter_without_selection_returns_highlighted_clan(
    monkeypatch: Any,
) -> None:
    alpha = _member("alpha.1", "alpha-1", clan="alpha")
    beta = _member("beta.1", "beta-1", clan="beta")
    clans, targets = _project(alpha, beta)

    async with _TestApp().run_test() as pilot:
        modal = AgentCleanupClanModal(
            clans=clans,
            targets=targets,
            focused_panel_label="@epic",
            initial_clan=("beta", "generation"),
        )
        dismissed: list[AgentCleanupClanResult | None] = []
        monkeypatch.setattr(modal, "dismiss", dismissed.append)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert dismissed == [
            AgentCleanupClanResult(clans=(("beta", "generation"),), identities=())
        ]
