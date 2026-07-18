"""ACE TUI PNG visual snapshots for Agents-tab list interactions."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.text import Text
from textual.widgets import Input

from sase.ace.testing import AcePage
from sase.ace.tui.modals import ConfirmDismissAllModal
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import (
    AgentDetail,
    AgentInfoPanel,
    AgentPanelSummary,
    HintInputBar,
    KeybindingFooter,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    hood_neighbor_agents,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _done_agents() -> list[Agent]:
    """Three completed agents in the ``Done`` bucket.

    Used by the unread-highlight snapshot — all three rows are then
    marked unread post-startup so the Agents-tab info-panel header
    renders a non-zero ``N unread`` count that exercises the yellow
    background style.
    """
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            stop_time=datetime(2026, 5, 9, 10, 7, 30),
            raw_suffix="20260509-100000-plan",
            agent_name="planner",
            llm_provider="codex",
            model="gpt-5",
            response_path="/workspace/sase/artifacts/visual-plan/response.md",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-code",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 8, 0),
            stop_time=datetime(2026, 5, 9, 10, 9, 5),
            raw_suffix="20260509-100800-code",
            agent_name="coder",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-review",
            project_file="/workspace/sase/visual_project.sase",
            status="PLAN DONE",
            start_time=datetime(2026, 5, 9, 10, 10, 0),
            stop_time=datetime(2026, 5, 9, 10, 12, 0),
            raw_suffix="20260509-101000-review",
            agent_name="reviewer",
            tag="visual",
        ),
    ]


def _panel_collapse_agents() -> list[Agent]:
    """Three panels where ``@chop`` owns the widest rendered rows."""
    project_file = "/workspace/sase/visual_project.sase"
    started = datetime(2026, 7, 15, 10, 0, 0)
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-home",
            project_file=project_file,
            status="RUNNING",
            start_time=started,
            raw_suffix="20260715-100000-home",
            agent_name="home",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-collapse-primary-with-a-deliberately-wide-row",
            project_file=project_file,
            status="RUNNING",
            start_time=started,
            raw_suffix="20260715-100100-chop-primary",
            agent_name="visual.collapse.primary.with.a.deliberately.wide.row",
            tag="chop",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-collapse-secondary-with-another-wide-row",
            project_file=project_file,
            status="WAITING",
            start_time=started,
            raw_suffix="20260715-100200-chop-secondary",
            agent_name="visual.collapse.secondary.with.another.wide.row",
            tag="chop",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-keep",
            project_file=project_file,
            status="DONE",
            start_time=started,
            stop_time=datetime(2026, 7, 15, 10, 4, 0),
            raw_suffix="20260715-100300-keep",
            agent_name="keep",
            tag="keep",
        ),
    ]


def _panel_auto_expand_agents() -> list[Agent]:
    """Collapsed ``@chop`` panel with an unread target after its first row."""
    agents = _panel_collapse_agents()
    target = agents[2]
    target.status = "DONE"
    target.stop_time = datetime(2026, 7, 15, 10, 5, 0)
    return agents


def _assert_collapsed_panel_summary(page: AcePage) -> None:
    """Assert the right pane represents ``@chop``, not its hidden first row."""
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    summary = page.app.query_one("#agent-panel-summary", AgentPanelSummary)
    info = page.app.query_one("#agent-info-panel", AgentInfoPanel)

    assert detail.is_panel_summary_visible()
    assert detail._current_agent is None
    assert page.app._get_selected_agent() is None
    assert summary.snapshot is not None
    assert summary.snapshot.label == "@chop"
    rendered = summary.render().plain
    assert "COLLAPSED AGENT PANEL" in rendered
    assert "@chop  COLLAPSED" in rendered
    assert "[R1 W1]" in rendered
    assert "visual-collapse-primary-with-a-deliberately-wide-row" in rendered
    assert "visual-collapse-secondary-with-another-wide-row" in rendered
    assert info._view_mode == "summary"
    assert "[view: summary]" in info._build_display_text().plain
    svg = page.export_svg(title="ACE collapsed summary assertion")
    assert "Name:" not in svg
    assert "ChangeSpec:" not in svg


async def test_agents_collapsed_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_panel_collapse_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        container = page.app.query_one("#agent-list-container")
        expanded_width = container.size.width
        await page.press("J")
        assert page.app._panel_group.focused_key == "chop"
        await page.press("H")
        await page.wait_for(lambda _screen: "chop" in page.app._collapsed_panel_keys)
        await wait_for_svg_contains(page, "▸ ")
        await wait_for_visual_idle(page)

        assert page.app._panel_group.panel_keys[-1] == "chop"
        collapsed_widget = page.app.query_one("#agent-list-panel-2")
        assert collapsed_widget.option_count == 0
        assert collapsed_widget.styles.height is not None
        assert collapsed_widget.styles.height.value == 2.0
        requested_widths = [
            widget._requested_width for widget in container.query("AgentList")
        ]
        assert container.size.width < expanded_width, requested_widths
        assert (
            Text.from_markup(collapsed_widget.border_title).plain
            == "▸ @chop · 2 [R1 W1]"
        )
        _assert_collapsed_panel_summary(page)
        assert_page_svg_contains(page, "▸ ")
        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        assert footer._last_layout_inputs is not None
        footer_bindings, _mode_label = footer._last_layout_inputs
        assert ("x", "kill/dismiss panel") in footer_bindings

        ace_png_visual.assert_page_png(
            page,
            "agents_collapsed_panel_120x40",
            title="ACE agents collapsed panel",
        )

        await page.press("x")
        await page.expect_modal("ConfirmDismissAllModal")
        modal = page.app.screen
        assert isinstance(modal, ConfirmDismissAllModal)
        assert "Panel: @chop (2 agents)" in modal.agent_description
        assert "visual-collapse-primary" in modal.agent_description
        assert "visual-collapse-secondary" in modal.agent_description
        assert "visual-home" not in modal.agent_description
        assert "visual-keep" not in modal.agent_description
        await page.press("escape")
        await page.expect_no_modal()

        normal_width = collapsed_widget._requested_width
        await page.press("apostrophe")
        await page.wait_for(
            lambda _screen: Text.from_markup(
                collapsed_widget.border_title
            ).plain.startswith("[3] ▸ ")
        )
        await wait_for_visual_idle(page)
        assert page.app._entry_jump_mode_active is True
        assert collapsed_widget._requested_width == normal_width + 4
        assert (
            Text.from_markup(collapsed_widget.border_title).plain
            == "[3] ▸ @chop · 2 [R1 W1]"
        )
        _assert_collapsed_panel_summary(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_collapsed_panel_jump_hints_120x40",
            title="ACE agents collapsed panel jump hints",
        )

        await page.press("escape")
        await page.wait_for(
            lambda _screen: Text.from_markup(
                collapsed_widget.border_title
            ).plain.startswith("▸ ")
        )
        assert collapsed_widget._requested_width == normal_width

        await page.press("comma")
        await page.press("H")
        await page.wait_for(lambda _screen: page.app._panel_fold_hint_mode_active)
        hint_bar = page.app.query_one("#hint-input-bar", HintInputBar)
        hint_input = hint_bar.query_one("#hint-input", Input)
        panel_titles = [
            Text.from_markup(widget.border_title).plain
            for widget in container.query("AgentList")
        ]
        assert panel_titles[0].startswith("[1] ")
        assert panel_titles[1].startswith("[2] ")
        assert panel_titles[2].startswith("[3] ▸ ")
        await wait_for_svg_contains(page, "Panels:")
        await wait_for_visual_idle(page)
        _assert_collapsed_panel_summary(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_panel_fold_selection_120x40",
            title="ACE agents panel fold selection",
        )

        hint_input.value = "1 3"
        await page.press("enter")
        await page.wait_for(lambda _screen: not page.app._panel_fold_hint_mode_active)
        await wait_for_visual_idle(page)

        assert page.app._collapsed_panel_keys == {None}
        assert page.app._panel_group.panel_keys == ["chop", "keep", None]
        assert page.app._panel_group.focused_key == "chop"
        assert page.app._agents[page.app.current_idx].tag == "chop"

        # A collapsed panel has no selectable rows, so mouse focus itself must
        # move whole-panel focus and route the detail pane to its summary.
        await page.click("#agent-list-panel-2")
        await page.wait_for(lambda _screen: page.app._panel_group.focused_key is None)
        await wait_for_visual_idle(page)
        summary = page.app.query_one("#agent-panel-summary", AgentPanelSummary)
        assert page.app._get_selected_agent() is None
        assert summary.snapshot is not None
        assert summary.snapshot.label == "(untagged)"


async def test_agents_unread_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done = _done_agents()
    patch_startup_loaders(monkeypatch, agents=done)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        identities = {agent.identity for agent in done}
        page.app._unread_completed_agent_ids = set(identities)
        page.app._manual_unread_agent_ids = set(identities)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        page.app._update_agents_info_panel()
        from sase.ace.tui.widgets import AgentInfoPanel

        panel = page.app.query_one("#agent-info-panel", AgentInfoPanel)
        await wait_for_state(
            page,
            lambda: panel._unread_count == 3,
            description="three unread completed agents",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_unread_highlight_120x40",
            title="ACE agents unread highlight",
        )


async def test_agents_leader_jump_auto_expands_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _panel_auto_expand_agents()
    target = agents[2]
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        page.app._unread_completed_agent_ids.add(target.identity)

        await page.press("J")
        assert page.app._panel_group.focused_key == "chop"
        await page.press("H")
        await page.wait_for(lambda _screen: "chop" in page.app._collapsed_panel_keys)
        assert page.app._panel_group.panel_keys == [None, "keep", "chop"]

        await page.press("comma")
        await page.press("j")
        await page.wait_for(
            lambda _screen: "chop" not in page.app._collapsed_panel_keys
        )
        await wait_for_visual_idle(page)

        assert page.app._panel_group.panel_keys == [None, "chop", "keep"]
        assert page.app._panel_group.focused_key == "chop"
        assert page.app.current_idx == 2
        assert page.app._agents[page.app.current_idx].identity == target.identity
        assert target.identity not in page.app._unread_completed_agent_ids
        target_widget = page.app.query_one("#agent-list-panel-1")
        assert target_widget.highlighted is not None

        ace_png_visual.assert_page_png(
            page,
            "agents_leader_jump_auto_expanded_panel_120x40",
            title="ACE agents leader jump auto-expanded panel",
        )


async def test_agents_neighbor_badge_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=hood_neighbor_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_svg_contains(page, "neighbors: ")
        await wait_for_visual_idle(page)
        neighbor_index = page.app._agent_neighbor_index()
        assert neighbor_index.neighbor_count(page.app.current_idx) == 2
        assert_page_svg_contains(page, "neighbors: ")

        ace_png_visual.assert_page_png(
            page,
            "agents_neighbor_badge_120x40",
            title="ACE agents neighbor badge",
        )


async def test_agent_neighbor_modal_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=hood_neighbor_agents())

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentNeighborModal")
        await wait_for_svg_contains(page, "Neighbors of visual.code.plan")
        await wait_for_visual_idle(page)
        modal = page.app.screen_stack[-1]
        assert modal.__class__.__name__ == "AgentNeighborModal"
        choices = vars(modal)["_choices"]
        assert [choice.global_idx for choice in choices] == [1, 2]
        assert_page_svg_contains(page, "Neighbors of visual.code.plan")
        assert_page_svg_contains(page, "visual.code.implementation")

        ace_png_visual.assert_page_png(
            page,
            "agent_neighbor_modal_60x30",
            title="ACE agent neighbor modal narrow",
        )


async def test_agent_neighbor_modal_dismissed_descendant_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parent",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 23, 13, 0, 0),
        raw_suffix="20260523-130000-parent",
        agent_name="visual.root",
        tag="api",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-child",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 13, 8, 0),
        stop_time=datetime(2026, 5, 23, 13, 12, 30),
        raw_suffix="20260523-130800-child",
        agent_name="visual.root.visible",
        tag="api",
    )
    dismissed = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-dismissed",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 13, 16, 0),
        stop_time=datetime(2026, 5, 23, 13, 17, 5),
        raw_suffix="20260523-131600-dismissed",
        agent_name="visual.root.dismissed",
        tag="api",
    )
    patch_startup_loaders(monkeypatch, agents=[parent, child])

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 2)
        page.app._dismissed_agent_objects = [dismissed]
        page.app._dismissed_agents = {dismissed.identity}
        page.app._dismiss_revive_epoch += 1
        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentNeighborModal")
        page.app._refresh_agent_footer_bindings_only()
        # The direct private-state mutation above bypasses the normal action
        # path that refreshes the footer. Repaint it explicitly, then keep the
        # rendered-count poll as a cheap guard before taking the snapshot.
        await wait_for_svg_contains(page, "neighbors (2)")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Descendants")
        assert_page_svg_contains(page, "visual.root.dismissed")
        assert_page_svg_contains(page, "dismissed")

        ace_png_visual.assert_page_png(
            page,
            "agent_neighbor_modal_descendants_dismissed_60x30",
            title="ACE agent neighbor modal dismissed descendant",
        )
