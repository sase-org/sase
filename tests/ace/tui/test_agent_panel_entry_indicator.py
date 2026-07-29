"""The tribe roster cursor agrees with whole-panel entry navigation."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MEMBER_ENTRY_CURSOR_GLYPH,
)

from ._agent_panel_collapse_helpers import (
    AgentPanelCollapseApp,
    make_agent,
    make_multi_panel_agents,
)


def _expanded_app() -> AgentPanelCollapseApp:
    app = AgentPanelCollapseApp(make_multi_panel_agents(), focused_key="alpha")
    app._expanded_panel_focus = True
    return app


def _rendered_tribe(app: AgentPanelCollapseApp) -> str:
    snapshot = app._focused_tribe_summary()
    assert snapshot is not None
    return build_tribe_detail_text(snapshot).plain


def _cursor_lines(rendered: str) -> list[str]:
    return [
        line
        for line in rendered.splitlines()
        if line.startswith(MEMBER_ENTRY_CURSOR_GLYPH)
    ]


def test_fresh_panel_marks_and_enters_first_rendered_row_not_roster_zero() -> None:
    app = _expanded_app()

    rendered = _rendered_tribe(app)

    assert len(_cursor_lines(rendered)) == 1
    assert _cursor_lines(rendered)[0].startswith("❯  1  render-first · agent")
    assert "TRIBE MEMBERS · 2 · l ❯ render-first" in rendered
    assert "  0  raw-first" in rendered

    app.action_expand_or_layout()

    assert app._resolve_focused_panel() is None
    assert app.current_idx == 2
    assert app._agents[app.current_idx].agent_name == "render-first"


def test_remembered_row_is_marked_and_escape_uses_the_same_destination() -> None:
    app = _expanded_app()
    app._panel_selection_memory["alpha"] = ("agent", 1)

    rendered = _rendered_tribe(app)

    assert len(_cursor_lines(rendered)) == 1
    assert "raw-first" in _cursor_lines(rendered)[0]
    assert "TRIBE MEMBERS · 2 · l ❯ raw-first" in rendered

    assert app._exit_expanded_panel_focus() is True

    assert app._resolve_focused_panel() is None
    assert app.current_idx == 1
    assert app._agents[app.current_idx].agent_name == "raw-first"


def test_removed_remembered_row_moves_cursor_to_the_new_first_stop() -> None:
    app = _expanded_app()
    app._panel_selection_memory["alpha"] = ("agent", 2)
    assert "render-first" in _cursor_lines(_rendered_tribe(app))[0]

    app._agents.pop(2)
    app._invalidate_agent_panel_cache()
    app._sync_panel_group()

    rendered = _rendered_tribe(app)

    assert len(_cursor_lines(rendered)) == 1
    assert "raw-first" in _cursor_lines(rendered)[0]
    assert "TRIBE MEMBERS · 1 · l ❯ raw-first" in rendered

    app.action_expand_or_layout()

    assert app.current_idx == 1
    assert app._agents[app.current_idx].agent_name == "raw-first"


def test_grouping_change_moves_cursor_with_the_render_order() -> None:
    app = _expanded_app()
    app._agents[1].status = "RUNNING"
    app._agents[2].status = "DONE"
    assert "render-first" in _cursor_lines(_rendered_tribe(app))[0]

    app._grouping_mode = GroupingMode.BY_STATUS
    app._nav_stops_cache = None

    rendered = _rendered_tribe(app)

    assert len(_cursor_lines(rendered)) == 1
    assert "raw-first" in _cursor_lines(rendered)[0]
    assert "TRIBE MEMBERS · 2 · l ❯ raw-first" in rendered

    app.action_expand_or_layout()

    assert app.current_idx == 1
    assert app._agents[app.current_idx].agent_name == "raw-first"


def test_nested_destination_marks_owning_family_and_names_exact_member() -> None:
    root = make_agent(name="ns--plan", project="one", tribe="alpha")
    root.agent_family = "ns"
    root.agent_family_role = "root"
    root.role_suffix = "--plan"
    root.plan_chain_root = True
    root.refresh_raw_presented_agent_name()
    child = make_agent(name="ns--2", project="one", tribe="alpha")
    child.agent_family = "ns"
    child.agent_family_role = "code"
    child.role_suffix = "--2"
    child.parent_timestamp = root.raw_suffix
    child.refresh_raw_presented_agent_name()
    root.followup_agents = [child]
    app = AgentPanelCollapseApp([root, child], focused_key="alpha")
    app._expanded_panel_focus = True
    app._panel_selection_memory["alpha"] = ("agent", 1)

    rendered = _rendered_tribe(app)

    assert len(_cursor_lines(rendered)) == 1
    assert "ns · family" in _cursor_lines(rendered)[0]
    assert "TRIBE MEMBERS · 1 · l ❯ ns › --2" in rendered

    app.action_expand_or_layout()

    assert app.current_idx == 1
    assert app._agents[app.current_idx] is child


def test_collapsed_group_destination_is_named_without_a_row_cursor() -> None:
    app = AgentPanelCollapseApp(
        [
            make_agent(name="one", project="one", tribe="research"),
            make_agent(name="two", project="two", tribe="research"),
        ],
        focused_key="research",
    )
    banner = app._all_known_group_keys()[0]
    app._group_fold_registry.for_panel("research").collapse(banner)
    app._panel_selection_memory["research"] = ("banner", banner)
    app._expanded_panel_focus = True

    rendered = _rendered_tribe(app)

    assert _cursor_lines(rendered) == []
    assert f"TRIBE MEMBERS · 2 · l ❯ {banner[0]} (group)" in rendered

    app.action_expand_or_layout()

    assert app._resolve_focused_panel() is None
    assert app._current_group_key == banner


def test_collapsed_panel_omits_cursor_until_first_l_expands_it() -> None:
    app = _expanded_app()
    app._collapsed_panel_keys.add("alpha")
    app._sync_panel_group()

    collapsed = _rendered_tribe(app)

    assert MEMBER_ENTRY_CURSOR_GLYPH not in collapsed
    assert " · l " not in collapsed

    app.action_expand_or_layout()

    focus = app._resolve_focused_panel()
    assert focus is not None and focus.collapsed is False
    expanded = _rendered_tribe(app)
    assert len(_cursor_lines(expanded)) == 1
    assert " · l ❯ " in expanded

    app.action_expand_or_layout()

    assert app._resolve_focused_panel() is None


def test_heading_uses_rebound_panel_entry_key_and_cheap_path_skips_resolution() -> None:
    app = _expanded_app()
    app._keymap_registry = SimpleNamespace(
        app=SimpleNamespace(expand_or_layout="enter")
    )

    rendered = _rendered_tribe(app)

    assert "TRIBE MEMBERS · 2 · <enter> ❯ render-first" in rendered

    app._panel_navigation_stops = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("entry target resolved on cheap path")
    )
    snapshot = app._focused_tribe_summary(with_entry_target=False)
    assert snapshot is not None
    assert snapshot.entry_target is None
