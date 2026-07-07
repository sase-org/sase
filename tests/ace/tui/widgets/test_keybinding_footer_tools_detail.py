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
