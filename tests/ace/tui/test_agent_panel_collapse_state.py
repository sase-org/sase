"""Whole-panel collapse projection and refresh state behavior."""

from __future__ import annotations

from sase.ace.tui.actions.navigation._entry_jump_mode import EntryJumpModeMixin

from ._agent_panel_collapse_helpers import (
    AgentPanelCollapseApp,
    make_multi_panel_agents,
)


def test_restored_collapsed_panels_sort_on_panel_sync() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="beta")

    # Fold persistence installs this set before the established refilter/full
    # refresh path synchronizes the rendered panel collection.
    app._collapsed_panel_keys.update({"alpha", None})
    app._sync_panel_group()

    assert app._panel_group.panel_keys == ["beta", None, "alpha"]
    assert app._panel_group.focused_key == "beta"
    assert app._panel_group.focused_idx == 0


def test_hidden_panel_rows_are_omitted_from_cross_panel_consumers() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app._collapsed_panel_keys.add("alpha")

    visible = app._visible_agent_panel_indices()
    targets = EntryJumpModeMixin._jump_candidate_targets(app)

    assert 1 not in visible
    assert 2 not in visible
    assert ("agent", 1) not in targets
    assert ("agent", 2) not in targets
    assert ("agent", 0) in targets
    assert ("agent", 3) in targets
    assert ("panel", "alpha") in targets


def test_collapsed_panel_rows_are_opt_in_without_bypassing_group_folds() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app._collapsed_panel_keys.add("alpha")
    app._group_fold_registry.for_panel("alpha").collapse(("zeta",))

    ordinary = app._visible_agent_panel_indices()
    jumpable = app._visible_agent_panel_indices(include_collapsed_panels=True)

    assert 1 not in ordinary
    assert 2 not in ordinary
    assert 1 not in jumpable
    assert jumpable[2] == app._panel_group.panel_keys.index("alpha")


def test_panel_fold_intent_survives_projection_churn_and_clears_on_merge() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app._collapsed_panel_keys.add("alpha")
    app._expanded_panel_keys = {"beta"}
    app._agents = [agent for agent in app._agents if agent.tribe is None]
    app._invalidate_agent_panel_cache()

    app._sync_panel_group()

    assert app._collapsed_panel_keys == {"alpha"}
    assert app._expanded_panel_keys == {"beta"}

    app._agents = make_multi_panel_agents()
    app._invalidate_agent_panel_cache()
    app._sync_panel_group()

    assert app._panel_group.panel_keys == [None, "beta", "alpha"]
    app.action_toggle_agent_panel_grouping()
    assert app._collapsed_panel_keys == set()
    assert app._expanded_panel_keys == set()
    assert app._agent_panels_grouped is True
    assert app._resolve_focused_panel() is None
    assert app.refresh_calls == [True]


def test_expanded_panel_focus_reconciles_when_refresh_membership_churns() -> None:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app.current_idx = 2
    app._panel_selection_memory["alpha"] = ("agent", 2)
    app._expanded_panel_focus = True

    # Search/refilter-style churn that leaves the panel alive keeps its
    # key-based whole-panel focus and snaps the stale row anchor in-panel.
    app._agents = [agent for agent in app._agents if agent.agent_name != "raw-first"]
    app._invalidate_agent_panel_cache()
    app._sync_panel_group()

    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "alpha"
    assert focus.collapsed is False
    assert app._agents[app.current_idx].tribe == "alpha"

    # If refresh/filter churn removes that tribe, explicit focus and stale
    # selection memory are discarded. Reappearance must not resurrect focus.
    alpha_agents = [agent for agent in app._agents if agent.tribe == "alpha"]
    app._agents = [agent for agent in app._agents if agent.tribe != "alpha"]
    app._invalidate_agent_panel_cache()
    app._sync_panel_group()

    assert app._resolve_focused_panel() is None
    assert "alpha" not in app._panel_selection_memory
    assert app._panel_group.focused_key in {None, "beta"}

    app._agents.extend(alpha_agents)
    app._invalidate_agent_panel_cache()
    app._sync_panel_group()

    assert "alpha" in app._panel_group.panel_keys
    assert app._resolve_focused_panel() is None
