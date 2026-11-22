"""Held staged-monitor row word and never-ran time column."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.monitor_state import (
    MONITOR_HELD_STATE,
    NOT_ADOPTED_COLOR,
    NOT_ADOPTED_GLYPH,
    NOT_ADOPTED_STATUS,
)

from ._agent_list_monitor_rows_helpers import style_at


def _held_monitor() -> Agent:
    started = datetime(2026, 11, 21, 23, 59, 0)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="held-row",
        project_file="/tmp/monitor.sase",
        status=NOT_ADOPTED_STATUS,
        status_bucket="Failed",
        start_time=started,
        run_start_time=started,
        stop_time=None,
        raw_suffix="20261121235900",
        parent_timestamp="20261121235300",
        agent_name="alpha--mon-0",
        agent_session="alpha",
        agent_session_role="monitor",
        role_suffix="--mon-0",
        monitor_id="m-held",
        monitor_state=MONITOR_HELD_STATE,
        monitor_label="just check",
        monitor_command="just check",
        monitor_start_status="MONITORING",
    )


def test_held_row_renders_not_adopted_word_and_glyph() -> None:
    left, suffix, _option_id = format_agent_option(
        _held_monitor(),
        0,
        is_selected=False,
        now=datetime(2026, 11, 21, 23, 59, 30),
    )

    expected = f"{NOT_ADOPTED_STATUS} {NOT_ADOPTED_GLYPH}"
    assert expected in left.plain
    assert style_at(left, left.plain.index(NOT_ADOPTED_STATUS)) == (
        f"bold {NOT_ADOPTED_COLOR}"
    )
    assert "⧗" not in suffix.plain
    assert "🏃‍♂️" not in suffix.plain
    assert suffix.plain == "staged 23:59 · never ran"
    assert "dim" in (style_at(suffix, 0) or "")
