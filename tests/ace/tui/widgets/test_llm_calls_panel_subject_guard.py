"""Stale-worker subject guard for the LLM Calls panel.

Selecting agent B while agent A's fetch is in flight must not paint A's
calls onto B, and B's skipped fetch must start when A's worker finishes.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

from textual.worker import Worker, WorkerState

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._llm_calls_panel_types import LLMCallsPanelFetchResult

from ._llm_calls_panel_helpers import _build_panel, _entry


def _agent(raw_suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=f"/tmp/proj/{raw_suffix}",
        raw_suffix=raw_suffix,
    )


def _event(worker: Any, state: WorkerState) -> Worker.StateChanged:
    return cast(Worker.StateChanged, SimpleNamespace(worker=worker, state=state))


def _result(agent: Agent, tool_use_id: str) -> LLMCallsPanelFetchResult:
    return LLMCallsPanelFetchResult(
        entries=(_entry(tool_use_id=tool_use_id),),
        rows=None,
        fetch_time=datetime(2026, 5, 14, 10, 30, 0),
        subject_identity=agent.identity,
    )


def test_select_b_while_a_fetch_in_flight_drops_a_result() -> None:
    """B never shows A's calls, and B's skipped fetch runs when A lands."""
    agent_a = _agent("aaa")
    agent_b = _agent("bbb")
    assert agent_a.identity != agent_b.identity

    panel = _build_panel()
    worker_a = MagicMock(is_running=True)
    panel.run_worker = MagicMock(return_value=worker_a)

    with patch(
        "sase.ace.tui.widgets.llm_calls_panel.supports_slow_tool_sources",
        return_value=False,
    ):
        panel._update_display_impl(agent_a)
        assert panel._current_worker_subject == agent_a.identity

        # B's selection paints cached/loading state but skips its fetch.
        panel._update_display_impl(agent_b)
        assert panel._current_agent is agent_b
        assert panel.run_worker.call_count == 1

    # A's worker finishes after B became current: drop it, fetch B.
    worker_a.is_running = False
    worker_a.result = _result(agent_a, "toolu_a")
    panel.update = MagicMock()
    panel.post_message = MagicMock()
    panel.on_worker_state_changed(_event(worker_a, WorkerState.SUCCESS))

    assert panel.update.call_count == 0
    assert panel.post_message.call_count == 0
    assert panel.run_worker.call_count == 2
    assert panel._current_worker_subject == agent_b.identity


def test_current_worker_result_still_displays() -> None:
    """A fresh result for the current agent paints as before."""
    agent_a = _agent("aaa")

    panel = _build_panel()
    worker = MagicMock(is_running=False)
    worker.result = _result(agent_a, "toolu_a")
    panel._current_agent = agent_a
    panel._current_worker = worker
    panel._current_worker_subject = agent_a.identity
    panel.update = MagicMock()
    panel.post_message = MagicMock()

    panel.on_worker_state_changed(_event(worker, WorkerState.SUCCESS))

    assert panel.update.call_count == 1
    assert panel.post_message.call_count == 1


def test_stale_worker_error_starts_current_fetch_without_painting() -> None:
    """A's failure while B is current shows no error and refetches B."""
    agent_a = _agent("aaa")
    agent_b = _agent("bbb")

    panel = _build_panel()
    worker_a = MagicMock(is_running=False)
    worker_a.result = None
    panel._current_agent = agent_b
    panel._current_worker = worker_a
    panel._current_worker_subject = agent_a.identity
    panel.update = MagicMock()
    panel.run_worker = MagicMock(return_value=MagicMock(is_running=False))

    panel.on_worker_state_changed(_event(worker_a, WorkerState.ERROR))

    assert panel.update.call_count == 0
    assert panel.run_worker.call_count == 1
    assert panel._current_worker_subject == agent_b.identity
