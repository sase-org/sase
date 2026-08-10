"""Panel isolation and restore from an in-panel row selection."""

from __future__ import annotations

from sase.ace.tui.models.agent_panels import PanelIsolationRevert
from tests.ace.tui._agent_panel_collapse_helpers import (
    AgentPanelCollapseApp,
    make_agent,
    make_multi_panel_agents,
)


def test_row_focus_isolation_collapses_siblings_without_touching_selection() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 1
    app._current_group_key = ("zeta",)

    assert app._resolve_focused_panel() is None  # ordinary row focus, not whole-panel

    app.action_isolate_panels()

    assert app._collapsed_panel_keys == {None, "beta"}
    assert app._panel_group.panel_keys == ["alpha", None, "beta"]
    assert app._panel_group.focused_key == "alpha"
    assert app._expanded_panel_focus is False
    assert app.current_idx == 1
    assert app._current_group_key == ("zeta",)
    assert app.current_attempt_number == 7
    assert app.panel_fold_changes == [(None, True), ("beta", True)]
    assert app._panel_isolation_revert == PanelIsolationRevert(
        target_key="alpha",
        collapsed_before=frozenset(),
    )


def test_row_focus_restore_round_trips_previous_layout() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 1
    app._current_group_key = ("zeta",)
    app.action_isolate_panels()
    assert app._panel_isolation_revert is not None

    app.action_isolate_panels()

    assert app._collapsed_panel_keys == set()
    assert app._panel_isolation_revert is None
    assert app._expanded_panel_focus is False
    assert app.current_idx == 1
    assert app._current_group_key == ("zeta",)
    assert app.notifications[-1] == "Restored 2 panels"


def test_row_focus_restore_collapsing_cursor_panel_lands_on_collapsed_focus() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 2
    app._current_group_key = ("zeta",)
    app._collapsed_panel_keys = {None}
    app._sync_panel_group()
    app._panel_isolation_revert = PanelIsolationRevert(
        target_key="beta",
        collapsed_before=frozenset({None, "alpha"}),
    )

    assert app._resolve_focused_panel() is None  # cursor sits in the expanded panel

    app.action_isolate_panels()

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "alpha"
    assert focus.collapsed is True
    assert app.current_idx == 1  # snapped to alpha's first rendered row
    assert app._current_group_key is None
    assert app._expanded_panel_focus is False
    assert app._collapsed_panel_keys == {None, "alpha"}
    assert app._panel_isolation_revert is None
    assert app.notifications == ["Restored 1 panel"]


def test_merged_layout_warns_instead_of_mutating_folds() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), merged=True)

    app.action_isolate_panels()

    assert app.notifications == ["No tribe panels to isolate"]
    assert app.refresh_calls == []
    assert app._panel_isolation_revert is None


def test_single_panel_layout_warns_instead_of_mutating_folds() -> None:
    app = AgentPanelCollapseApp([make_agent(name="solo", project="home", tribe=None)])

    app.action_isolate_panels()

    assert app.notifications == ["No tribe panels to isolate"]
    assert app.refresh_calls == []
    assert app._panel_isolation_revert is None
