"""Row-formatter visual hierarchy for the AXE sidebar (Phase 2).

Pinned by the AXE-tab visual redesign plan (sdd/plans/202605/
axe_tab_visual_redesign.md). The three row taxonomies (lumberjack,
chop, bgcmd) must be visually distinguishable at a glance:

* lumberjack rows carry a strong top-level accent in the gold hue;
* chop rows render with a tree-style connector and a subordinate
  dim-gold/copper colour;
* bgcmd rows wear a distinct cyan slot badge so user/background
  commands cannot be mistaken for AXE-managed lumberjack rows;
* when both AXE-managed and bgcmd rows are present, the first bgcmd
  row carries a leading divider line that separates the user-commands
  group from the lumberjack tree above.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets.option_list import Option

from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.widgets.bgcmd_list import (
    AxeItem,
    BgCmdItem,
    BgCmdList,
    ChopItem,
    LumberjackItem,
    _DIVIDER_LABEL,
)
from sase.axe.state import LumberjackStatus


def _bg_info(command: str) -> BackgroundCommandInfo:
    return BackgroundCommandInfo(
        command=command,
        project="proj",
        workspace_num=0,
        workspace_dir="/tmp",
        started_at="2026-05-11T00:00:00",
    )


def _make_status(name: str, status: str = "running") -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=4242,
        started_at="2026-05-09T10:00:00",
        status=status,  # type: ignore[arg-type]
        interval=60,
        chops=[],
        last_cycle="2026-05-09T10:05:00",
        cycles_run=7,
        errors_encountered=0,
        uptime_seconds=300,
    )


class _Host(App):
    def compose(self) -> ComposeResult:
        yield BgCmdList(id="bgcmd-list")


def _option_text(option: Option) -> Text:
    assert isinstance(option.prompt, Text)
    return option.prompt


def _styles_in(text: Text) -> set[str]:
    return {str(span.style) for span in text.spans}


async def test_lumberjack_row_has_top_level_accent_and_gold_name() -> None:
    """A lumberjack row should carry a strong left accent bar in the
    gold taxonomy colour plus a gold-styled name span."""
    items: list[AxeItem] = [LumberjackItem(name="hooks")]
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

        text = _option_text(widget.get_option_at_index(0))
        plain = text.plain

    # Top-level accent bar must appear before the status marker.
    assert "▌" in plain, f"expected lumberjack accent bar in row: {plain!r}"
    assert plain.index("▌") < plain.index("["), (
        f"accent bar must precede status marker: {plain!r}"
    )
    assert "hooks" in plain
    styles = _styles_in(text)
    assert any("#FFD700" in style for style in styles), (
        f"lumberjack row must use gold (#FFD700) somewhere; got {styles}"
    )


async def test_lumberjack_row_status_chip_shows_cycle_count() -> None:
    """When a status reports recorded cycles, the row should append a
    compact ``Nc`` chip so the user gets a sense of activity without
    leaving the sidebar."""
    items: list[AxeItem] = [LumberjackItem(name="hooks")]
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

        text = _option_text(widget.get_option_at_index(0))
        assert "7c" in text.plain, f"expected cycles chip '7c' in row: {text.plain!r}"


async def test_lumberjack_row_status_chip_shows_errors_when_nonzero() -> None:
    """A non-zero error count should win over the cycles chip and use
    the red severity colour so errors stand out at a glance."""
    err_status = LumberjackStatus(
        name="hooks",
        pid=42,
        started_at="2026-05-09T10:00:00",
        status="error",
        interval=60,
        chops=[],
        cycles_run=5,
        errors_encountered=3,
    )
    items: list[AxeItem] = [LumberjackItem(name="hooks")]
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=["hooks"],
            bgcmd_infos={},
            lumberjack_statuses={"hooks": err_status},
            bgcmd_running={},
        )

        text = _option_text(widget.get_option_at_index(0))
        assert "3e" in text.plain
        # Error chip span must include a red style.
        assert any(
            "red" in str(span.style) and "3e" == text.plain[span.start : span.end]
            for span in text.spans
        ), f"expected red 3e chip; got spans={text.spans}"


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


async def test_bgcmd_row_uses_slot_badge_and_cyan_command_label() -> None:
    """A bgcmd row carries a ``#N`` slot badge and a cyan command label,
    so it cannot be confused with the gold lumberjack/chop rows."""
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
    styles = _styles_in(text)
    assert any("#5FD7FF" in style for style in styles), (
        f"bgcmd row should use the cyan hue #5FD7FF; got {styles}"
    )


async def test_bgcmd_row_done_state_uses_check_marker_and_dim_label() -> None:
    """A completed bgcmd row should show the ``[✓]`` marker and a
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
