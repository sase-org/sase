"""Pure layout tests for the split-button Prompts tab bar."""

from __future__ import annotations

from rich.cells import cell_len

from sase.ace.tui.modals.prompts_tab_bar import (
    PromptsTabBarState,
    _layout_prompts_tab_bar,
)


def _state(
    surface: str, stash: int = 3, trash: int = 2, limit: int = 100
) -> PromptsTabBarState:
    return PromptsTabBarState(
        surface=surface, stash_count=stash, trash_count=trash, trash_limit=limit
    )


def _styles(layout) -> list[str]:
    return [span.style or "" for span in layout.text.spans]


def test_stash_surface_pill_and_secondary() -> None:
    layout = _layout_prompts_tab_bar(_state("stash"), 120)
    assert layout.tier == "full"
    plain = layout.text.plain
    assert "≡ Stash 3" in plain
    assert "🗑️ 2" in plain
    assert "↺ History" in plain
    styles = _styles(layout)
    assert any("#FF87D7" in s and "#1a1a1a" in s for s in styles)
    # Quiet trash secondary keeps its #303030 background.
    assert any("#303030" in s and "#bcbcbc" in s for s in styles)


def test_trash_surface_moves_fill_and_expands_label() -> None:
    layout = _layout_prompts_tab_bar(_state("trash"), 120)
    assert layout.tier == "full"
    assert "🗑️ Trash 2/100" in layout.text.plain
    styles = _styles(layout)
    assert any("#EBC04F" in s and "#1a1a1a" in s for s in styles)
    # Stash becomes the parent crumb.
    assert any("#FF87D7" in s and "#303030" in s for s in styles)


def test_history_surface_flat_stash_segments() -> None:
    layout = _layout_prompts_tab_bar(_state("history"), 120)
    assert layout.tier == "full"
    assert "↺ History" in layout.text.plain
    styles = _styles(layout)
    assert any("#5FD7FF" in s and "#1a1a1a" in s for s in styles)
    # Both Stash segments flat with no background.
    assert any(s == "#8a8a8a" for s in styles)


def test_trash_badge_off_empty_count_full() -> None:
    off = _layout_prompts_tab_bar(_state("stash", trash=5, limit=0), 120)
    assert "off" in off.text.plain
    assert any("#6c6c6c" in s for s in _styles(off))

    empty = _layout_prompts_tab_bar(_state("stash", trash=0, limit=100), 120)
    # Count zero shows the icon alone (no digit after the icon segment).
    assert "🗑️" in empty.text.plain
    assert "🗑️ 1" not in empty.text.plain

    count = _layout_prompts_tab_bar(_state("stash", trash=2, limit=100), 120)
    assert any("#EBC04F" in s for s in _styles(count))

    full = _layout_prompts_tab_bar(_state("stash", trash=100, limit=100), 120)
    assert any("#FF5F5F" in s for s in _styles(full))


def test_active_trash_labels() -> None:
    layout = _layout_prompts_tab_bar(_state("trash", trash=2, limit=100), 120)
    assert "Trash 2/100" in layout.text.plain
    off = _layout_prompts_tab_bar(_state("trash", trash=0, limit=0), 120)
    assert "Trash off" in off.text.plain


def test_hints_per_surface() -> None:
    assert "t trash" in _layout_prompts_tab_bar(_state("stash"), 120).text.plain
    assert "t/esc back" in _layout_prompts_tab_bar(_state("trash"), 120).text.plain
    history_plain = _layout_prompts_tab_bar(_state("history"), 120).text.plain
    assert "[ ] tabs" in history_plain
    assert "t trash" not in history_plain


def test_tier_ladder_and_width_zero_is_full() -> None:
    full = _layout_prompts_tab_bar(_state("stash"), 120)
    assert full.tier == "full"
    assert "t trash" in full.text.plain

    # Narrow to segments-only width: compact has no hints.
    segments_only_width = cell_len(full.text.plain.split("  t trash")[0]) + 5
    compact = _layout_prompts_tab_bar(_state("stash"), segments_only_width)
    if compact.tier == "full":
        # Width still fits full; force compact with a tighter width.
        compact = _layout_prompts_tab_bar(_state("stash"), 40)
    assert compact.tier in ("compact", "micro")
    if compact.tier == "compact":
        assert "Stash 3" in compact.text.plain
        assert "t trash" not in compact.text.plain

    micro = _layout_prompts_tab_bar(_state("stash"), 20)
    assert micro.tier == "micro"
    assert "≡ 3" in micro.text.plain
    assert "Stash" not in micro.text.plain
    assert "History" not in micro.text.plain

    zero = _layout_prompts_tab_bar(_state("stash"), 0)
    assert zero.tier == "full"


def test_hits_cell_accurate_around_emoji() -> None:
    layout = _layout_prompts_tab_bar(_state("stash", stash=3, trash=2, limit=100), 120)
    hits = {sid: (s, e) for s, e, sid in layout.hits}
    assert set(hits) == {"stash", "trash", "history"}
    # Attached split button: trash starts where stash ends.
    assert hits["trash"][0] == hits["stash"][1]
    # History starts after the 3-space gap following the trash segment.
    assert hits["history"][0] == hits["trash"][1] + 3
    # Widths match cell_len (emoji is two cells).
    for start, end, sid in layout.hits:
        assert end - start >= 2
    # The history hit starts after the emoji's two cells: recompute the
    # trash segment cell width and confirm the gap arithmetic.
    stash_len = cell_len(" ≡ Stash 3 ")
    trash_len = cell_len(" 🗑️ 2 ")
    assert hits["stash"] == (0, stash_len)
    assert hits["trash"] == (stash_len, stash_len + trash_len)


def test_hover_brightening() -> None:
    base = _layout_prompts_tab_bar(_state("stash"), 120)
    assert not any("#d0d0d0" in s for s in _styles(base))
    hovered = _layout_prompts_tab_bar(_state("stash"), 120, hover="history")
    assert any("#d0d0d0" in s for s in _styles(hovered))
