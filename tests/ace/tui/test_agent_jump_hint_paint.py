"""App-level paint coverage for Agents-tab jump and fold hints.

The widget-level tests call ``AgentList.update_list`` directly with a hint map,
so they cannot notice when the panel paint gate never hands the map to the
rows. These tests drive the app-level refresh paths and assert on rendered row
text, not on ``update_list`` call counts alone.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.ace.tui.actions.agents._panel_hint_folding import AgentPanelHintFoldingMixin
from sase.ace.tui.actions.navigation._entry_jump_mode import EntryJumpModeMixin
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree
from sase.ace.tui.widgets.agent_list import AgentList
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter

from ._agent_display_diff_helpers import _DisplayDiffApp, _agent, _widget_sel


class _JumpApp(EntryJumpModeMixin, AgentPanelHintFoldingMixin, _DisplayDiffApp):
    """Display harness that can also enter, refresh, and exit hint modes."""

    def __init__(self, agents: list[Agent], monkeypatch: Any) -> None:
        super().__init__(agents, monkeypatch)
        self._entry_jump_panel_to_hint: dict[Any, str] = {}
        self._entry_jump_agents_anchor_stack: list[Any] = []
        self._panel_fold_hint_mode_active = False
        self._panel_fold_target_to_hint: dict[Any, str] = {}
        self._panel_fold_hint_scope = "tribe"

    def _get_selected_agent(self) -> Agent | None:
        return None


def _agents() -> list[Agent]:
    return [
        _agent("alpha", tribe="apple", suffix="a1"),
        _agent("beta", tribe="apple", suffix="b1", status="DONE"),
        _agent("gamma", tribe="pear", suffix="g1"),
    ]


def _rows(widget: AgentList) -> list[str]:
    return [
        str(widget.get_option_at_index(i).prompt) for i in range(widget.option_count)
    ]


def _title(widget: AgentList) -> str:
    return Text.from_markup(str(widget.border_title)).plain


def _panels(app: _JumpApp) -> tuple[AgentList, AgentList]:
    return app._widgets[_widget_sel("apple")], app._widgets[_widget_sel("pear")]


def _row_with(widget: AgentList, needle: str) -> str:
    matches = [row for row in _rows(widget) if needle in row]
    assert len(matches) == 1, _rows(widget)
    return matches[0]


def _collapse_banner(app: _JumpApp, panel_key: str, *, member: str) -> tuple[str, ...]:
    """Collapse the grouping banner for *member* and return its group key."""
    registry = app._group_fold_registry.for_panel(panel_key)
    panel_agents = [a for a in app._agents if a.tribe == panel_key]
    tree = build_agent_tree(
        panel_agents, fold_registry=registry, mode=GroupingMode.STANDARD
    )
    group_key = next(
        entry.group.group_key
        for entry in tree
        if entry.kind == "group"
        and entry.group is not None
        and entry.group.group_key[-1] == member
    )
    registry.collapse(group_key)
    app._refresh_panel_widgets(jump_hints=None)
    return group_key


def test_entry_jump_hints_paint_on_agent_rows_and_titles(monkeypatch: Any) -> None:
    app = _JumpApp(_agents(), monkeypatch)
    apple, pear = _panels(app)
    assert (apple.update_list_calls, pear.update_list_calls) == (1, 1)  # type: ignore[attr-defined]

    app._entry_jump_mode_active = True
    app._entry_jump_index_to_hint = {0: "a", 1: "b", 2: "c"}
    app._entry_jump_panel_to_hint = {("panel", "apple"): "x", ("panel", "pear"): "y"}

    assert app._refresh_affected_panel_widgets(set(app._panel_group.panel_keys))

    assert apple.update_list_calls == 2  # type: ignore[attr-defined]
    assert pear.update_list_calls == 2  # type: ignore[attr-defined]
    assert "[a]" in _row_with(apple, "alpha (RUNNING)")
    assert "[b]" in _row_with(apple, "beta (DONE)")
    assert "[c]" in _row_with(pear, "gamma (RUNNING)")
    assert "[x]" in _title(apple)
    assert "[y]" in _title(pear)


def test_entry_jump_hints_use_panel_local_rows_for_hidden_agents(
    monkeypatch: Any,
) -> None:
    """Global hint indices must land on the right row of a later panel."""
    app = _JumpApp(_agents(), monkeypatch)
    apple, pear = _panels(app)
    app._entry_jump_mode_active = True
    app._entry_jump_index_to_hint = {2: "q"}

    assert app._refresh_affected_panel_widgets(set(app._panel_group.panel_keys))

    assert "[q]" in _row_with(pear, "gamma (RUNNING)")
    assert not any("[q]" in row for row in _rows(apple))


def test_entry_jump_hint_painting_is_stable_across_repeated_refreshes(
    monkeypatch: Any,
) -> None:
    app = _JumpApp(_agents(), monkeypatch)
    apple, _pear = _panels(app)
    app._entry_jump_mode_active = True
    app._entry_jump_index_to_hint = {0: "a", 1: "b"}
    keys = set(app._panel_group.panel_keys)

    assert app._refresh_affected_panel_widgets(keys)
    assert apple.update_list_calls == 2  # type: ignore[attr-defined]
    assert app._refresh_affected_panel_widgets(keys)
    assert apple.update_list_calls == 2  # type: ignore[attr-defined]
    assert "[a]" in _row_with(apple, "alpha (RUNNING)")


def test_entry_jump_banner_hints_paint_on_collapsed_group(monkeypatch: Any) -> None:
    app = _JumpApp(_agents(), monkeypatch)
    apple, _pear = _panels(app)
    group_key = _collapse_banner(app, "apple", member="beta")
    banner_row = _row_with(apple, "beta")
    assert "[z]" not in banner_row

    app._entry_jump_mode_active = True
    app._entry_jump_banner_to_hint = {("banner", 0, group_key): "z"}

    assert app._refresh_affected_panel_widgets({"apple"})

    assert "[z]" in _row_with(apple, "beta")


def test_exit_entry_jump_mode_clears_row_and_title_hints(monkeypatch: Any) -> None:
    app = _JumpApp(_agents(), monkeypatch)
    apple, pear = _panels(app)
    group_key = _collapse_banner(app, "apple", member="beta")
    app._entry_jump_mode_active = True
    app._entry_jump_index_to_hint = {0: "a", 2: "c"}
    app._entry_jump_banner_to_hint = {("banner", 0, group_key): "z"}
    app._entry_jump_panel_to_hint = {("panel", "apple"): "x", ("panel", "pear"): "y"}
    app._refresh_agents_jump_hint_display()
    assert "[a]" in _row_with(apple, "alpha (RUNNING)")
    assert "[z]" in _row_with(apple, "beta")
    assert "[x]" in _title(apple)

    app._exit_entry_jump_mode()

    for widget in (apple, pear):
        rendered = "\n".join(_rows(widget) + [_title(widget)])
        for hint in "acxyz":
            assert f"[{hint}]" not in rendered
    assert app.full_rebuilds == 0


def test_fold_hint_mode_paints_rows_banners_and_titles(monkeypatch: Any) -> None:
    app = _JumpApp(_agents(), monkeypatch)
    apple, pear = _panels(app)
    group_key = _collapse_banner(app, "apple", member="beta")
    app._panel_fold_hint_mode_active = True
    app._panel_fold_hint_scope = "all"
    app._panel_fold_target_to_hint = {
        ("agent", "apple", 0, "fold-alpha"): "f",
        ("group", "apple", group_key): "g",
        ("panel", "apple"): "h",
        ("panel", "pear"): "j",
    }

    app._refresh_panel_fold_hint_display()

    assert "[f]" in _row_with(apple, "alpha (RUNNING)")
    assert "[g]" in _row_with(apple, "beta")
    assert "[h]" in _title(apple)
    assert "[j]" in _title(pear)
    assert app.full_rebuilds == 0

    app._teardown_panel_fold_hint_mode(refresh_titles=False)
    app._refresh_panel_fold_hint_display({"apple", "pear"})

    for widget in (apple, pear):
        rendered = "\n".join(_rows(widget) + [_title(widget)])
        for hint in "fghj":
            assert f"[{hint}]" not in rendered


def test_unchanged_panels_are_not_rebuilt_when_no_hint_mode_is_active(
    monkeypatch: Any,
) -> None:
    """Guard the tribe-keyed skip: hint-awareness must not widen the gate."""
    app = _JumpApp(_agents(), monkeypatch)
    apple, pear = _panels(app)
    keys = set(app._panel_group.panel_keys)

    assert app._refresh_affected_panel_widgets(keys)
    assert app._refresh_affected_panel_widgets(keys)
    app._refresh_panel_widgets(jump_hints=None)

    assert (apple.update_list_calls, pear.update_list_calls) == (1, 1)  # type: ignore[attr-defined]


def _capture_footer() -> tuple[KeybindingFooter, list[tuple[Any, Any]]]:
    footer = KeybindingFooter()
    captured: list[tuple[Any, Any]] = []

    def _capture(bindings: Any, mode_label: Any = None) -> None:
        captured.append((list(bindings), mode_label))

    footer._update_display = _capture  # type: ignore[method-assign]
    return footer, captured


class _FakeDetail:
    """Just enough ``AgentDetail`` for the ordinary-bindings footer branch."""

    llm_calls_detail_level = 1

    def is_file_visible(self) -> bool:
        return False

    def is_llm_calls_visible(self) -> bool:
        return False


def test_footer_only_refresh_keeps_jump_bindings_while_jump_mode_is_active(
    monkeypatch: Any,
) -> None:
    app = _JumpApp(_agents(), monkeypatch)
    footer, captured = _capture_footer()
    app._widgets["#keybinding-footer"] = footer
    app._widgets["#agent-detail-panel"] = _FakeDetail()
    app._entry_jump_mode_active = True

    app._refresh_agent_footer_bindings_only()

    assert captured == [([("'", "first"), ("<esc>", "cancel")], "JUMP")]

    app._entry_jump_agents_anchor_stack = [object()]
    captured.clear()

    app._refresh_agent_footer_bindings_only()

    assert captured == [([("'", "back"), ("<esc>", "cancel")], "JUMP")]


def test_footer_only_refresh_restores_agent_bindings_after_jump_mode(
    monkeypatch: Any,
) -> None:
    app = _JumpApp(_agents(), monkeypatch)
    footer, captured = _capture_footer()
    app._widgets["#keybinding-footer"] = footer
    app._widgets["#agent-detail-panel"] = _FakeDetail()
    app._entry_jump_mode_active = True
    app._refresh_agent_footer_bindings_only()
    captured.clear()

    app._entry_jump_mode_active = False
    app._refresh_agent_footer_bindings_only()

    assert captured
    assert all(label != "JUMP" for _bindings, label in captured)
