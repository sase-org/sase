"""Monitor member row rendering tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.ace.tui.widgets._agent_list_styling import (
    _MONITOR_GLYPH_STYLE,
    _MONITOR_ROW_STYLE,
    _MONITOR_SETTLED_COUNT_GLYPH_STYLE,
    _MONITOR_SETTLED_GLYPH_STYLE,
)

from ._agent_list_monitor_rows_helpers import (
    gear_style,
    make_family_container,
    make_monitor,
    make_monitor_starter,
)


def test_monitor_row_uses_glyph_without_label_or_command() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(status="MONITORING", monitor_state="running"),
        0,
        is_selected=False,
    )

    assert "⚙" in left.plain
    assert "just check" not in left.plain
    assert "just check-full" not in left.plain
    assert "MONITORING" in left.plain
    assert "alpha--mon" in left.plain


def test_monitor_starter_row_uses_agent_rendering_not_monitor_rendering() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor_starter(),
        0,
        is_selected=False,
    )

    assert "⚙" not in left.plain
    assert "starter-row" in left.plain
    assert "just check" not in left.plain
    assert not any(str(span.style) == _MONITOR_ROW_STYLE for span in left.spans)


def test_failed_monitor_row_renders_exit_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(status="MONITORED", monitor_state="failed", exit_code=1),
        0,
        is_selected=False,
    )

    assert "✗ 1" in left.plain


def test_timeout_monitor_row_renders_timeout_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(status="MONITORED", monitor_state="timeout"),
        0,
        is_selected=False,
    )

    assert "⧖" in left.plain


def test_lost_monitor_row_renders_as_failed_without_exit_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(status="MONITORED", monitor_state="lost", exit_code=1),
        0,
        is_selected=False,
    )

    assert "MONITORED" in left.plain
    assert "✗ 1" not in left.plain


def test_dead_on_arrival_monitor_row_renders_stalled_badge() -> None:
    """A supervisor that died before reporting an exit code is not a plain FAILED row."""
    left, _suffix, _option_id = format_agent_option(
        make_monitor(status="MONITORED", monitor_state="failed", exit_code=None),
        0,
        is_selected=False,
    )

    assert "⚠" in left.plain
    assert "✗" not in left.plain


def test_lost_monitor_without_exit_code_renders_stalled_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(status="MONITORED", monitor_state="lost", exit_code=None),
        0,
        is_selected=False,
    )

    assert "⚠" in left.plain


def test_completed_monitor_row_has_no_stalled_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(status="MONITORED", monitor_state="completed", exit_code=0),
        0,
        is_selected=False,
    )

    assert "⚠" not in left.plain


def test_monitor_row_with_dropped_followup_renders_flag_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(
            status="MONITORED",
            monitor_state="completed",
            exit_code=0,
            followup_error="workspace #10 with pid 3333672 was not found",
        ),
        0,
        is_selected=False,
    )

    assert "⚑" in left.plain
    # A clean completion is not also flagged as dead-on-arrival.
    assert "⚠" not in left.plain


def test_monitor_row_with_degraded_followup_renders_flag_badge() -> None:
    """A degraded launch records no error, so the outcome alone must flag it."""
    left, _suffix, _option_id = format_agent_option(
        make_monitor(
            status="MONITORED",
            monitor_state="completed",
            exit_code=0,
            followup_outcome="launched-degraded",
        ),
        0,
        is_selected=False,
    )

    assert "⚑" in left.plain


def test_monitor_row_with_a_clean_launched_followup_has_no_flag_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(
            status="MONITORED",
            monitor_state="completed",
            exit_code=0,
            followup_outcome="launched",
        ),
        0,
        is_selected=False,
    )

    assert "⚑" not in left.plain


def test_monitor_row_without_followup_error_has_no_flag_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(status="MONITORED", monitor_state="completed", exit_code=0),
        0,
        is_selected=False,
    )

    assert "⚑" not in left.plain


def test_running_monitor_row_renders_amber_gear() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(status="MONITORING", monitor_state="running"),
        0,
        is_selected=False,
    )

    assert gear_style(left) == _MONITOR_GLYPH_STYLE


@pytest.mark.parametrize(
    "monitor_state",
    ("completed", "failed", "timeout", "stopped", "lost"),
)
def test_terminal_monitor_row_renders_grey_gear(monitor_state: str) -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(status="MONITORED", monitor_state=monitor_state),
        0,
        is_selected=False,
    )

    assert gear_style(left) == _MONITOR_SETTLED_GLYPH_STYLE


def test_unreported_monitor_row_renders_amber_gear() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_monitor(status="MONITORING", monitor_state=None),
        0,
        is_selected=False,
    )

    assert gear_style(left) == _MONITOR_GLYPH_STYLE


def test_running_monitor_row_with_stop_time_renders_grey_gear() -> None:
    monitor = make_monitor(status="MONITORING", monitor_state="running")
    monitor.stop_time = datetime(2026, 8, 12, 9, 3, 0)

    left, _suffix, _option_id = format_agent_option(monitor, 0, is_selected=False)

    assert gear_style(left) == _MONITOR_SETTLED_GLYPH_STYLE


def test_tree_child_settled_monitor_row_renders_grey_gear() -> None:
    container = make_family_container("completed")
    monitor = container.followup_agents[0]

    left, _suffix, _option_id = format_agent_option(monitor, 0, is_selected=False)

    assert gear_style(left) == _MONITOR_SETTLED_GLYPH_STYLE


def test_top_level_settled_monitor_row_renders_grey_gear() -> None:
    monitor = make_monitor(status="MONITORED", monitor_state="completed")
    monitor.parent_timestamp = None

    left, _suffix, _option_id = format_agent_option(monitor, 0, is_selected=False)

    assert gear_style(left) == _MONITOR_SETTLED_GLYPH_STYLE


def test_settled_row_gear_style_matches_container_settled_badge_style() -> None:
    container = make_family_container("completed")
    monitor = container.followup_agents[0]

    row_left, _suffix, _option_id = format_agent_option(monitor, 0, is_selected=False)
    container_left, _c_suffix, _c_option_id = format_agent_option(
        container, 0, is_selected=False
    )

    assert gear_style(row_left) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE
    assert gear_style(container_left) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE
