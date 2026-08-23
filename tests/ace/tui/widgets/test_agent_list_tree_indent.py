"""Agents-tab tree indent colors follow hierarchy depth."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets._agent_list_rendering import (
    AgentRenderCache,
    cached_format_agent_option,
    format_agent_option,
)
from sase.ace.tui.widgets._agent_list_styling import _TREE_DEPTH_COLORS
from tests.ace.tui.widgets._agent_display_helpers import make_agent

from ._agent_render_cache_helpers import style_at as _style_at


def _row(*, tree_depth: int, is_selected: bool = False) -> Text:
    agent = make_agent(
        cl_name="child",
        agent_name="child",
        parent_timestamp="20260823000000",
        llm_provider=None,
    )
    agent.tree_depth = tree_depth
    left, _, _ = format_agent_option(agent, 0, is_selected=is_selected)
    return left


def _connector_styles(text: Text) -> list[str]:
    styles: list[str] = []
    for span in text.spans:
        fragment = text.plain[span.start : span.end]
        if "│" in fragment or "└" in fragment:
            styles.append(str(span.style))
    return styles


def test_root_row_has_no_tree_indent() -> None:
    agent = make_agent(cl_name="root", agent_name="root", llm_provider=None)
    left, _, _ = format_agent_option(agent, 0, is_selected=False)

    assert not left.plain.startswith(" ")
    assert "└" not in left.plain
    assert "│" not in left.plain
    assert _connector_styles(left) == []


def test_depth_1_prefix_uses_sky_blue_branch() -> None:
    left = _row(tree_depth=1)

    assert left.plain.startswith("  └─ ")
    assert "│" not in left.plain
    assert _style_at(left, left.plain.index("└")) == _TREE_DEPTH_COLORS[0]
    assert _connector_styles(left) == [_TREE_DEPTH_COLORS[0]]


def test_depth_2_prefix_keeps_level_1_guide_and_level_2_branch() -> None:
    left = _row(tree_depth=2)

    assert left.plain.startswith("  │  └─ ")
    assert _style_at(left, left.plain.index("│")) == _TREE_DEPTH_COLORS[0]
    assert _style_at(left, left.plain.index("└")) == _TREE_DEPTH_COLORS[1]
    assert _connector_styles(left) == [_TREE_DEPTH_COLORS[0], _TREE_DEPTH_COLORS[1]]


def test_depth_3_row_carries_three_ordered_colors() -> None:
    left = _row(tree_depth=3)
    guides = [index for index, char in enumerate(left.plain) if char == "│"]

    assert left.plain.startswith("  │  │  └─ ")
    assert len(guides) == 2
    assert _style_at(left, guides[0]) == _TREE_DEPTH_COLORS[0]
    assert _style_at(left, guides[1]) == _TREE_DEPTH_COLORS[1]
    assert _style_at(left, left.plain.index("└")) == _TREE_DEPTH_COLORS[2]
    assert _connector_styles(left) == list(_TREE_DEPTH_COLORS[:3])


def test_selected_connectors_are_bold_and_never_dim() -> None:
    unselected = _row(tree_depth=3, is_selected=False)
    selected = _row(tree_depth=3, is_selected=True)

    assert selected.plain.startswith(unselected.plain[: len("  │  │  └─ ")])
    expected = [f"bold {color}" for color in _TREE_DEPTH_COLORS[:3]]
    assert _connector_styles(selected) == expected
    for style in _connector_styles(selected):
        assert "dim" not in style.lower()
        assert "bold" in style.lower()
    for style in _connector_styles(unselected):
        assert "dim" not in style.lower()
        assert "bold" not in style.lower()


def test_depth_beyond_palette_cycles_deterministically() -> None:
    palette = _TREE_DEPTH_COLORS
    left = _row(tree_depth=len(palette) + 1)
    guides = [index for index, char in enumerate(left.plain) if char == "│"]

    assert left.plain.startswith("  " + ("│  " * len(palette)) + "└─ ")
    assert len(guides) == len(palette)
    assert _style_at(left, guides[0]) == palette[0]
    assert _style_at(left, guides[-1]) == palette[-1]
    assert _style_at(left, left.plain.index("└")) == palette[0]
    assert _connector_styles(left) == [*palette, palette[0]]


def test_selected_and_unselected_tree_renders_do_not_alias_in_cache() -> None:
    cache = AgentRenderCache()
    agent = make_agent(
        cl_name="child",
        agent_name="child",
        parent_timestamp="20260823000000",
        llm_provider=None,
    )
    agent.tree_depth = 2

    unselected = cached_format_agent_option(cache, agent, 0, is_selected=False)
    selected = cached_format_agent_option(cache, agent, 0, is_selected=True)
    selected_again = cached_format_agent_option(cache, agent, 0, is_selected=True)

    assert unselected[0] is not selected[0]
    assert selected[0] is selected_again[0]
    unselected_branch = _style_at(unselected[0], unselected[0].plain.index("└"))
    selected_branch = _style_at(selected[0], selected[0].plain.index("└"))
    assert unselected_branch == _TREE_DEPTH_COLORS[1]
    assert selected_branch == f"bold {_TREE_DEPTH_COLORS[1]}"
