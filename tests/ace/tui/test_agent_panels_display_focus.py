"""Panel titles, focus visuals, and grouping for the Agents-tab tribe stack."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agents._display_helpers import panel_widget_id_for_key
from sase.ace.tui.actions.agents._display_panel_titles import (
    _PANEL_SELECTED_CHROME_STYLE,
)
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin

from ._agent_panel_title_helpers import _assert_title_range_style
from ._agent_panels_display_helpers import (
    _FakeApp,
    _InteractiveFakeApp,
    _pw,
    _three_panel_agents,
    _title_text,
    _two_tribe_assigned_panel_agents,
)


def test_panel_separator_class_tracks_panel_position() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 4, 6], container_height=30)

    # Simulate a reused slot carrying stale position state before refresh.
    _pw(app, None)._classes.add("agent-panel-separated")

    app._refresh_panel_widgets(jump_hints=None)

    main = _pw(app, None)
    apple = _pw(app, "apple")
    banana = _pw(app, "banana")

    assert "agent-panel-separated" not in main._classes
    assert "agent-panel-separated" in apple._classes
    assert "agent-panel-separated" in banana._classes


def test_collapsed_panel_hint_routes_by_key_in_full_and_selective_refreshes() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 4, 6], container_height=30)
    app._collapsed_panel_keys.add("banana")
    app._sync_panel_group()
    target = ("panel", "banana")

    app._refresh_panel_widgets(
        jump_hints=None,
        panel_jump_hints={target: "7"},
    )

    banana = _pw(app, "banana")
    assert getattr(banana.border_title, "plain", "") == "[7] ▸ @banana · 1 [R1]"

    app._entry_jump_mode_active = True
    app._entry_jump_panel_to_hint = {target: "x"}
    assert app._refresh_affected_panel_widgets({"banana"}) is True
    assert getattr(banana.border_title, "plain", "") == "[x] ▸ @banana · 1 [R1]"

    app._entry_jump_mode_active = False
    app._entry_jump_panel_to_hint = {}
    assert app._refresh_affected_panel_widgets({"banana"}) is True
    assert getattr(banana.border_title, "plain", "") == "▸ @banana · 1 [R1]"


def test_expanded_panel_jump_hint_routes_by_key_in_full_and_selective_refreshes() -> (
    None
):
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 4, 6], container_height=30)
    target = ("panel", "banana")

    app._refresh_panel_widgets(
        jump_hints=None,
        panel_jump_hints={target: "7"},
    )

    banana = _pw(app, "banana")
    assert getattr(banana.border_title, "plain", "") == "[7] @banana · 1 [R1]"

    app._entry_jump_mode_active = True
    app._entry_jump_panel_to_hint = {target: "x"}
    assert app._refresh_affected_panel_widgets({"banana"}) is True
    assert getattr(banana.border_title, "plain", "") == "[x] @banana · 1 [R1]"


def test_full_rebuild_focus_class_tracks_focused_panel_key() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(
        agents,
        option_counts=[2, 4, 6],
        container_height=30,
        focused_key="banana",
    )
    app.current_idx = 2

    # Simulate stale focus state from a prior panel before a full rebuild.
    _pw(app, None)._classes.add("-focused-panel")
    _pw(app, "apple")._classes.add("-focused-panel")

    app._refresh_panel_widgets(jump_hints=None)

    main = _pw(app, None)
    apple = _pw(app, "apple")
    banana = _pw(app, "banana")

    assert app._panel_group.focused_key == "banana"
    assert "-focused-panel" not in main._classes
    assert "-focused-panel" not in apple._classes
    assert "-focused-panel" in banana._classes
    assert main.last_local_idx == -1
    assert apple.last_local_idx == -1
    assert banana.last_local_idx == 0


def test_full_rebuild_selected_expanded_panel_uses_whole_panel_visuals() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(
        agents,
        option_counts=[2, 4, 6],
        container_height=30,
        focused_key="banana",
    )
    app.current_idx = 2
    app._expanded_panel_focus = True

    app._refresh_panel_widgets(jump_hints=None)

    main = _pw(app, None)
    apple = _pw(app, "apple")
    banana = _pw(app, "banana")
    assert "-whole-panel-focus" not in main._classes
    assert "-whole-panel-focus" not in apple._classes
    assert "-whole-panel-focus" in banana._classes
    assert banana.last_local_idx == -1
    assert getattr(banana.border_title, "plain", "").startswith("❖ @banana")


def test_whole_panel_navigation_refreshes_selected_and_collapsed_titles() -> None:
    agents = _three_panel_agents()
    app = _InteractiveFakeApp(
        agents,
        option_counts=[2, 4, 6],
        container_height=30,
        focused_key="banana",
    )
    app.current_idx = 2
    app._collapsed_panel_keys.add("apple")
    app._sync_panel_group()
    app._refresh_panel_widgets(jump_hints=None)

    banana = _pw(app, "banana")
    apple = _pw(app, "apple")
    assert getattr(banana.border_title, "plain", "") == "@banana · 1 [R1]"
    assert getattr(apple.border_title, "plain", "") == "▸ @apple · 1 [R1]"
    _assert_title_range_style(_title_text(apple), start=0, end=2, style="#AFAFAF")

    assert app._activate_focused_panel() is True
    assert getattr(banana.border_title, "plain", "") == "❖ @banana · 1 [R1]"

    BasicNavigationMixin._navigate_agents_panel(app, 1)
    assert getattr(banana.border_title, "plain", "") == "@banana · 1 [R1]"
    assert getattr(apple.border_title, "plain", "") == "▸ @apple · 1 [R1]"
    apple_title = _title_text(apple)
    for text in ("▸", "1", "[", "R", "]"):
        position = apple_title.plain.index(text)
        _assert_title_range_style(
            apple_title,
            start=position,
            end=position + len(text),
            style=_PANEL_SELECTED_CHROME_STYLE,
        )
    assert "❖" not in apple_title.plain

    BasicNavigationMixin._navigate_agents_panel(app, -1)
    assert getattr(banana.border_title, "plain", "") == "❖ @banana · 1 [R1]"
    assert getattr(apple.border_title, "plain", "") == "▸ @apple · 1 [R1]"
    _assert_title_range_style(_title_text(apple), start=0, end=2, style="#AFAFAF")


def test_grouped_mode_renders_one_panel_with_effective_tribe_labels() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(
        agents,
        option_counts=[3],
        container_height=40,
        agent_panels_grouped=True,
    )

    app._refresh_panel_widgets(jump_hints=None)

    assert app._panel_group.panel_keys == [None]
    assert list(app._panel_widgets) == ["agent-list-panel"]
    main = app._panel_widgets["agent-list-panel"]
    assert main.border_title is not None
    assert getattr(main.border_title, "plain", "") == "All agents · 3 [R3]"
    assert main.last_agents == agents
    assert main.last_tribe_labels == ["default", "apple", "banana"]
    assert main.last_panel_tribe is None


def test_split_panel_refreshes_thread_enclosing_tribe_context() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 2, 2], container_height=30)

    app._refresh_panel_widgets(jump_hints=None)

    main = _pw(app, None)
    apple = _pw(app, "apple")
    banana = _pw(app, "banana")
    assert [
        main.last_panel_tribe,
        apple.last_panel_tribe,
        banana.last_panel_tribe,
    ] == [None, "apple", "banana"]

    assert banana.last_panel_tribe == "banana"
    assert app._refresh_affected_panel_widgets({"banana"}) is True
    assert banana.last_panel_tribe == "banana"


def test_each_panel_widget_receives_its_scoped_fold_registry() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 2, 2], container_height=30)

    app._refresh_panel_widgets(jump_hints=None)

    registries = [
        app._panel_widgets[wid].last_fold_registry
        for wid in (
            panel_widget_id_for_key(None),
            panel_widget_id_for_key("apple"),
            panel_widget_id_for_key("banana"),
        )
    ]
    assert registries == [
        app._group_fold_registry.for_panel(None),
        app._group_fold_registry.for_panel("apple"),
        app._group_fold_registry.for_panel("banana"),
    ]
    assert len({id(registry) for registry in registries}) == 3


def test_merged_widget_uses_separate_merged_scope() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(
        agents,
        option_counts=[3],
        container_height=30,
        agent_panels_grouped=True,
    )
    app._group_fold_registry.for_panel(None, merged=False).collapse(("p",))

    app._refresh_panel_widgets(jump_hints=None)

    merged = app._panel_widgets["agent-list-panel"].last_fold_registry
    assert merged is app._group_fold_registry.for_panel(None, merged=True)
    assert merged.is_collapsed(("p",)) is False


def test_refresh_panel_widgets_span_reports_panel_widget_ids(
    tmp_path: Any, monkeypatch: Any
) -> None:
    """Soaks assert tribe-stable widget identity from the trace, not by eye."""
    import json

    from sase.ace.tui.util import trace

    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    app = _FakeApp(
        _two_tribe_assigned_panel_agents(), option_counts=[2, 2], container_height=30
    )

    app._refresh_panel_widgets(jump_hints=None)

    trace._flush_trace_writes()
    spans = [
        json.loads(line)
        for line in log.read_text().splitlines()
        if line and json.loads(line).get("span") == "agents.refresh_panel_widgets"
    ]
    (span,) = spans
    assert span["panels"] == 2
    assert span["panel_widget_ids"] == [
        panel_widget_id_for_key("apple"),
        panel_widget_id_for_key("banana"),
    ]
