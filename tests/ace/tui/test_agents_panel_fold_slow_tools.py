"""Slow-tool rendering tests for Agents-tab fold mode."""

from datetime import UTC, datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.tools import SlowToolSource, ToolCallEntry
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from tests.ace.tui._agents_panel_fold_mode_helpers import _FoldApp, _press


def _ordinary_slow_tool_fold_document(
    app: _FoldApp,
    agent: Agent,
) -> str:
    entry = ToolCallEntry(
        recorded_at="2026-07-28T12:00:00+00:00",
        runtime="codex",
        event="ToolUse",
        status="success",
        tool_name="Bash",
        duration_ms=30_000,
        completed_at="2026-07-28T12:00:30+00:00",
        tool_input_summary={
            "description": "run checks",
            "command": "just check\nprintf ordinary-slow-detail",
        },
        tool_response_summary={
            "exit_code": 0,
            "stdout_preview": "all checks passed",
        },
    )
    summary = DetailHeaderSummary(
        slow_tool_sources=(
            SlowToolSource(
                label=None,
                entries=(entry,),
                agent_is_active=False,
                end_reference=None,
                palette_index=0,
            ),
        )
    )
    header, _ = build_header_text(
        agent,
        summary=summary,
        lane_fold_level=app.panel_fold_level,
        lane_section_fold_overrides=app._panel_fold_overrides.snapshot(),
    )
    return header.plain


def test_slow_tool_section_commands_change_an_ordinary_lane_and_panel_cycle_resets() -> (
    None
):
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="ordinary-slow-fold",
        project_file="/tmp/fold.sase",
        status="DONE",
        start_time=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
        stop_time=datetime(2026, 7, 28, 12, 1, tzinfo=UTC),
        raw_suffix="ordinary-slow-fold",
        agent_name="ordinary-slow-fold",
        model="gpt-5",
    )
    app = _FoldApp(clan=False, slow_tool_call_count=1)
    app.selected_agent = agent
    app.section_id = "slow-tool-calls"

    assert "ordinary-slow-detail" not in _ordinary_slow_tool_fold_document(app, agent)

    _press(app, "a")
    assert app._panel_fold_overrides.get_override("slow-tool-calls") is (
        FoldLevel.EXPANDED
    )
    assert "ordinary-slow-detail" in _ordinary_slow_tool_fold_document(app, agent)

    _press(app, "A")
    assert "ordinary-slow-detail" not in _ordinary_slow_tool_fold_document(app, agent)
    _press(app, "A")
    full = _ordinary_slow_tool_fold_document(app, agent)
    assert "│ output all checks passed" in full

    _press(app, "1")
    assert app._panel_fold_overrides.snapshot() == {}
    assert "ordinary-slow-detail" not in _ordinary_slow_tool_fold_document(app, agent)
