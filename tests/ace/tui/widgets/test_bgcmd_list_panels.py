"""Two-panel behavior of the Services-tab ``BgCmdList`` widget.

Pins the Phase 1 contract: panel-local indices, ``clear_highlight``, the
disabled empty placeholder, ``rendered_line_count``, title-driven width,
and ``panel_key`` on ``SelectionChanged``.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.widgets.bgcmd_list import (
    AxeItem,
    BgCmdItem,
    BgCmdList,
    LumberjackItem,
    ServiceProcItem,
)


class _Host(App):
    def compose(self) -> ComposeResult:
        yield BgCmdList(panel_key="service_procs", id="procs")
        yield BgCmdList(panel_key="user_routines", id="routines")


def _paint(
    widget: BgCmdList,
    items: list[AxeItem],
    current_idx: int,
    **kwargs,
) -> None:
    widget.update_list(
        items=items,
        current_idx=current_idx,
        axe_running=False,
        lumberjack_names=[],
        bgcmd_infos={},
        lumberjack_statuses={},
        bgcmd_running={},
        **kwargs,
    )


async def test_panel_key_defaults_and_stores() -> None:
    app = _Host()
    async with app.run_test():
        procs = app.query_one("#procs", BgCmdList)
        routines = app.query_one("#routines", BgCmdList)
        assert procs.panel_key == "service_procs"
        assert routines.panel_key == "user_routines"
        assert BgCmdList.SelectionChanged(0).panel_key == "service_procs"


async def test_negative_index_clears_highlight() -> None:
    app = _Host()
    async with app.run_test():
        widget = app.query_one("#procs", BgCmdList)
        _paint(widget, [ServiceProcItem(name="scheduler")], 0)
        assert widget.highlighted == 0
        _paint(widget, [ServiceProcItem(name="scheduler")], -1)
        assert widget.highlighted is None


async def test_clear_highlight() -> None:
    app = _Host()
    async with app.run_test():
        widget = app.query_one("#procs", BgCmdList)
        _paint(widget, [ServiceProcItem(name="scheduler")], 0)
        widget.clear_highlight()
        assert widget.highlighted is None
        assert widget._programmatic_update is False


async def test_empty_placeholder_is_disabled_and_uncounted() -> None:
    app = _Host()
    async with app.run_test():
        widget = app.query_one("#routines", BgCmdList)
        _paint(widget, [], -1, empty_placeholder=Text("No routines", style="dim"))
        assert widget._item_count == 0
        assert widget.rendered_line_count == 1
        assert widget.highlighted is None
        option = widget.get_option_at_index(0)
        assert option.disabled is True


async def test_placeholder_never_emits_selection_changed() -> None:
    app = _Host()
    async with app.run_test():
        widget = app.query_one("#routines", BgCmdList)
        _paint(widget, [], -1, empty_placeholder=Text("No routines", style="dim"))
        posted: list[BgCmdList.SelectionChanged] = []
        original_post = widget.post_message

        def _spy(message: object) -> bool:
            if isinstance(message, BgCmdList.SelectionChanged):
                posted.append(message)
            return original_post(message)  # type: ignore[arg-type]

        widget.post_message = _spy  # type: ignore[method-assign]
        option = widget.get_option_at_index(0)
        widget.on_option_list_option_highlighted(
            OptionList.OptionHighlighted(widget, option, 0)
        )
        widget.on_option_list_option_selected(
            OptionList.OptionSelected(widget, option, 0)
        )
        assert posted == []


async def test_selection_changed_carries_panel_key() -> None:
    app = _Host()
    async with app.run_test():
        widget = app.query_one("#routines", BgCmdList)
        _paint(widget, [LumberjackItem(name="hooks")], -1)
        posted: list[BgCmdList.SelectionChanged] = []
        original_post = widget.post_message

        def _spy(message: object) -> bool:
            if isinstance(message, BgCmdList.SelectionChanged):
                posted.append(message)
            return original_post(message)  # type: ignore[arg-type]

        widget.post_message = _spy  # type: ignore[method-assign]
        option = widget.get_option_at_index(0)
        widget.on_option_list_option_selected(
            OptionList.OptionSelected(widget, option, 0)
        )
        assert [msg.panel_key for msg in posted] == ["user_routines"]
        assert [msg.index for msg in posted] == [0]


async def test_rendered_line_count_includes_divider() -> None:
    from sase.ace.tui.bgcmd import BackgroundCommandInfo

    info = BackgroundCommandInfo(
        command="make docs",
        project="proj",
        workspace_num=0,
        workspace_dir="/tmp",
        started_at="2026-05-11T00:00:00",
    )
    app = _Host()
    async with app.run_test():
        widget = app.query_one("#procs", BgCmdList)
        widget.update_list(
            items=[ServiceProcItem(name="scheduler"), BgCmdItem(slot=1)],
            current_idx=0,
            axe_running=False,
            lumberjack_names=[],
            bgcmd_infos={1: info},
            lumberjack_statuses={},
            bgcmd_running={1: False},
        )
        assert widget.rendered_line_count == 3


async def test_title_width_drives_requested_width_once() -> None:
    app = _Host()
    async with app.run_test():
        widget = app.query_one("#procs", BgCmdList)
        _paint(widget, [ServiceProcItem(name="x")], 0)
        posted: list[BgCmdList.WidthChanged] = []
        original_post = widget.post_message

        def _spy(message: object) -> bool:
            if isinstance(message, BgCmdList.WidthChanged):
                posted.append(message)
            return original_post(message)  # type: ignore[arg-type]

        widget.post_message = _spy  # type: ignore[method-assign]
        baseline = widget._requested_width
        widget.update_border_title(Text("⚙ Service Procs · 3 [R3] ▷1 ✓1"))
        assert widget._requested_width >= baseline
        assert len(posted) == 1
        # An identical title must not re-post.
        widget.update_border_title(Text("⚙ Service Procs · 3 [R3] ▷1 ✓1"))
        assert len(posted) == 1
