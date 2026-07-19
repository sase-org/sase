from __future__ import annotations

from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter
from sase.ace.tui.widgets.tools_panel import ToolDetailLevel


def _labels(bindings: list[tuple[str, str]]) -> set[tuple[str, str]]:
    return set(bindings)


def test_footer_tools_detail_chips_follow_level() -> None:
    footer = KeybindingFooter()

    compact = _labels(
        footer._compute_agent_bindings(
            None,
            tools_visible=True,
            tools_detail_level=ToolDetailLevel.COMPACT,
        )
    )
    expanded = _labels(
        footer._compute_agent_bindings(
            None,
            tools_visible=True,
            tools_detail_level=ToolDetailLevel.EXPANDED,
        )
    )
    full = _labels(
        footer._compute_agent_bindings(
            None,
            tools_visible=True,
            tools_detail_level=ToolDetailLevel.FULL,
        )
    )
    hidden = _labels(
        footer._compute_agent_bindings(
            None,
            tools_visible=False,
            tools_detail_level=ToolDetailLevel.EXPANDED,
        )
    )

    assert ("l", "more detail") in compact
    assert ("h", "less detail") not in compact
    assert ("l", "more detail") in expanded
    assert ("h", "less detail") in expanded
    assert ("l", "more detail") not in full
    assert ("h", "less detail") in full
    assert ("l", "more detail") not in hidden
    assert ("h", "less detail") not in hidden


def test_footer_without_selected_agent_omits_agent_only_actions() -> None:
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(
        None,
        completed_count=3,
        marked_count=0,
    )
    labels = {label for _key, label in bindings}

    assert labels == {"cleanup (3 done)"}
    assert labels.isdisjoint(
        {"retry", "dismiss", "kill", "edit chat", "edit tribe", "tmux"}
    )


def test_footer_selected_panel_advertises_only_panel_action() -> None:
    footer = KeybindingFooter()

    expanded = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_collapsed=False,
        )
    )
    collapsed = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_collapsed=True,
        )
    )

    assert ("H", "only panel") in expanded
    assert ("H", "only panel") in collapsed


def test_footer_armed_panel_isolation_advertises_restore_action() -> None:
    footer = KeybindingFooter()

    bindings = _labels(
        footer._compute_agent_bindings(
            None,
            panel_focused=True,
            panel_restore_armed=True,
        )
    )

    assert ("H", "restore panels") in bindings
    assert ("H", "only panel") not in bindings
