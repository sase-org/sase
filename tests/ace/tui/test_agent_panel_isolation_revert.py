"""Undo semantics for the Agents-tab zoom-action panel isolation."""

from __future__ import annotations

from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.agent_panels import PanelIsolationRevert
from tests.ace.tui.test_agent_panel_collapse import (
    _StubApp,
    _agent,
    _multi_panel_agents,
)


def test_isolate_then_restore_round_trips_an_arbitrary_layout() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 2
    app._collapsed_panel_keys.update({None, "alpha"})
    app._sync_panel_group()

    app.action_zoom_panel()

    assert app._collapsed_panel_keys == {None, "beta"}
    assert app._panel_isolation_revert == PanelIsolationRevert(
        target_key="alpha",
        collapsed_before=frozenset({None, "alpha"}),
    )
    assert app._panel_isolation_marked_keys() == {"alpha", "beta"}

    # The armed restore belongs to the zoom action, not the original target panel.
    BasicNavigationMixin._navigate_agents_panel(app, 1)
    BasicNavigationMixin._navigate_agents_panel(app, 1)
    assert app._panel_group.focused_key == "beta"
    app.action_zoom_panel()

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "beta"
    assert focus.collapsed is False
    assert app._collapsed_panel_keys == {None, "alpha"}
    assert app._panel_isolation_revert is None
    assert app._panel_isolation_marked_keys() == set()
    assert app.panel_fold_changes == [
        ("beta", True),
        ("alpha", False),
        ("alpha", True),
        ("beta", False),
    ]
    assert app.notifications == ["Restored 2 panels"]


def test_idempotent_isolation_does_not_arm_restore() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app._collapsed_panel_keys.update({None, "beta"})
    app._sync_panel_group()
    app._expanded_panel_focus = True

    app.action_zoom_panel()

    assert app._collapsed_panel_keys == {None, "beta"}
    assert app._panel_isolation_revert is None
    assert app.refresh_calls == []
    assert app.affected_refreshes == []
    assert app.footer_refresh_calls == 0


def test_target_panel_changes_keep_restore_but_other_panel_change_disarms() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app._expanded_panel_focus = True
    app.action_zoom_panel()
    armed = app._panel_isolation_revert
    assert armed is not None

    app.action_hooks_or_collapse()
    assert app._collapsed_panel_keys == {None, "alpha", "beta"}
    assert app._panel_isolation_revert is armed

    app.action_expand_or_layout()
    assert app._collapsed_panel_keys == {None, "beta"}
    assert app._panel_isolation_revert is armed

    BasicNavigationMixin._navigate_agents_panel(app, 1)
    assert app._panel_group.focused_key is None
    app.action_expand_or_layout()

    assert app._collapsed_panel_keys == {"beta"}
    assert app._panel_isolation_revert is None
    assert app._panel_isolation_marked_keys() == set()


def test_numeric_panel_fold_funnel_disarms_non_target_change() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app._expanded_panel_focus = True
    app.action_zoom_panel()
    assert app._panel_isolation_revert is not None

    # Numeric fold selection mutates first, then records through this funnel.
    app._collapsed_panel_keys.discard("beta")
    app._persist_panel_fold_change("beta", collapsed=False)

    assert app._panel_isolation_revert is None
    assert "beta" in app.affected_refreshes[-1]


def test_merged_layout_toggle_disarms_restore() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app._expanded_panel_focus = True
    app.action_zoom_panel()
    assert app._panel_isolation_revert is not None

    app.action_toggle_agent_panel_grouping()

    assert app._panel_isolation_revert is None
    assert app._collapsed_panel_keys == set()
    assert app._agent_panels_grouped is True


def test_vanished_target_expires_restore_when_markers_are_computed() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app._expanded_panel_focus = True
    app.action_zoom_panel()
    assert app._panel_isolation_revert is not None

    app._agents = [agent for agent in app._agents if agent.tribe != "alpha"]
    app._invalidate_agent_panel_cache()
    app._sync_panel_group()

    assert app._panel_isolation_marked_keys() == set()
    assert app._panel_isolation_revert is None


def test_restore_preserves_vanished_intent_and_leaves_new_panels_expanded() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app._collapsed_panel_keys.add("beta")
    app._sync_panel_group()
    app._expanded_panel_focus = True
    app.action_zoom_panel()
    assert app._panel_isolation_revert is not None

    app._agents = [agent for agent in app._agents if agent.tribe != "beta"]
    app._agents.append(_agent(name="gamma", project="gamma", tribe="gamma"))
    app._invalidate_agent_panel_cache()
    app._sync_panel_group()
    assert "gamma" not in app._collapsed_panel_keys

    app.action_zoom_panel()

    assert app._collapsed_panel_keys == {"beta"}
    assert "gamma" not in app._collapsed_panel_keys
    assert app._panel_isolation_revert is None


def test_restore_with_no_remaining_diff_disarms_and_reports_zero() -> None:
    app = _StubApp(_multi_panel_agents(), focused_key="alpha")
    app._collapsed_panel_keys.update({None, "beta"})
    app._sync_panel_group()
    app._expanded_panel_focus = True

    # Manually install the only armed shape that can have no current diff:
    # the user returned the exempt target to its pre-isolation state.
    app._panel_isolation_revert = PanelIsolationRevert(
        target_key="alpha",
        collapsed_before=frozenset({None, "beta"}),
    )
    app.action_zoom_panel()

    assert app._panel_isolation_revert is None
    assert app.refresh_calls == []
    assert app.notifications == ["Restored 0 panels"]
