"""ACE TUI PNG visual snapshots for Agents-tab panel interactions."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.text import Text
from textual.css.scalar import Unit
from textual.widgets import Input

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._panel_fold_intent import (
    effective_panel_collapses,
)
from sase.ace.tui.modals import ConfirmDismissAllModal
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import (
    AgentDetail,
    AgentInfoPanel,
    AgentList,
    HintInputBar,
    KeybindingFooter,
)
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
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
            tribe="visual",
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
            tribe="chop",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-collapse-secondary-with-another-wide-row",
            project_file=project_file,
            status="WAITING",
            start_time=started,
            raw_suffix="20260715-100200-chop-secondary",
            agent_name="visual.collapse.secondary.with.another.wide.row",
            tribe="chop",
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
            tribe="keep",
        ),
    ]


def _panel_auto_expand_agents() -> list[Agent]:
    """Collapsed ``@chop`` panel with an unread target after its first row."""
    agents = _panel_collapse_agents()
    target = agents[2]
    target.status = "DONE"
    target.stop_time = datetime(2026, 7, 15, 10, 5, 0)
    return agents


def _sole_default_panel_agent() -> Agent:
    """One top-level row in the split ``@default`` panel."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-sole-default-panel",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 20, 12, 0, 0),
        raw_suffix="20260720-120000-sole-default",
        agent_name="visual.sole.default.panel",
        llm_provider="codex",
        model="gpt-5",
    )


def _overflowing_panel_agents() -> list[Agent]:
    """Large no-tribe panel followed by two compact tribe panels."""
    project_file = "/workspace/sase/visual_project.sase"
    started = datetime(2026, 7, 18, 15, 0, 0)
    rows = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-overflow-agent-{idx:02d}",
            project_file=project_file,
            status="RUNNING",
            start_time=started,
            raw_suffix=f"20260718-15{idx:02d}00-overflow-{idx:02d}",
            agent_name=f"overflow-agent-{idx:02d}",
        )
        for idx in range(28)
    ]
    rows.extend(
        [
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name="visual-compact-apple",
                project_file=project_file,
                status="WAITING",
                start_time=started,
                raw_suffix="20260718-160000-compact-apple",
                agent_name="compact-apple",
                tribe="apple",
            ),
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name="visual-compact-banana",
                project_file=project_file,
                status="DONE",
                start_time=started,
                stop_time=datetime(2026, 7, 18, 16, 5, 0),
                raw_suffix="20260718-160100-compact-banana",
                agent_name="compact-banana",
                tribe="banana",
            ),
        ]
    )
    return rows


def _assert_collapsed_panel_summary(page: AcePage) -> None:
    """Assert the right pane represents ``@chop``, not its hidden first row."""
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    prompt = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
    info = page.app.query_one("#agent-info-panel", AgentInfoPanel)

    assert detail._current_agent is None
    assert detail._current_tribe_identity == ("panel", "chop")
    assert page.app._get_selected_agent() is None
    snapshot = page.app._focused_tribe_summary()
    assert snapshot is not None
    assert snapshot.label == "† @chop"
    rendered = prompt.content.plain
    assert "TRIBE\n" in rendered
    assert "Name: † @chop" in rendered
    assert "Panel:" not in rendered
    assert "Fold: 1/4" in rendered
    assert "[R1 W1]" in rendered
    assert "TRIBE MEMBERS · 2" in rendered
    assert "visual.collapse.primary.with.a.deliberately.wide.row" in rendered
    assert info._view_mode == "tribe"
    assert "[view: tribe]" in info._build_display_text().plain
    svg = page.export_svg(title="ACE collapsed summary assertion")
    assert "Name:" in svg
    assert "ChangeSpec:" not in svg


async def test_agents_sole_selected_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _sole_default_panel_agent()
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert page.app._panel_group.panel_keys == [None]
        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        assert footer._last_layout_inputs is not None
        row_bindings, _mode_label = footer._last_layout_inputs
        assert ("h", "parent tribe") in row_bindings

        await page.press("h")
        await page.wait_for(
            lambda _screen: (
                (focus := page.app._resolve_focused_panel()) is not None
                and not focus.collapsed
            )
        )
        await wait_for_visual_idle(page)

        panel = page.app.query_one("#agent-list-panel", AgentList)
        assert Text.from_markup(panel.border_title).plain.startswith("❖ ⌂ @default")
        assert footer._last_layout_inputs is not None
        selected_bindings, _mode_label = footer._last_layout_inputs
        assert ("h", "collapse panel") in selected_bindings
        assert ("l", "enter panel") in selected_bindings
        assert ("Esc", "enter panel") in selected_bindings
        assert ("H", "collapse group") in selected_bindings
        assert ("Z", "only panel") in selected_bindings
        assert not any(label.startswith("parent ") for _key, label in selected_bindings)

        ace_png_visual.assert_page_png(
            page,
            "agents_sole_selected_panel_120x40",
            title="ACE agents sole selected panel",
        )

        await page.press("h")
        await page.wait_for(
            lambda _screen: (
                (focus := page.app._resolve_focused_panel()) is not None
                and focus.collapsed
            )
        )
        assert page.app._collapsed_panel_keys == {None}

        await page.press("l")
        await page.wait_for(
            lambda _screen: (
                (focus := page.app._resolve_focused_panel()) is not None
                and not focus.collapsed
            )
        )
        await page.press("l")
        await page.wait_for(lambda _screen: page.app._resolve_focused_panel() is None)
        assert page.app.current_idx == 0


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
        assert "chop" not in page.app._collapsed_panel_keys
        assert "chop" not in page.app._expanded_panel_keys
        await page.press("J")
        await page.press("J")
        assert page.app._panel_group.focused_key == "chop"
        panel_focus = page.app._resolve_focused_panel()
        assert panel_focus is not None and panel_focus.collapsed
        await wait_for_svg_contains(page, "▸ ")
        await wait_for_visual_idle(page)

        assert page.app._panel_group.panel_keys[-1] == "chop"
        collapsed_widget = page.app.query_one("#agent-list-panel-2")
        assert collapsed_widget.option_count == 0
        assert collapsed_widget.styles.height is not None
        assert collapsed_widget.styles.height.value == 2.0
        assert (
            Text.from_markup(collapsed_widget.border_title).plain
            == "▸ † @chop · 2 [R1 W1]"
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
        collapsed_jump_hint = page.app._entry_jump_panel_to_hint[("panel", "chop")]
        await page.wait_for(
            lambda _screen: Text.from_markup(
                collapsed_widget.border_title
            ).plain.startswith(f"[{collapsed_jump_hint}] ▸ ")
        )
        await wait_for_visual_idle(page)
        assert page.app._entry_jump_mode_active is True
        assert collapsed_widget._requested_width == normal_width + 4
        assert (
            Text.from_markup(collapsed_widget.border_title).plain
            == f"[{collapsed_jump_hint}] ▸ † @chop · 2 [R1 W1]"
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

        await page.press("L")
        await page.wait_for(lambda _screen: page.app._panel_fold_hint_mode_active)
        hint_bar = page.app.query_one("#hint-input-bar", HintInputBar)
        hint_input = hint_bar.query_one("#hint-input", Input)
        panel_titles = [
            Text.from_markup(widget.border_title).plain
            for widget in container.query("AgentList")
        ]
        fold_hints = page.app._panel_fold_target_to_hint
        for panel_idx, panel_key in enumerate(page.app._panel_group.panel_keys):
            hint = fold_hints[("panel", panel_key)]
            collapsed_marker = (
                "▸ "
                if panel_key
                in effective_panel_collapses(page.app, page.app._panel_group.panel_keys)
                else ""
            )
            assert panel_titles[panel_idx].startswith(f"[{hint}] {collapsed_marker}")
        await wait_for_svg_contains(page, "Folds:")
        await wait_for_visual_idle(page)
        _assert_collapsed_panel_summary(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_panel_fold_selection_120x40",
            title="ACE agents unified fold hints",
        )

        hint_input.value = " ".join(
            str(fold_hints[target]) for target in (("panel", None), ("panel", "chop"))
        )
        await page.press("enter")
        await page.wait_for(lambda _screen: not page.app._panel_fold_hint_mode_active)
        await wait_for_visual_idle(page)

        assert page.app._collapsed_panel_keys == {None}
        assert page.app._panel_group.panel_keys == ["chop", "keep", None]
        assert page.app._panel_group.focused_key == "chop"
        assert page.app._agents[page.app.current_idx].tribe == "chop"

        # A collapsed panel has no selectable rows, so mouse focus itself must
        # move whole-panel focus and route the detail pane to its summary.
        await page.click("#agent-list-panel-2")
        await page.wait_for(lambda _screen: page.app._panel_group.focused_key is None)
        await wait_for_visual_idle(page)
        prompt = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        assert page.app._get_selected_agent() is None
        snapshot = page.app._focused_tribe_summary()
        assert snapshot is not None
        assert snapshot.label == "⌂ @default"
        assert "Name: ⌂ @default" in prompt.content.plain


async def test_agents_overflowing_panel_uses_full_height_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _overflowing_panel_agents()
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", len(rows))
        await wait_for_visual_idle(page)

        container = page.app.query_one("#agent-list-container")
        widgets = list(container.query(AgentList).results(AgentList))
        assert page.app._panel_group.panel_keys == [None, "apple", "banana"]
        assert len(widgets) == 3
        no_tribe, apple, banana = widgets

        assert no_tribe.styles.height.unit is Unit.FRACTION
        assert no_tribe.option_count + 2 > no_tribe.region.height
        for compact in (apple, banana):
            assert compact.styles.height.unit is Unit.CELLS
            assert compact.styles.height.value == compact.option_count + 2
        assert banana.region.bottom == container.content_region.bottom

        ace_png_visual.assert_page_png(
            page,
            "agents_overflowing_panel_full_height_120x40",
            title="ACE agents overflowing panel full height",
        )


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

        await page.press("J")
        await page.press("J")
        assert page.app._panel_group.focused_key == "chop"
        await page.press("l")
        await page.wait_for(
            lambda _screen: (
                not effective_panel_collapses(
                    page.app, page.app._panel_group.panel_keys
                )
            )
        )
        await page.press("l")
        await page.press("j")
        assert page.app._agents[page.app.current_idx].identity == target.identity
        await page.press("h")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )
        page.app._unread_completed_agent_ids.add(target.identity)

        await page.press("comma")
        await page.press("j")
        await page.wait_for(lambda _screen: page.app._resolve_focused_panel() is None)

        assert page.app._agents[page.app.current_idx].identity == target.identity
        assert target.identity not in page.app._unread_completed_agent_ids
        focused_idx = page.app._panel_group.focused_idx
        widget_id = (
            "#agent-list-panel"
            if focused_idx == 0
            else f"#agent-list-panel-{focused_idx}"
        )
        target_widget = page.app.query_one(widget_id, AgentList)
        assert "❖" not in Text.from_markup(target_widget.border_title).plain
        assert target_widget.highlighted is not None

        assert page.app._restore_agents_jump_anchor() is True
        page.app._unread_completed_agent_ids.add(target.identity)
        await page.press("h")
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
