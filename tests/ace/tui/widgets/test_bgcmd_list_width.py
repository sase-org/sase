"""Dynamic-width and no-wrap behavior for the AXE sidebar (Phase 1).

Pinned by the AXE-tab visual redesign plan (sdd/plans/202605/
axe_tab_visual_redesign.md). The sidebar must:

* compute a natural width from its widest formatted row so long
  lumberjack/chop/bgcmd labels do not get chopped at the previous
  ``max-width: 50`` clamp;
* render every row as a no-wrap Rich ``Text`` so labels never wrap onto
  a second line; and
* post a :class:`BgCmdList.WidthChanged` message after each
  ``update_list`` call so the AXE container can resize.
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
)


def _bg_info(command: str) -> BackgroundCommandInfo:
    return BackgroundCommandInfo(
        command=command,
        project="proj",
        workspace_num=0,
        workspace_dir="/tmp",
        started_at="2026-05-11T00:00:00",
    )


class _Host(App):
    def compose(self) -> ComposeResult:
        yield BgCmdList(id="bgcmd-list")


def _option_text(option: Option) -> Text:
    assert isinstance(option.prompt, Text)
    return option.prompt


async def test_long_lumberjack_label_requests_wider_panel() -> None:
    """A long lumberjack name should drive the requested width past the
    previous fixed ``max-width: 50`` cap."""
    long_name = "extremely-long-lumberjack-name-that-must-not-wrap-in-the-sidebar"
    items: list[AxeItem] = [LumberjackItem(name=long_name)]
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
            lumberjack_names=[long_name],
            bgcmd_infos={},
            lumberjack_statuses={long_name: None},
            bgcmd_running={},
        )

    assert posted, "BgCmdList must post a WidthChanged message"
    # Long label + status marker + comfort padding should exceed the old
    # fixed max-width of 50.
    assert posted[-1].width > 50
    assert widget._requested_width == posted[-1].width
    assert widget._target_width >= len(long_name)


async def test_long_chop_label_requests_wider_panel() -> None:
    """A long chop child label should drive the requested width past 50."""
    chop = "really-long-chop-name-that-needs-room-to-breathe"
    items: list[AxeItem] = [
        LumberjackItem(name="lj"),
        ChopItem(lumberjack_name="lj", chop_name=chop),
    ]
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
            bgcmd_infos={},
            lumberjack_statuses={"lj": None},
            bgcmd_running={},
        )

    assert posted, "BgCmdList must post a WidthChanged message"
    assert posted[-1].width > 50


async def test_long_bgcmd_label_is_not_truncated_in_text() -> None:
    """Background command labels must keep their full text in the
    underlying Rich ``Text`` so the dynamic width can grow to fit them
    instead of falling back to the old 25-character truncation."""
    long_cmd = "a-really-long-background-command-with-many-arguments --flag value"
    info = _bg_info(long_cmd)

    items: list[AxeItem] = [BgCmdItem(slot=1)]
    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=[],
            bgcmd_infos={1: info},
            lumberjack_statuses={},
            bgcmd_running={1: True},
        )

        option = widget.get_option_at_index(0)
        text = _option_text(option)
        assert long_cmd in text.plain, (
            f"Expected full bgcmd label to be present in row text, got: {text.plain!r}"
        )
        assert widget._requested_width > 50


async def test_all_row_text_is_no_wrap() -> None:
    """Every rendered sidebar row Text must declare ``no_wrap=True`` so
    Textual's option list cannot break a label across two lines, even
    when the panel is narrower than the formatted row."""
    long_name = "lumberjack-with-a-very-long-name-XXXXXXXXXXXX"
    long_chop = "chop-with-a-very-long-name-YYYYYYYYYYYY"
    info = _bg_info("long-bgcmd-name-ZZZZZZZZZZZZZZZZZ")
    items: list[AxeItem] = [
        LumberjackItem(name=long_name),
        ChopItem(lumberjack_name=long_name, chop_name=long_chop),
        BgCmdItem(slot=2),
    ]

    app = _Host()
    async with app.run_test():
        widget = app.query_one(BgCmdList)
        widget.update_list(
            items=items,
            current_idx=0,
            axe_running=False,
            lumberjack_names=[long_name],
            bgcmd_infos={2: info},
            lumberjack_statuses={long_name: None},
            bgcmd_running={2: False},
        )

        for i in range(len(items)):
            text = _option_text(widget.get_option_at_index(i))
            assert text.no_wrap is True, (
                f"Row {i} text should be no_wrap; got no_wrap={text.no_wrap!r}"
            )


async def test_update_list_posts_width_changed_message() -> None:
    """``update_list`` must always post a WidthChanged message — even for
    a short label — so the container resizes back down when long rows
    disappear."""
    items: list[AxeItem] = [LumberjackItem(name="lj")]
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
            bgcmd_infos={},
            lumberjack_statuses={"lj": None},
            bgcmd_running={},
        )

    assert len(posted) == 1
    assert posted[0].width > 0
