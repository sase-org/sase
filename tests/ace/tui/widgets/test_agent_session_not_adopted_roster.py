"""SESSION TURNS and JUMP show ‖ for a NOT ADOPTED monitor."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets._agent_jump_legend import _build_cell
from sase.ace.tui.widgets.prompt_panel._agent_display_agent_session import (
    agent_session_roster_entries,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from sase.ace.tui.widgets.prompt_panel._member_in_flight import (
    append_member_status_cell,
)
from sase.monitor_state import (
    MONITOR_HELD_STATE,
    NOT_ADOPTED_COLOR,
    NOT_ADOPTED_GLYPH,
    NOT_ADOPTED_STATUS,
)
from rich.text import Text


def _session_with_held_monitor() -> Agent:
    started = datetime(2026, 11, 21, 23, 50, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="research-8",
        project_file="/tmp/session.sase",
        status="FAILED",
        status_bucket="Failed",
        start_time=started,
        run_start_time=started,
        stop_time=started + timedelta(minutes=8),
        raw_suffix="20261121235000",
        agent_name="research.8--plan",
        agent_session="research.8",
        agent_session_role="root",
        role_suffix="--plan",
        plan_chain_root=True,
        model="codex/gpt-5",
    )
    failed = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="research-8-1",
        project_file="/tmp/session.sase",
        status="FAILED",
        status_bucket="Failed",
        start_time=started + timedelta(minutes=1),
        run_start_time=started + timedelta(minutes=1),
        stop_time=started + timedelta(minutes=8),
        raw_suffix="20261121235100",
        parent_timestamp=root.raw_suffix,
        agent_name="research.8--1",
        agent_session="research.8",
        agent_session_role="attempt",
        role_suffix="--1",
        model="codex/gpt-5",
    )
    held = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="research-8-mon",
        project_file="/tmp/session.sase",
        status=NOT_ADOPTED_STATUS,
        status_bucket="Failed",
        start_time=started + timedelta(minutes=9),
        run_start_time=started + timedelta(minutes=9),
        raw_suffix="20261121235900",
        parent_timestamp=failed.raw_suffix,
        agent_name="research.8--mon-0",
        agent_session="research.8",
        agent_session_role="monitor",
        role_suffix="--mon-0",
        monitor_id="m-held",
        monitor_state=MONITOR_HELD_STATE,
        monitor_label="just check",
        monitor_command="just check",
        monitor_start_status="MONITORING",
    )
    failed.runtime_children = [held]
    failed.followup_agents = [held]
    root.runtime_children = [failed]
    root.followup_agents = [failed]
    failed.agent_session_container = root
    held.agent_session_container = root
    return root


def test_session_turns_roster_uses_not_adopted_glyph() -> None:
    root = _session_with_held_monitor()
    entries = agent_session_roster_entries(root)
    held = next(entry for entry in entries if entry.status == NOT_ADOPTED_STATUS)
    assert held.effective_bucket in {"Failed", "Done"}
    header, _ = build_header_text(root, cheap=True, lane_fold_level=FoldLevel.EXPANDED)
    assert "SESSION TURNS" in header.plain
    assert f"{NOT_ADOPTED_GLYPH} {NOT_ADOPTED_STATUS}" in header.plain
    assert "▶" not in header.plain.split("SESSION TURNS", 1)[-1]


def test_jump_cell_uses_not_adopted_glyph_and_color() -> None:
    cell = _build_cell(
        "3",
        "#FFAF5F",
        ".8--mon-0",
        bucket="Failed",
        dismissed=False,
        show_archive_hint=False,
        status=NOT_ADOPTED_STATUS,
    )
    assert NOT_ADOPTED_GLYPH in cell.plain
    assert "✗" not in cell.plain
    assert "▶" not in cell.plain
    text = Text()
    append_member_status_cell(
        text,
        ".8--mon-0",
        bucket="Failed",
        status=NOT_ADOPTED_STATUS,
    )
    glyph_at = text.plain.index(NOT_ADOPTED_GLYPH)
    styles = [
        str(span.style) for span in text.spans if span.start <= glyph_at < span.end
    ]
    assert f"bold {NOT_ADOPTED_COLOR}" in styles
