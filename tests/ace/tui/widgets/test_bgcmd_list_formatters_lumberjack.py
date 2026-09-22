"""Lumberjack row formatters for the AXE sidebar (Phase 2).

Covers the top-level accent bar, the gold name hue, the cycles/errors
status chip, and the overrun roll-up chip. See
``_bgcmd_list_formatters_helpers.py`` for the full row-taxonomy
rationale pinned by the AXE-tab visual redesign plan.
"""

from __future__ import annotations

from sase.ace.tui.widgets.bgcmd_list import (
    AxeItem,
    BgCmdList,
    LumberjackItem,
)
from sase.axe.state import LumberjackStatus
from tests.ace.tui.widgets._bgcmd_list_formatters_helpers import (
    _Host,
    _make_status,
    _option_text,
    _styles_in,
)


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


async def test_lumberjack_rollup_chip_precedes_cycles_chip() -> None:
    """The ``⚠N`` roll-up chip is placed before the cycles/errors chip."""
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
            lumberjack_overruns={"hooks": 2},
        )

        text = _option_text(widget.get_option_at_index(0))
        plain = text.plain

    assert "⚠2" in plain, f"expected roll-up chip '⚠2': {plain!r}"
    assert plain.index("⚠2") < plain.index("7c"), (
        f"roll-up chip must precede cycles chip: {plain!r}"
    )


async def test_lumberjack_rollup_chip_absent_when_zero() -> None:
    """No roll-up chip renders when the lumberjack has zero over chops."""
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
            lumberjack_overruns={"hooks": 0},
        )

        text = _option_text(widget.get_option_at_index(0))

    assert "⚠" not in text.plain
