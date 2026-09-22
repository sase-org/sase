"""Bgcmd row formatters and the oneshots divider for the AXE sidebar.

Covers the running/done oneshot glyphs and hues, the one-time
``── oneshots ──`` divider separating oneshots from the AXE tree, and
the cross-taxonomy hue check. See
``_bgcmd_list_formatters_helpers.py`` for the full row-taxonomy
rationale pinned by the AXE-tab visual redesign plan.
"""

from __future__ import annotations

from sase.ace.tui.widgets.bgcmd_list import (
    _DIVIDER_LABEL,
    AxeItem,
    BgCmdItem,
    BgCmdList,
    ChopItem,
    LumberjackItem,
)
from tests.ace.tui.widgets._bgcmd_list_formatters_helpers import (
    _bg_info,
    _Host,
    _make_status,
    _option_text,
    _styles_in,
)


async def test_bgcmd_row_uses_slot_badge_and_muted_running_label() -> None:
    """A running oneshot row carries a ``▷`` glyph, a ``#N`` slot badge, and
    a muted teal command label, so it cannot be confused with the gold
    lumberjack/chop rows."""
    info = _bg_info("just test --visual")
    items: list[AxeItem] = [BgCmdItem(slot=3)]
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=[],
            bgcmd_infos={3: info},
            lumberjack_statuses={},
            bgcmd_running={3: True},
        )

        text = _option_text(widget.get_option_at_index(0))
        plain = text.plain

    assert "#3" in plain, f"bgcmd row must include slot badge '#3': {plain!r}"
    assert "just test --visual" in plain
    assert plain.startswith("▷ #3 ")
    styles = _styles_in(text)
    # The row is the highlighted one, so its label takes the bold selected teal.
    assert any("#87D7D7" in style for style in styles), (
        f"running oneshot label should use the muted teal #87D7D7; got {styles}"
    )
    assert not any("#FFD700" in style for style in styles), (
        f"oneshot rows must not borrow the gold lumberjack hue; got {styles}"
    )


async def test_bgcmd_row_done_state_uses_check_marker_and_dim_label() -> None:
    """A completed oneshot row should show the ``✓`` glyph and a
    dimmer label style to subordinate it visually to running rows."""
    info = _bg_info("just check")
    items: list[AxeItem] = [BgCmdItem(slot=2)]
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=[],
            bgcmd_infos={2: info},
            lumberjack_statuses={},
            bgcmd_running={2: False},
        )

        text = _option_text(widget.get_option_at_index(0))
        assert "✓" in text.plain
        styles = _styles_in(text)
        assert any("#87AFAF" in style for style in styles), (
            f"done bgcmd row should use the dim cyan/teal hue #87AFAF; got {styles}"
        )


async def test_first_bgcmd_row_renders_divider_when_mixed_with_axe_rows() -> None:
    """When lumberjack/chop rows coexist with bgcmds, the first bgcmd
    row should carry a leading divider line so the two row families
    are visually grouped."""
    info = _bg_info("just check")
    items: list[AxeItem] = [
        LumberjackItem(name="hooks"),
        BgCmdItem(slot=1),
        BgCmdItem(slot=2),
    ]
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=["hooks"],
            bgcmd_infos={1: info, 2: info},
            lumberjack_statuses={"hooks": _make_status("hooks")},
            bgcmd_running={1: True, 2: False},
        )

        first_bgcmd_text = _option_text(widget.get_option_at_index(1))
        second_bgcmd_text = _option_text(widget.get_option_at_index(2))

    # First bgcmd row must include the divider label followed by a
    # newline before the data line.
    assert _DIVIDER_LABEL in first_bgcmd_text.plain, (
        f"first bgcmd row must include divider label: {first_bgcmd_text.plain!r}"
    )
    assert "\n" in first_bgcmd_text.plain, (
        f"first bgcmd row must split divider from content with a newline: "
        f"{first_bgcmd_text.plain!r}"
    )
    # Second bgcmd row must NOT include the divider — it is a one-time
    # spacer at the boundary, not a per-row decoration.
    assert _DIVIDER_LABEL not in second_bgcmd_text.plain, (
        f"second bgcmd row should not repeat divider: {second_bgcmd_text.plain!r}"
    )


async def test_divider_omitted_when_only_bgcmds() -> None:
    """When the sidebar contains only bgcmd rows (no lumberjacks/chops),
    no divider is needed and none should be rendered."""
    info = _bg_info("just check")
    items: list[AxeItem] = [BgCmdItem(slot=1), BgCmdItem(slot=2)]
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=[],
            bgcmd_infos={1: info, 2: info},
            lumberjack_statuses={},
            bgcmd_running={1: True, 2: False},
        )

        for idx in range(2):
            text = _option_text(widget.get_option_at_index(idx))
            assert _DIVIDER_LABEL not in text.plain, (
                f"row {idx} should not include divider when no axe rows present"
            )


async def test_divider_omitted_when_only_axe_rows() -> None:
    """When the sidebar has only lumberjack/chop rows, no divider should
    appear anywhere — the divider exists solely to separate user
    commands from the AXE tree."""
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

        for idx in range(2):
            text = _option_text(widget.get_option_at_index(idx))
            assert _DIVIDER_LABEL not in text.plain


async def test_divider_does_not_inflate_requested_width() -> None:
    """The divider line is a visual spacer — it should not be included
    in the natural row-width calculation that drives the WidthChanged
    event. Otherwise a short bgcmd would still demand a wide panel."""
    info = _bg_info("x")
    items: list[AxeItem] = [LumberjackItem(name="lj"), BgCmdItem(slot=1)]

    posted: list[BgCmdList.WidthChanged] = []
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        original_post = widget.post_message

        def _spy(message: object) -> bool:
            if isinstance(message, BgCmdList.WidthChanged):
                posted.append(message)
            return original_post(message)  # type: ignore[arg-type]

        widget.post_message = _spy  # type: ignore[method-assign]

        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=["lj"],
            bgcmd_infos={1: info},
            lumberjack_statuses={"lj": None},
            bgcmd_running={1: True},
        )

    assert posted
    # The longest *content* line is the lumberjack row (the bgcmd row's
    # divider line is ignored). The reported target_width should match
    # the data-only width of the widest row.
    assert widget._target_width < len(_DIVIDER_LABEL) + 10, (
        f"divider line must not drive width; target_width={widget._target_width}"
    )


async def test_each_row_type_uses_distinct_dominant_hue() -> None:
    """The three taxonomies must use visibly different dominant colours
    so a screenshot reader can tell them apart by colour alone."""
    info = _bg_info("just check")
    items: list[AxeItem] = [
        LumberjackItem(name="hooks"),
        ChopItem(lumberjack_name="hooks", chop_name="fast_lint"),
        BgCmdItem(slot=1),
    ]
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=["hooks"],
            bgcmd_infos={1: info},
            lumberjack_statuses={"hooks": _make_status("hooks")},
            bgcmd_running={1: True},
        )

        lj_styles = _styles_in(_option_text(widget.get_option_at_index(0)))
        chop_styles = _styles_in(_option_text(widget.get_option_at_index(1)))
        bg_styles = _styles_in(_option_text(widget.get_option_at_index(2)))

    # Each row family uses its taxonomy hue.
    assert any("#FFD700" in style for style in lj_styles)
    assert any("#D7AF87" in style for style in chop_styles)
    assert any("#5FD7FF" in style for style in bg_styles)
    # And the bgcmd row should NOT lean on the lumberjack gold for its
    # name label — that would defeat the visual distinction.
    bg_text = _option_text(widget.get_option_at_index(2))
    cmd_span_styles = [
        str(span.style)
        for span in bg_text.spans
        if "just check" in bg_text.plain[span.start : span.end]
    ]
    assert cmd_span_styles, "bgcmd row must style the command label"
    assert all("#FFD700" not in style for style in cmd_span_styles), (
        f"bgcmd command label must not use lumberjack gold; got {cmd_span_styles}"
    )
