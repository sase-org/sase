"""Scope resolution for ``,H`` collapse-by-hint (selected tribe vs every tribe)."""

from __future__ import annotations

from sase.ace.tui.models.fold_state import FoldLevel
from tests.ace.tui.test_agent_panel_hint_collapse import _PanelFocusEntryApp
from tests.ace.tui.test_agent_panel_hint_folding import _agent, _EntryApp


def _two_tribe_agents() -> list[object]:
    return [
        _agent("alpha-first", "alpha", project_file="/r/alpha/project.sase"),
        _agent("alpha-second", "alpha", project_file="/r/alpha/project.sase"),
        _agent("beta-first", "beta", project_file="/r/beta/project.sase"),
        _agent("beta-second", "beta", project_file="/r/beta/project.sase"),
    ]


def _two_tribe_app(**kwargs: object) -> _PanelFocusEntryApp:
    kwargs.setdefault("agents", _two_tribe_agents())
    kwargs.setdefault("collapsed_panels", set())
    return _PanelFocusEntryApp(**kwargs)  # type: ignore[arg-type]


def _collapse_all_hintable_folds(app: _EntryApp, *, scope: str = "all") -> None:
    for target in list(
        app._enumerate_panel_fold_hint_targets(
            collapsible_only=True,
            scope=scope,  # type: ignore[arg-type]
        )
    ):
        if target[0] == "group":
            app._group_fold_registry.for_panel(target[1]).collapse(target[2])
        elif target[0] == "agent":
            while app._fold_manager.get(target[3]) != FoldLevel.COLLAPSED:
                if not app._fold_manager.collapse(target[3]):
                    break


def test_row_focus_arms_selected_tribe_scope_matching_whole_panel_h() -> None:
    row_app = _EntryApp(agents=_two_tribe_agents(), collapsed_panels=set())
    panel_app = _two_tribe_app()

    row_app.action_collapse_fold_by_hint()
    panel_app.action_hooks_or_collapse_all()

    assert row_app._panel_fold_hint_scope == "tribe"
    assert row_app._panel_fold_hint_snapshot == panel_app._panel_fold_hint_snapshot
    assert all(target[1] == "alpha" for target in row_app._panel_fold_hint_snapshot)
    assert all(target[0] != "panel" for target in row_app._panel_fold_hint_snapshot)
    assert row_app.footer.fold_hint_all_tribes is False
    assert row_app.footer.fold_hint_collapse_only is True


def test_whole_panel_focus_arms_all_tribes_in_render_order() -> None:
    app = _two_tribe_app()

    app.action_collapse_fold_by_hint()

    assert app._panel_fold_hint_scope == "all"
    assert app.footer.fold_hint_all_tribes is True
    snapshot = app._panel_fold_hint_snapshot
    kinds_and_panels = [(target[0], target[1]) for target in snapshot]
    assert kinds_and_panels[0] == ("panel", "alpha")
    assert ("panel", "beta") in kinds_and_panels
    alpha_panel_at = kinds_and_panels.index(("panel", "alpha"))
    beta_panel_at = kinds_and_panels.index(("panel", "beta"))
    assert alpha_panel_at < beta_panel_at
    assert any(target[0] != "panel" and target[1] == "alpha" for target in snapshot)
    assert any(target[0] != "panel" and target[1] == "beta" for target in snapshot)
    assert all(
        kinds_and_panels[index][1] == "alpha"
        for index in range(alpha_panel_at, beta_panel_at)
    )


def test_collapsed_panels_contribute_nothing_to_all_scope() -> None:
    app = _two_tribe_app(collapsed_panels={"beta"})

    app.action_collapse_fold_by_hint()

    assert app._panel_fold_hint_mode_active is True
    assert all(target[1] != "beta" for target in app._panel_fold_hint_snapshot)
    assert ("panel", "alpha") in app._panel_fold_hint_snapshot


def test_collapsed_whole_panel_focus_still_arms_all_scope_over_other_panels() -> None:
    app = _PanelFocusEntryApp(
        agents=_two_tribe_agents(),  # type: ignore[arg-type]
        focused_key="beta",
        collapsed_panels={"beta"},
        panel_collapsed=True,
    )

    app.action_collapse_fold_by_hint()

    assert app._panel_fold_hint_scope == "all"
    assert app._panel_fold_hint_mode_active is True
    assert all(target[1] != "beta" for target in app._panel_fold_hint_snapshot)
    assert any(target[1] == "alpha" for target in app._panel_fold_hint_snapshot)


def test_single_live_panel_and_merged_layout_omit_panel_targets() -> None:
    single = _PanelFocusEntryApp(
        agents=[_agent("only", None)],
        focused_key=None,
        collapsed_panels=set(),
    )
    single.action_collapse_fold_by_hint()
    assert single._panel_fold_hint_mode_active is True
    assert all(target[0] != "panel" for target in single._panel_fold_hint_snapshot)

    merged = _EntryApp(merged=True)
    merged.action_collapse_fold_by_hint()
    assert merged._panel_fold_hint_scope == "tribe"
    assert all(target[0] != "panel" for target in merged._panel_fold_hint_snapshot)


def test_all_panels_collapsed_warns_without_arming() -> None:
    app = _PanelFocusEntryApp(
        agents=_two_tribe_agents(),  # type: ignore[arg-type]
        collapsed_panels={"alpha", "beta"},
        panel_collapsed=True,
    )

    app.action_collapse_fold_by_hint()

    assert app._panel_fold_hint_mode_active is False
    assert app.notifications[-1] == "All tribe panels are collapsed"


def test_single_expanded_panel_with_no_folds_warns_without_arming() -> None:
    app = _PanelFocusEntryApp(
        agents=[_agent("only", None)],
        focused_key=None,
        collapsed_panels=set(),
    )
    _collapse_all_hintable_folds(app, scope="all")

    app.action_collapse_fold_by_hint()

    assert app._panel_fold_hint_mode_active is False
    assert app.notifications[-1] == "No expanded folds in any tribe panel"


def test_picking_banner_in_other_panel_does_not_snap_focus() -> None:
    app = _two_tribe_app()
    app.action_collapse_fold_by_hint()
    group_target = next(
        target
        for target in app._panel_fold_hint_snapshot
        if target[0] == "group" and target[1] == "beta"
    )

    assert app._handle_panel_fold_hint_key(app.hint_for(group_target)) is True

    assert app._group_fold_registry.for_panel("beta").is_collapsed(group_target[2])
    assert app.group_persistence_intents == [("beta", group_target[2], True)]
    assert app.snap_group_focus_calls == 0
    assert app._resolve_focused_panel() is not None
    assert app._resolve_focused_panel().panel_key == "alpha"  # type: ignore[union-attr]


def test_picking_agent_fold_in_other_panel_lands_collapsed() -> None:
    app = _PanelFocusEntryApp(
        agents=[
            _agent("alpha-flow", "alpha", workflow="alpha-flow"),
            _agent("beta-flow", "beta", workflow="beta-flow"),
        ],
        collapsed_panels=set(),
        fold_counts={"alpha-flow": (1, 0), "beta-flow": (1, 0)},
    )
    app._fold_manager.expand("alpha-flow")
    app._fold_manager.expand("beta-flow")
    app.action_collapse_fold_by_hint()
    target = next(
        target
        for target in app._panel_fold_hint_snapshot
        if target[0] == "agent" and target[3] == "beta-flow"
    )

    assert app._handle_panel_fold_hint_key(app.hint_for(target)) is True

    assert app._fold_manager.get("beta-flow") == FoldLevel.COLLAPSED
    assert app.notifications[-1] == "Fold collapsed"


def test_picking_focused_panel_title_uses_focused_collapse_path() -> None:
    app = _two_tribe_app()
    app.action_collapse_fold_by_hint()
    target = ("panel", "alpha")
    assert target in app._panel_fold_hint_snapshot

    assert app._handle_panel_fold_hint_key(app.hint_for(target)) is True

    assert "alpha" in app._collapsed_panel_keys
    assert "beta" not in app._collapsed_panel_keys
    assert app.notifications[-1] == "Panel collapsed"


def test_picking_other_panel_title_applies_layout_for_that_key() -> None:
    app = _two_tribe_app()
    app.action_collapse_fold_by_hint()
    target = ("panel", "beta")
    assert target in app._panel_fold_hint_snapshot

    assert app._handle_panel_fold_hint_key(app.hint_for(target)) is True

    assert "beta" in app._collapsed_panel_keys
    assert "alpha" not in app._collapsed_panel_keys
    assert app.notifications[-1] == "Panel collapsed"
    assert app._resolve_focused_panel() is not None
    assert app._resolve_focused_panel().panel_key == "alpha"  # type: ignore[union-attr]


def test_stale_snapshot_in_all_scope_aborts_with_retry_warning() -> None:
    app = _two_tribe_app()
    app.action_collapse_fold_by_hint()
    target = app._panel_fold_hint_snapshot[0]
    hint = app.hint_for(target)
    app._agents.append(_agent("new-beta-project", "beta"))
    app._invalidate_agent_panel_cache()

    app._handle_panel_fold_hint_key(hint)

    assert app._panel_fold_hint_mode_active is False
    assert app.notifications[-1] == "Visible folds changed; retry fold selection"


def test_title_map_is_panel_targets_only_and_display_maps_ignore_them() -> None:
    app = _two_tribe_app()
    app.action_collapse_fold_by_hint()

    title_map = app._panel_fold_hint_title_map()
    assert set(title_map) == {("panel", "alpha"), ("panel", "beta")}
    agent_hints, banner_hints = app._panel_fold_hint_display_maps()
    assert all(isinstance(index, int) for index in agent_hints)
    assert all(target[0] == "banner" for target in banner_hints)

    tribe = _EntryApp(agents=_two_tribe_agents(), collapsed_panels=set())
    tribe.action_collapse_fold_by_hint()
    assert tribe._panel_fold_hint_title_map() == {}


def test_teardown_repaints_every_live_panel_in_all_scope_and_resets() -> None:
    app = _two_tribe_app()
    app.action_collapse_fold_by_hint()
    live_keys = set(app._panel_group.panel_keys)
    assert app.affected_refreshes[-1] == live_keys

    assert app._handle_panel_fold_hint_key("escape") is True

    assert app._panel_fold_hint_mode_active is False
    assert app._panel_fold_hint_scope == "tribe"
    assert app.affected_refreshes[-1] == live_keys


def test_teardown_repaints_focused_panel_in_tribe_scope() -> None:
    app = _EntryApp(agents=_two_tribe_agents(), collapsed_panels=set())
    app.action_collapse_fold_by_hint()
    assert app.affected_refreshes[-1] == {"alpha"}

    app._handle_panel_fold_hint_key("escape")

    assert app.affected_refreshes[-1] == {"alpha"}
    assert app._panel_fold_hint_scope == "tribe"


def test_row_focus_reanchors_workflow_child_hidden_by_picked_fold() -> None:
    parent = _agent("flow", "alpha", workflow="flow")
    child = _agent(
        "step",
        "alpha",
        raw_suffix="step",
        parent_workflow="flow",
        parent_timestamp="flow",
        step_type="agent",
    )
    app = _EntryApp(
        agents=[parent, child],
        collapsed_panels=set(),
        fold_counts={"flow": (1, 0)},
    )
    app._fold_manager.expand("flow")
    app.current_idx = 1
    app.action_collapse_fold_by_hint()
    target = next(
        item
        for item in app._panel_fold_hint_snapshot
        if item[0] == "agent" and item[3] == "flow"
    )

    assert app._handle_panel_fold_hint_key(app.hint_for(target)) is True

    assert app.current_idx == 0
    assert app.remember_selection_calls == 1
    assert app._fold_manager.get("flow") == FoldLevel.COLLAPSED


def test_row_focus_reanchors_clan_member_hidden_by_picked_fold() -> None:
    clan = _agent(
        "crew",
        "alpha",
        raw_suffix=None,
        is_clan_container=True,
        agent_clan="crew",
    )
    member = _agent(
        "crew-member",
        "alpha",
        tree_parent_key="clan:crew",
        tree_depth=1,
    )
    app = _EntryApp(agents=[clan, member], collapsed_panels=set())
    app._fold_manager.expand("clan:crew")
    app.current_idx = 1
    app.action_collapse_fold_by_hint()
    target = next(
        item
        for item in app._panel_fold_hint_snapshot
        if item[0] == "agent" and item[3] == "clan:crew"
    )

    assert app._handle_panel_fold_hint_key(app.hint_for(target)) is True

    assert app.current_idx == 0
    assert app.remember_selection_calls == 1


def test_row_focus_skips_reanchor_when_selection_is_outside_fold() -> None:
    parent = _agent("flow", "alpha", workflow="flow")
    other = _agent("other", "alpha")
    app = _EntryApp(
        agents=[parent, other],
        collapsed_panels=set(),
        fold_counts={"flow": (1, 0)},
    )
    app._fold_manager.expand("flow")
    app.current_idx = 1
    app.action_collapse_fold_by_hint()
    target = next(
        item
        for item in app._panel_fold_hint_snapshot
        if item[0] == "agent" and item[3] == "flow"
    )

    assert app._handle_panel_fold_hint_key(app.hint_for(target)) is True

    assert app.current_idx == 1
    assert app.remember_selection_calls == 0


def test_toggle_intent_row_focus_reanchors_hidden_workflow_child() -> None:
    parent = _agent("flow", "alpha", workflow="flow")
    child = _agent(
        "step",
        "alpha",
        raw_suffix="step",
        parent_workflow="flow",
        parent_timestamp="flow",
        step_type="agent",
    )
    app = _EntryApp(
        agents=[parent, child],
        collapsed_panels=set(),
        fold_counts={"flow": (1, 0)},
    )
    app._fold_manager.expand("flow")
    app.current_idx = 1
    app.action_toggle_selected_agent_panels()
    assert app._panel_fold_hint_intent == "toggle"
    target = next(
        item
        for item in app._panel_fold_hint_snapshot
        if item[0] == "agent" and item[3] == "flow"
    )

    assert app._handle_panel_fold_hint_key(app.hint_for(target)) is True

    assert app.current_idx == 0
    assert app.remember_selection_calls == 1
    assert app._fold_manager.get("flow") == FoldLevel.COLLAPSED
