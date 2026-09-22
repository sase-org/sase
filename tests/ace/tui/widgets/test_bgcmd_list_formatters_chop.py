"""Chop row formatters for the AXE sidebar (Phase 2).

Covers the tree connector, the subordinate chop hue, and the overrun
chips. See ``_bgcmd_list_formatters_helpers.py`` for the full
row-taxonomy rationale pinned by the AXE-tab visual redesign plan.
"""

from __future__ import annotations

from sase.ace.tui.widgets.bgcmd_list import (
    AxeItem,
    BgCmdList,
    ChopItem,
    LumberjackItem,
)
from tests.ace.tui.widgets._bgcmd_list_formatters_helpers import (
    _Host,
    _chop_snapshot,
    _make_status,
    _option_text,
    _overrun,
    _styles_in,
)


async def test_chop_row_uses_tree_connector_and_subordinate_colour() -> None:
    """A chop row must render a tree connector under its lumberjack and
    use a colour distinct from the bold lumberjack hue so the parent
    relationship reads visually."""
    items: list[AxeItem] = [
        LumberjackItem(name="hooks"),
        ChopItem(lumberjack_name="hooks", chop_name="fast_lint"),
    ]
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=["hooks"],
            bgcmd_infos={},
            lumberjack_statuses={"hooks": _make_status("hooks")},
            bgcmd_running={},
        )

        chop_text = _option_text(widget.get_option_at_index(1))
        plain = chop_text.plain

    assert "└─" in plain, f"chop row must include tree connector: {plain!r}"
    assert "fast_lint" in plain
    styles = _styles_in(chop_text)
    # Subordinate hue is #D7AF87 (dim copper) for the chop name.
    assert any("#D7AF87" in style for style in styles), (
        f"chop row should use the subordinate hue #D7AF87; got {styles}"
    )


async def test_chop_row_shows_bold_amber_chip_when_over() -> None:
    """An ``over`` chop shows a bold-amber worst-ratio chip after its name."""
    items: list[AxeItem] = [
        LumberjackItem(name="hooks"),
        ChopItem(lumberjack_name="hooks", chop_name="fast_lint"),
    ]
    snap = _chop_snapshot(overrun=_overrun("over", worst_ratio=4.0))
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=["hooks"],
            bgcmd_infos={},
            lumberjack_statuses={"hooks": _make_status("hooks")},
            bgcmd_running={},
            chop_snapshots={("hooks", "fast_lint"): snap},
        )

        text = _option_text(widget.get_option_at_index(1))

    assert "⚠ 4.0×" in text.plain
    over_spans = [
        str(span.style)
        for span in text.spans
        if "⚠ 4.0×" in text.plain[span.start : span.end]
    ]
    assert over_spans and all("bold #FFAF5F" in style for style in over_spans)


async def test_chop_row_shows_dim_amber_chip_when_intermittent() -> None:
    """An ``intermittent`` chop shows the same chip but dim, not bold."""
    items: list[AxeItem] = [
        LumberjackItem(name="hooks"),
        ChopItem(lumberjack_name="hooks", chop_name="fast_lint"),
    ]
    snap = _chop_snapshot(overrun=_overrun("intermittent", worst_ratio=1.2))
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=["hooks"],
            bgcmd_infos={},
            lumberjack_statuses={"hooks": _make_status("hooks")},
            bgcmd_running={},
            chop_snapshots={("hooks", "fast_lint"): snap},
        )

        text = _option_text(widget.get_option_at_index(1))

    assert "⚠ 1.2×" in text.plain
    chip_spans = [
        str(span.style)
        for span in text.spans
        if "⚠ 1.2×" in text.plain[span.start : span.end]
    ]
    assert chip_spans and all("dim #FFAF5F" in style for style in chip_spans)


async def test_chop_row_omits_chip_when_level_none() -> None:
    """A healthy chop (level ``none``) never shows an overrun chip."""
    items: list[AxeItem] = [
        LumberjackItem(name="hooks"),
        ChopItem(lumberjack_name="hooks", chop_name="fast_lint"),
    ]
    snap = _chop_snapshot(overrun=_overrun("none", worst_ratio=None, latest_ratio=None))
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=["hooks"],
            bgcmd_infos={},
            lumberjack_statuses={"hooks": _make_status("hooks")},
            bgcmd_running={},
            chop_snapshots={("hooks", "fast_lint"): snap},
        )

        text = _option_text(widget.get_option_at_index(1))

    assert "⚠" not in text.plain


async def test_disabled_chop_never_shows_overrun_chip() -> None:
    """A disabled chop never gets a chip even if a stale verdict lingers."""
    items: list[AxeItem] = [
        LumberjackItem(name="hooks"),
        ChopItem(lumberjack_name="hooks", chop_name="fast_lint"),
    ]
    snap = _chop_snapshot(enabled=False, overrun=_overrun("over", worst_ratio=4.0))
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=["hooks"],
            bgcmd_infos={},
            lumberjack_statuses={"hooks": _make_status("hooks")},
            bgcmd_running={},
            chop_snapshots={("hooks", "fast_lint"): snap},
        )

        text = _option_text(widget.get_option_at_index(1))

    assert "⚠" not in text.plain
    assert "disabled" in text.plain
