"""Grouping-fold repaints on the incremental Agents display path.

Pressing ``H`` to fold a grouping banner updates fold state at once, but the
panel used to keep drawing the group expanded: a fold-only change leaves the
agent roster identical, so the incremental path found no roster diff and never
rebuilt the panel. These tests pin the fix: every panel whose rows were built
under different grouping-fold state than its registry holds is rebuilt through
the per-panel lane, while unchanged refreshes stay on the cheap patch path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.actions.agents._display_helpers import panel_widget_id_for_key
from sase.ace.tui.actions.agents._fold_scope import panel_fold_registry
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode, enumerate_group_keys
from sase.ace.tui.models.group_fold import GroupFoldRegistry, group_fold_snapshot
from sase.ace.tui.widgets.agent_list import AgentList

from ._agent_display_diff_helpers import (
    _DisplayDiffApp,
    _agent,
    _apply_roster,
    _display_costs,
    _panel_attributions,
    _panel_id,
    _widget_sel,
)

BY_STATUS = GroupingMode.BY_STATUS
STANDARD = GroupingMode.STANDARD


def _epic_agents() -> list[Agent]:
    return [
        _agent("alpha", tribe="epic", suffix="a1", status="RUNNING"),
        _agent("beta", tribe="epic", suffix="b1", status="DONE"),
    ]


def _by_status_epic_app(agents: list[Agent], monkeypatch: Any) -> _DisplayDiffApp:
    app = _DisplayDiffApp(agents, monkeypatch)
    app._grouping_mode = BY_STATUS
    app._refresh_panel_widgets(jump_hints=None)
    app._agents_refresh_trace_records.clear()
    for widget in app._container.children:
        widget.update_list_calls = 0  # type: ignore[attr-defined]
    return app


def _epic_widget(app: _DisplayDiffApp) -> AgentList:
    return app._widgets[_widget_sel("epic")]


def test_collapse_repaints_fold_stale_panel_without_full_rebuild(
    monkeypatch: Any,
) -> None:
    agents = _epic_agents()
    app = _by_status_epic_app(agents, monkeypatch)
    widget = _epic_widget(app)
    options_before = widget.option_count

    assert panel_fold_registry(app, "epic").collapse(("Done",)) is True
    _apply_roster(app, agents, agents)

    assert app.full_rebuilds == 0
    assert widget.update_list_calls == 1  # type: ignore[attr-defined]
    assert _panel_attributions(app) == [(_panel_id("epic"), "group_fold_change")]
    assert "display_panel_rebuild" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)
    # The Done banner stays, collapsed, with no agent rows for its members.
    assert ("Done",) in widget._banner_row_by_key
    banner_row = widget._banner_row_by_key[("Done",)]
    assert widget._banner_at_row[banner_row].is_collapsed is True
    done_local_idx = 1
    assert done_local_idx not in widget._row_by_agent_idx
    assert widget.option_count == options_before - 1


def test_expand_repaints_and_restores_rows(monkeypatch: Any) -> None:
    agents = _epic_agents()
    app = _by_status_epic_app(agents, monkeypatch)
    widget = _epic_widget(app)
    options_before = widget.option_count

    panel_fold_registry(app, "epic").collapse(("Done",))
    _apply_roster(app, agents, agents)
    assert widget.option_count == options_before - 1

    assert panel_fold_registry(app, "epic").expand(("Done",)) is True
    _apply_roster(app, agents, agents)

    assert app.full_rebuilds == 0
    assert widget.update_list_calls == 2  # type: ignore[attr-defined]
    assert _panel_attributions(app) == [
        (_panel_id("epic"), "group_fold_change"),
        (_panel_id("epic"), "group_fold_change"),
    ]
    assert widget.option_count == options_before
    assert 1 in widget._row_by_agent_idx


def test_unchanged_fold_state_stays_on_patch_path(monkeypatch: Any) -> None:
    agents = _epic_agents()
    app = _by_status_epic_app(agents, monkeypatch)
    widget = _epic_widget(app)

    panel_fold_registry(app, "epic").collapse(("Done",))
    _apply_roster(app, agents, agents)
    assert widget.update_list_calls == 1  # type: ignore[attr-defined]

    app._agents_refresh_trace_records.clear()
    _apply_roster(app, agents, agents)

    assert widget.update_list_calls == 1  # type: ignore[attr-defined]
    assert app.full_rebuilds == 0
    assert _panel_attributions(app) == []


def test_sibling_panel_without_fold_change_is_not_repainted(
    monkeypatch: Any,
) -> None:
    epic_running = _agent("alpha", tribe="epic", suffix="a1", status="RUNNING")
    epic_done = _agent("beta", tribe="epic", suffix="b1", status="DONE")
    review = _agent("gamma", tribe="review", suffix="c1", status="RUNNING")
    agents = [epic_running, epic_done, review]
    app = _by_status_epic_app(agents, monkeypatch)
    epic_widget = app._widgets[_widget_sel("epic")]
    review_widget = app._widgets[_widget_sel("review")]
    review_rows = review_widget.option_count

    panel_fold_registry(app, "epic").collapse(("Done",))
    _apply_roster(app, agents, agents)

    assert app.full_rebuilds == 0
    assert epic_widget.update_list_calls == 1  # type: ignore[attr-defined]
    assert review_widget.update_list_calls == 0  # type: ignore[attr-defined]
    assert review_widget.option_count == review_rows
    assert _panel_attributions(app) == [(_panel_id("epic"), "group_fold_change")]


def test_whole_panel_collapsed_widget_is_ignored(monkeypatch: Any) -> None:
    agents = [
        _agent("alpha", tribe="epic", suffix="a1", status="RUNNING"),
        _agent("beta", tribe="epic", suffix="b1", status="DONE"),
        _agent("gamma", tribe="review", suffix="c1", status="RUNNING"),
    ]
    app = _DisplayDiffApp(agents, monkeypatch, collapsed_panel_keys={"epic"})
    app._grouping_mode = BY_STATUS
    app._refresh_panel_widgets(jump_hints=None)
    app._agents_refresh_trace_records.clear()
    for widget in app._container.children:
        widget.update_list_calls = 0  # type: ignore[attr-defined]

    panel_fold_registry(app, "epic").collapse(("Done",))
    _apply_roster(app, agents, agents)

    assert app.full_rebuilds == 0
    assert _panel_attributions(app) == []
    for widget in app._container.children:
        assert widget.update_list_calls == 0  # type: ignore[attr-defined]


def test_standard_mode_project_banner_repaint(monkeypatch: Any) -> None:
    agents = [
        _agent("coder.claude", tribe="epic", suffix="a1"),
        _agent("coder.codex", tribe="epic", suffix="a2"),
    ]
    app = _DisplayDiffApp(agents, monkeypatch)
    app._agents_refresh_trace_records.clear()
    for widget in app._container.children:
        widget.update_list_calls = 0  # type: ignore[attr-defined]
    widget = _epic_widget(app)
    options_before = widget.option_count

    panel_agents = list(widget._agents)
    keys = enumerate_group_keys(panel_agents, mode=STANDARD)
    assert keys, "expected at least one STANDARD banner key"
    target = keys[0]
    assert panel_fold_registry(app, "epic").collapse(target) is True
    _apply_roster(app, agents, agents)

    assert app.full_rebuilds == 0
    assert widget.update_list_calls == 1  # type: ignore[attr-defined]
    assert _panel_attributions(app) == [(_panel_id("epic"), "group_fold_change")]
    assert widget.option_count < options_before
    assert target in widget._banner_row_by_key


def test_version_bump_without_net_change_does_not_repaint(
    monkeypatch: Any,
) -> None:
    agents = _epic_agents()
    app = _by_status_epic_app(agents, monkeypatch)
    widget = _epic_widget(app)

    registry = panel_fold_registry(app, "epic")
    assert registry.collapse(("Done",)) is True
    assert registry.expand(("Done",)) is True
    assert registry.version > 0
    _apply_roster(app, agents, agents)

    assert widget.update_list_calls == 0  # type: ignore[attr-defined]
    assert app.full_rebuilds == 0
    assert _panel_attributions(app) == []


def test_group_fold_snapshot_helper() -> None:
    assert group_fold_snapshot(None) == frozenset()
    registry = GroupFoldRegistry()
    registry.collapse(("Done",))
    assert group_fold_snapshot(registry) == frozenset({("Done",)})

    class _CollapsedAttr:
        collapsed = {("Running",)}

    assert group_fold_snapshot(_CollapsedAttr()) == frozenset({("Running",)})

    class _NoState:
        pass

    assert group_fold_snapshot(_NoState()) == frozenset()


def _stub_widget(monkeypatch: pytest.MonkeyPatch) -> AgentList:
    widget = AgentList()
    monkeypatch.setattr(widget, "post_message", lambda _msg: None)
    return widget


def _status_agents() -> list[Agent]:
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="demo",
            project_file="/repo/proj.sase",
            status="RUNNING",
            start_time=datetime(2026, 4, 25, 12, 0, 0),
            agent_name=f"node-{i:02d}",
            raw_suffix=f"202604251200{i:02d}",
        )
        for i in range(3)
    ]


def test_update_list_records_rendered_group_folds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = _stub_widget(monkeypatch)
    agents = _status_agents()
    assert widget._rendered_group_folds is None
    registry = GroupFoldRegistry()
    registry.collapse(("Running",))
    widget.update_list(agents, 0, grouping_mode=BY_STATUS, fold_registry=registry)
    assert widget._rendered_group_folds == registry.snapshot()


def test_try_insert_rows_records_snapshot_only_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = _stub_widget(monkeypatch)
    base = _status_agents()
    registry = GroupFoldRegistry()
    # Collapse a bucket with no members here: the rendered tree is unchanged,
    # so a later insert can still take the in-place path.
    registry.collapse(("Done",))
    widget.update_list(base, 0, grouping_mode=BY_STATUS, fold_registry=registry)
    assert widget._rendered_group_folds == frozenset({("Done",)})

    extra = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/repo/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 3, 0),
        agent_name="node-03",
        raw_suffix="20260425120300",
    )
    assert (
        widget.try_insert_rows(
            [*base, extra], 0, grouping_mode=BY_STATUS, fold_registry=registry
        )
        is True
    )
    assert widget._rendered_group_folds == frozenset({("Done",)})

    # A declined insert (grouping-mode mismatch) leaves the snapshot alone.
    assert (
        widget.try_insert_rows(
            [*widget._agents, extra],
            0,
            grouping_mode=STANDARD,
            fold_registry=GroupFoldRegistry(),
        )
        is False
    )
    assert widget._rendered_group_folds == frozenset({("Done",)})


def test_render_collapsed_resets_rendered_group_folds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = _stub_widget(monkeypatch)
    registry = GroupFoldRegistry()
    registry.collapse(("Running",))
    widget.update_list(
        _status_agents(), 0, grouping_mode=BY_STATUS, fold_registry=registry
    )
    assert widget._rendered_group_folds == frozenset({("Running",)})

    widget.render_collapsed(grouping_mode=BY_STATUS)
    assert widget._rendered_group_folds is None


def test_panel_widget_id_for_epic_key() -> None:
    assert panel_widget_id_for_key("epic") == "agent-list-panel-epic"


def _mounted_fold_agents() -> list[Agent]:
    started = datetime(2026, 7, 22, 7, 0, 0)
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"foldrepaint-{name}",
            project_file="/repo/foldrepaint/foldrepaint.sase",
            status=status,
            start_time=started.replace(minute=minute),
            agent_name=f"foldrepaint-{name}",
            raw_suffix=f"20260722070{minute}00",
            tribe="epic",
        )
        for minute, (name, status) in enumerate(
            [
                ("alpha", "RUNNING"),
                ("beta", "RUNNING"),
                ("gamma", "DONE"),
                ("delta", "DONE"),
            ]
        )
    ]


@pytest.mark.asyncio
async def test_mounted_h_collapses_status_group_without_l(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pressing ``H`` on a BY_STATUS row repaints the fold with no ``L``."""

    from sase.ace.testing import AcePage
    from sase.ace.tui.models.agent_groups import GroupingMode
    from tests.ace.tui.visual._ace_png_snapshot_helpers import (
        patches,
        patch_startup_loaders,
        wait_for_startup,
        wait_for_visual_idle,
    )

    patch_startup_loaders(monkeypatch, agents=_mounted_fold_agents())

    async with AcePage(query='"foldrepaint"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.press("o", "s")
        assert page.app._grouping_mode is GroupingMode.BY_STATUS
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        done_idx = next(
            i for i, agent in enumerate(page.app._agents) if agent.status == "DONE"
        )
        page.app.current_idx = done_idx
        page.app._current_group_key = None

        widget = page.query_one_widget("#agent-list-panel-epic", AgentList)
        options_before = widget.option_count
        assert options_before > 0

        await page.press("H")
        await wait_for_visual_idle(page)

        registry = panel_fold_registry(page.app, "epic")
        assert registry.is_collapsed(("Done",))
        # The collapsed banner draws at once: no ``L`` or other repaint needed.
        assert ("Done",) in widget._banner_row_by_key
        banner_row = widget._banner_row_by_key[("Done",)]
        assert widget._banner_at_row[banner_row].is_collapsed is True
        assert widget.option_count == options_before - 2

        await page.press("l")
        await wait_for_visual_idle(page)

        assert not registry.is_collapsed(("Done",))
        assert widget.option_count == options_before
