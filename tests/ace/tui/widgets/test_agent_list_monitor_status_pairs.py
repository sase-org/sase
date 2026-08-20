"""Custom monitor status-pair presentation tests."""

from __future__ import annotations

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.ace.tui.widgets._agent_list_styling import monitor_status_presentation
from sase.monitor_status import (
    MONITOR_STATUS_FAILURE_STYLE,
    monitor_status_accent,
    monitor_status_pair,
)

from ._agent_list_monitor_rows_helpers import make_monitor, style_at

_TESTING_PAIR = monitor_status_pair("TESTING", "TESTED")
_TESTING_ACCENT = monitor_status_accent(_TESTING_PAIR)
_SLEEPING_PAIR = monitor_status_pair("SLEEPING", "SLEPT")
_SLEEPING_ACCENT = monitor_status_accent(_SLEEPING_PAIR)


def _custom_monitor(
    *,
    status: str,
    monitor_state: str,
    exit_code: int | None = None,
    start_status: str = "TESTING",
    stop_status: str = "TESTED",
) -> Agent:
    return make_monitor(
        status=status,
        monitor_state=monitor_state,
        exit_code=exit_code,
        start_status=start_status,
        stop_status=stop_status,
    )


def test_running_custom_pair_renders_bold_accent() -> None:
    left, _suffix, _option_id = format_agent_option(
        _custom_monitor(status="TESTING", monitor_state="running"),
        0,
        is_selected=False,
    )

    assert "TESTING" in left.plain
    assert "✓" not in left.plain
    assert style_at(left, left.plain.index("TESTING")) == f"bold {_TESTING_ACCENT}"


def test_completed_custom_pair_renders_accent_and_check_glyph() -> None:
    left, _suffix, _option_id = format_agent_option(
        _custom_monitor(status="TESTED", monitor_state="completed", exit_code=0),
        0,
        is_selected=False,
    )

    assert "TESTED ✓" in left.plain
    assert style_at(left, left.plain.index("TESTED")) == _TESTING_ACCENT
    assert style_at(left, left.plain.index("✓")) == _TESTING_ACCENT


def test_stopped_custom_pair_renders_accent_and_stop_glyph() -> None:
    left, _suffix, _option_id = format_agent_option(
        _custom_monitor(status="TESTED", monitor_state="stopped", exit_code=0),
        0,
        is_selected=False,
    )

    assert "TESTED ⊘" in left.plain
    assert style_at(left, left.plain.index("TESTED")) == _TESTING_ACCENT


@pytest.mark.parametrize(
    ("monitor_state", "exit_code", "marker"),
    (
        ("failed", 1, "✗ 1"),
        ("timeout", None, "⧖"),
        ("lost", None, "⚠"),
    ),
)
def test_failure_states_render_red_and_keep_existing_markers(
    monitor_state: str, exit_code: int | None, marker: str
) -> None:
    left, _suffix, _option_id = format_agent_option(
        _custom_monitor(
            status="TESTED", monitor_state=monitor_state, exit_code=exit_code
        ),
        0,
        is_selected=False,
    )

    assert marker in left.plain
    assert left.plain.count("✗") == (1 if monitor_state == "failed" else 0)
    assert style_at(left, left.plain.index("TESTED")) == MONITOR_STATUS_FAILURE_STYLE


def test_different_pairs_render_different_styles() -> None:
    testing, _suffix, _option_id = format_agent_option(
        _custom_monitor(status="TESTING", monitor_state="running"),
        0,
        is_selected=False,
    )
    sleeping, _s_suffix, _s_option_id = format_agent_option(
        _custom_monitor(
            status="SLEEPING",
            monitor_state="running",
            start_status="SLEEPING",
            stop_status="SLEPT",
        ),
        0,
        is_selected=False,
    )

    testing_style = style_at(testing, testing.plain.index("TESTING"))
    sleeping_style = style_at(sleeping, sleeping.plain.index("SLEEPING"))
    assert testing_style == f"bold {_TESTING_ACCENT}"
    assert sleeping_style == f"bold {_SLEEPING_ACCENT}"
    assert testing_style != sleeping_style


def test_same_pair_renders_the_same_style_on_two_rows() -> None:
    first, _suffix, _option_id = format_agent_option(
        _custom_monitor(status="TESTING", monitor_state="running"),
        0,
        is_selected=False,
    )
    second, _s_suffix, _s_option_id = format_agent_option(
        _custom_monitor(status="TESTING", monitor_state="running"),
        1,
        is_selected=False,
    )

    assert style_at(first, first.plain.index("TESTING")) == style_at(
        second, second.plain.index("TESTING")
    )


def test_starting_monitor_member_keeps_starting_style() -> None:
    left, _suffix, _option_id = format_agent_option(
        _custom_monitor(status="STARTING", monitor_state="running"),
        0,
        is_selected=False,
    )

    assert "STARTING" in left.plain
    assert "TESTING" not in left.plain
    assert style_at(left, left.plain.index("STARTING")) == "bold #87D7FF"


def test_presentation_helper_ignores_rows_without_a_recorded_pair() -> None:
    row = _custom_monitor(status="TESTING", monitor_state="running")
    row.monitor_start_status = None
    row.monitor_stop_status = None

    assert monitor_status_presentation(row) is None


def test_presentation_helper_ignores_status_that_is_not_a_pair_half() -> None:
    assert (
        monitor_status_presentation(
            _custom_monitor(status="RUNNING", monitor_state="running")
        )
        is None
    )


def test_mirrored_family_container_uses_the_same_style_as_the_monitor() -> None:
    monitor = _custom_monitor(status="TESTING", monitor_state="running")
    container = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-root",
        project_file="/tmp/monitor.sase",
        status="TESTING",
        start_time=monitor.start_time,
        raw_suffix="20260812085900",
        agent_name="alpha--0",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state="running",
    )

    monitor_left, _suffix, _option_id = format_agent_option(
        monitor, 0, is_selected=False
    )
    container_left, _c_suffix, _c_option_id = format_agent_option(
        container, 0, is_selected=False
    )

    assert monitor_status_presentation(container) == monitor_status_presentation(
        monitor
    )
    assert style_at(monitor_left, monitor_left.plain.index("TESTING")) == style_at(
        container_left, container_left.plain.index("TESTING")
    )
