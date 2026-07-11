from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tools import ToolCallEntry
from sase.ace.tui.tools.cache import _ToolsCacheEntry, _tools_cache, get_cache_key
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_display_state import AgentHintRender


def _agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 3, 10, 0, 0),
        artifacts_dir="/tmp/artifacts",
        raw_suffix="20260703100000",
    )


def _workflow_root_with_child() -> tuple[Agent, Agent]:
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 3, 10, 0, 0),
        artifacts_dir="/tmp/root-artifacts",
        raw_suffix="20260703100000",
        workflow="wf",
    )
    child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="plan",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 3, 10, 0, 0),
        artifacts_dir="/tmp/child-artifacts",
        raw_suffix="20260703100001",
        parent_workflow="wf",
        step_type="agent",
    )
    root.runtime_children.append(child)
    return root, child


def _entry(**overrides: object) -> ToolCallEntry:
    kwargs = {
        "recorded_at": "2026-07-03T14:00:00+00:00",
        "runtime": "codex",
        "event": "ToolUse",
        "status": "pending",
        "tool_name": "Bash",
        "tool_use_id": "call_1",
        "duration_ms": None,
        "tool_input_summary": {"command": "just test"},
        "tool_response_summary": {},
    }
    kwargs.update(overrides)
    return ToolCallEntry(**kwargs)  # type: ignore[arg-type]


def _panel() -> AgentPromptPanel:
    panel = AgentPromptPanel.__new__(AgentPromptPanel)
    panel.attempt_pinned_number = None
    panel._slow_tool_render_timer = None
    panel._slow_tool_tick_agent = None
    panel.set_interval = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]
    panel.refresh_slow_tool_metadata_from_cache = MagicMock()  # type: ignore[method-assign]
    return panel


def test_slow_tool_tick_repaints_from_cache_without_artifact_read() -> None:
    agent = _agent()
    cache_key = get_cache_key(agent)
    _tools_cache[cache_key] = _ToolsCacheEntry(
        entries=(_entry(),),
        fetch_time=datetime.now(),
    )
    panel = _panel()

    try:
        panel._configure_slow_tool_render_tick(agent)
        with patch("sase.ace.tui.tools.cache.read_tool_calls_for_agent") as read_mock:
            panel._on_slow_tool_render_tick()
    finally:
        _tools_cache.pop(cache_key, None)

    assert panel.set_interval.call_count == 1  # type: ignore[attr-defined]
    panel.refresh_slow_tool_metadata_from_cache.assert_called_once_with(agent)  # type: ignore[attr-defined]
    read_mock.assert_not_called()


def test_slow_tool_tick_stays_armed_for_pending_child_source() -> None:
    root, child = _workflow_root_with_child()
    child_cache_key = get_cache_key(child)
    _tools_cache[child_cache_key] = _ToolsCacheEntry(
        entries=(_entry(),),
        fetch_time=datetime.now(),
    )
    panel = _panel()

    try:
        panel._configure_slow_tool_render_tick(root)
        panel._on_slow_tool_render_tick()
    finally:
        _tools_cache.pop(child_cache_key, None)

    assert panel.set_interval.call_count == 1  # type: ignore[attr-defined]
    panel.refresh_slow_tool_metadata_from_cache.assert_called_once_with(root)  # type: ignore[attr-defined]


def test_slow_tool_tick_disarms_when_no_pending_calls_remain() -> None:
    agent = _agent()
    cache_key = get_cache_key(agent)
    _tools_cache[cache_key] = _ToolsCacheEntry(
        entries=(_entry(status="success", duration_ms=30_000),),
        fetch_time=datetime.now(),
    )
    timer = MagicMock()
    panel = _panel()
    panel._slow_tool_render_timer = timer
    panel._slow_tool_tick_agent = agent

    try:
        panel._on_slow_tool_render_tick()
    finally:
        _tools_cache.pop(cache_key, None)

    timer.stop.assert_called_once_with()
    assert panel._slow_tool_render_timer is None
    assert panel._slow_tool_tick_agent is None


def test_slow_tool_tick_cannot_repaint_after_hint_generation_transition() -> None:
    agent = _agent()
    cache_key = get_cache_key(agent)
    _tools_cache[cache_key] = _ToolsCacheEntry(
        entries=(_entry(),),
        fetch_time=datetime.now(),
    )
    detail = AgentDetail.__new__(AgentDetail)
    detail._agent_detail_generation = 3
    detail._current_agent = agent
    detail._attempt_view_mode = "merged"
    detail._current_attempt_number = None
    panel = _panel()
    panel.update_display_with_hints = MagicMock(  # type: ignore[method-assign]
        return_value=AgentHintRender(file_hints={}, tool_call_reports={})
    )
    detail.query_one = lambda *_args: panel  # type: ignore[method-assign]

    def is_current(
        agent_identity: tuple[object, ...],
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
    ) -> bool:
        return (
            detail._agent_detail_generation == generation
            and detail._current_agent is not None
            and detail._current_agent.identity == agent_identity
            and detail._attempt_view_mode == attempt_view_mode
            and detail._current_attempt_number == attempt_pinned_number
        )

    panel.set_agent_detail_render_context(
        generation=3,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=is_current,
    )

    try:
        panel._configure_slow_tool_render_tick(agent)
        timer = panel._slow_tool_render_timer
        detail.update_display_with_hints(agent)
        panel._on_slow_tool_render_tick()
    finally:
        _tools_cache.pop(cache_key, None)

    assert detail._agent_detail_generation == 4
    panel.update_display_with_hints.assert_called_once_with(agent)  # type: ignore[attr-defined]
    panel.refresh_slow_tool_metadata_from_cache.assert_not_called()  # type: ignore[attr-defined]
    assert timer is not None
    timer.stop.assert_called_once_with()
    assert panel._slow_tool_render_timer is None
    assert panel._slow_tool_tick_agent is None
