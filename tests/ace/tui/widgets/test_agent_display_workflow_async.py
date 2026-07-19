"""Workflow parent detail rendering tests."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.worker import Worker, WorkerState

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tools import SlowToolSource, ToolCallEntry
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets._agent_detail_panels import DetailPanelMode
from sase.ace.tui.widgets.prompt_panel._workflow_display import (
    WorkflowDisplayMixin,
    _build_workflow_detail_renderable,
    _load_workflow_detail_snapshot,
)
from sase.ace.tui.widgets.prompt_panel._workflow_types import WorkflowDetailSnapshot
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_rendered_section_is_compact,
)


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.WORKFLOW,
        "cl_name": "demo_cl",
        "project_file": "/tmp/demo.sase",
        "status": "DONE",
        "start_time": datetime(2026, 5, 14, 12, 0, 0),
        "workflow": "demo_workflow",
    }
    defaults.update(overrides)
    if "tag" in defaults:
        defaults["tribe"] = defaults.pop("tag")
    return Agent(**defaults)  # type: ignore[arg-type]


def _plain(renderable: object) -> str:
    if isinstance(renderable, Text):
        return renderable.plain
    if isinstance(renderable, Syntax):
        return str(renderable.code)
    if isinstance(renderable, Group):
        return "\n".join(_plain(item) for item in renderable.renderables)
    return str(renderable)


def _workflow_snapshot() -> WorkflowDetailSnapshot:
    return WorkflowDetailSnapshot(
        artifacts_path=None,
        workflow_state=None,
        inputs=None,
        meta_raw=None,
        meta_fields=[],
        steps=[],
        error=None,
        traceback=None,
        prompt_content=None,
        embedded_markers={},
        embedded_meta={},
    )


def _tool_entry(**overrides: object) -> ToolCallEntry:
    kwargs = {
        "recorded_at": "2026-07-03T14:00:00+00:00",
        "runtime": "codex",
        "event": "ToolUse",
        "status": "success",
        "tool_name": "Bash",
        "tool_use_id": "call_1",
        "duration_ms": 30_000,
        "tool_input_summary": {"command": "just test"},
        "tool_response_summary": {"exit_code": 0},
    }
    kwargs.update(overrides)
    return ToolCallEntry(**kwargs)  # type: ignore[arg-type]


def _slow_source(*entries: ToolCallEntry) -> SlowToolSource:
    return SlowToolSource(
        label=None,
        entries=tuple(entries),
        agent_is_active=False,
        end_reference=None,
        palette_index=0,
    )


class _Panel(WorkflowDisplayMixin):
    def __init__(self) -> None:
        self.captured: list[object] = []

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)


def test_workflow_snapshot_render_reads_state_once_and_uses_parsed_data(
    tmp_path: Path,
) -> None:
    state = {
        "inputs": {"task": "fix"},
        "steps": [
            {
                "name": "plan",
                "status": "completed",
                "output": {
                    "meta_project": "sase",
                    "meta_workspace": 7,
                    "meta_result": "ok",
                },
            }
        ],
        "step_prompts": [{"name": "plan", "agent": "fallback prompt"}],
    }
    state_path = tmp_path / "workflow_state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    agent = _make_agent(artifacts_dir=str(tmp_path), cl_name="old_cl")
    panel = _Panel()

    from sase.ace.tui.widgets.prompt_panel import _workflow_display

    real_load_json_cached = _workflow_display.load_json_cached
    with patch.object(
        _workflow_display, "load_json_cached", wraps=real_load_json_cached
    ) as mock_load:
        panel._update_workflow_display(agent)

    state_reads = [
        call for call in mock_load.call_args_list if call.args[0] == state_path
    ]
    assert len(state_reads) == 1

    plain = _plain(panel.captured[-1])
    assert "Project: sase" in plain
    assert "Workspace: #7" in plain
    assert "WORKFLOW VARIABLES" in plain
    assert plain.index("WORKFLOW VARIABLES") < plain.index("Result: ok")
    assert "Result: ok" in plain
    assert "INPUTS" in plain
    assert 'task: "fix"' in plain
    assert "Step 1/1" in plain
    rendered = panel.captured[-1]
    assert_rendered_section_is_compact(
        rendered,
        "WORKFLOW DETAILS",
        "Workflow: demo_workflow",
    )
    assert_rendered_section_is_compact(
        rendered,
        "WORKFLOW VARIABLES",
        "Result: ok",
    )
    assert_rendered_section_is_compact(rendered, "INPUTS", '  task: "fix"')
    assert_rendered_section_is_compact(rendered, "WORKFLOW STEPS", "  Step 1/1")


def test_workflow_snapshot_omits_workflow_variables_header_when_no_meta_fields(
    tmp_path: Path,
) -> None:
    state = {
        "inputs": {"task": "fix"},
        "steps": [
            {
                "name": "plan",
                "status": "completed",
                "output": {"result": "ok"},
            }
        ],
        "step_prompts": [{"name": "plan", "agent": "fallback prompt"}],
    }
    (tmp_path / "workflow_state.json").write_text(json.dumps(state), encoding="utf-8")
    agent = _make_agent(artifacts_dir=str(tmp_path))
    panel = _Panel()

    panel._update_workflow_display(agent)

    plain = _plain(panel.captured[-1])
    assert "WORKFLOW VARIABLES" not in plain
    assert "plan" in plain
    assert "fallback prompt" in plain


def test_workflow_snapshot_renders_prompt_markers_and_embedded_meta_in_order(
    tmp_path: Path,
) -> None:
    (tmp_path / "workflow_state.json").write_text(
        json.dumps(
            {"steps": [{"name": "main", "status": "completed", "output": "done"}]}
        ),
        encoding="utf-8",
    )
    early_prompt = tmp_path / "001_prompt.md"
    late_prompt = tmp_path / "002_prompt.md"
    early_prompt.write_text("early prompt", encoding="utf-8")
    late_prompt.write_text("late prompt", encoding="utf-8")
    os.utime(early_prompt, (1, 1))
    os.utime(late_prompt, (2, 2))

    (tmp_path / "prompt_step_000.json").write_text(
        json.dumps(
            {
                "parent_step_index": 0,
                "step_index": 0,
                "embedded_workflow_name": "deploy",
                "is_pre_prompt_step": True,
                "step_name": "prep",
                "status": "completed",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "prompt_step_001.json").write_text(
        json.dumps(
            {
                "parent_step_index": 0,
                "step_index": 1,
                "embedded_workflow_name": "deploy",
                "is_pre_prompt_step": False,
                "step_name": "cleanup",
                "status": "completed",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "embedded_workflows_main.json").write_text(
        json.dumps([{"name": "deploy", "args": {"env": "prod"}}]),
        encoding="utf-8",
    )

    agent = _make_agent(artifacts_dir=str(tmp_path))
    renderable = _build_workflow_detail_renderable(
        agent, _load_workflow_detail_snapshot(agent)
    )

    plain = _plain(renderable)
    assert "early prompt" in plain
    assert "late prompt" not in plain
    assert plain.index("#deploy(env=prod)") < plain.index("prep")
    assert plain.index("prep") < plain.index("cleanup")
    assert plain.index("AGENT PROMPT") < plain.index("early prompt")
    assert_rendered_section_is_compact(
        renderable,
        "AGENT PROMPT",
        "early prompt",
    )


def test_empty_workflow_steps_placeholder_is_compact() -> None:
    renderable = _build_workflow_detail_renderable(
        _make_agent(),
        _workflow_snapshot(),
    )

    assert_rendered_section_is_compact(
        renderable,
        "WORKFLOW DETAILS",
        "Workflow: demo_workflow",
    )
    assert_rendered_section_is_compact(
        renderable,
        "WORKFLOW STEPS",
        "No workflow state found.",
    )


def test_failed_workflow_without_recorded_error_shows_output() -> None:
    renderable = _build_workflow_detail_renderable(
        _make_agent(status="FAILED", output_path="/tmp/workflow-runner.log"),
        _workflow_snapshot(),
    )

    plain = _plain(renderable)
    assert "ERROR" in plain
    assert "Runner failed without error details." in plain
    assert "Output: /tmp/workflow-runner.log" in plain


def test_workflow_detail_uses_custom_slow_tool_threshold() -> None:
    agent = _make_agent()
    renderable = _build_workflow_detail_renderable(
        agent,
        _workflow_snapshot(),
        slow_tool_sources=(
            _slow_source(
                _tool_entry(
                    duration_ms=29_999,
                    tool_input_summary={"command": "under threshold"},
                ),
                _tool_entry(
                    duration_ms=30_000,
                    tool_input_summary={"command": "exact threshold"},
                ),
            ),
        ),
        slow_tool_call_threshold_ms=30_000,
    )

    plain = _plain(renderable)
    assert "SLOW TOOL CALLS · ≥30s · 1 call" in plain
    assert "exact threshold" in plain
    assert "under threshold" not in plain


class _FakePromptPanel:
    def __init__(self) -> None:
        self.attempt_view_mode = ""
        self.attempt_pinned_number: int | None = None
        self.update_display_calls: list[Agent] = []
        self.workflow_render_calls: list[dict[str, Any]] = []

    def update_display(self, agent: Agent) -> None:
        self.update_display_calls.append(agent)

    def start_workflow_detail_render(self, agent: Agent, **kwargs: Any) -> None:
        self.workflow_render_calls.append({"agent": agent, **kwargs})


class _FakeFilePanel:
    def __init__(self) -> None:
        self.update_display_calls: list[Agent] = []
        self.file_lists: list[list[str]] = []

    def update_display(self, agent: Agent, **_kwargs: Any) -> None:
        self.update_display_calls.append(agent)

    def set_file_list(self, files: list[str], *, start_index: int = 0) -> None:
        self.file_lists.append(files)


class _FakeToolsPanel:
    def __init__(self) -> None:
        self.update_display_calls: list[Agent] = []

    def update_display(self, agent: Agent, **_kwargs: Any) -> None:
        self.update_display_calls.append(agent)


class _FakeScroll:
    def add_class(self, _class_name: str) -> None:
        pass


def test_agent_detail_starts_background_workflow_render_in_debounced_path() -> None:
    prompt_panel = _FakePromptPanel()
    file_panel = _FakeFilePanel()
    tools_panel = _FakeToolsPanel()
    scroll = _FakeScroll()
    detail = AgentDetail.__new__(AgentDetail)
    detail._current_agent = None
    detail._current_attempt_number = None
    detail._attempt_view_mode = "merged"
    detail._agent_detail_generation = 10
    detail._panel_mode = DetailPanelMode.AUTO
    detail._update_panel_indicators = lambda: None  # type: ignore[method-assign]
    expanded: list[bool] = []
    detail._expand_prompt_only = lambda: expanded.append(True)  # type: ignore[method-assign]

    def query_one(_selector: str, cls: object) -> object:
        if cls.__name__ == "AgentPromptPanel":
            return prompt_panel
        if cls.__name__ == "AgentFilePanel":
            return file_panel
        if cls.__name__ == "AgentToolsPanel":
            return tools_panel
        return scroll

    detail.query_one = query_one  # type: ignore[method-assign]

    agent = _make_agent()
    detail._update_display_impl(agent)

    assert prompt_panel.update_display_calls == []
    assert len(prompt_panel.workflow_render_calls) == 1
    assert tools_panel.update_display_calls == []
    assert expanded == [True]

    call = prompt_panel.workflow_render_calls[0]
    is_current = call["is_current"]
    assert is_current(agent.identity, 10, "merged", None)
    detail._agent_detail_generation = 11
    assert not is_current(agent.identity, 10, "merged", None)


class _FakeWorker:
    def __init__(self) -> None:
        self.is_running = False
        self.result = Text("rendered")
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _AsyncPanel(WorkflowDisplayMixin):
    def __init__(self, worker: _FakeWorker) -> None:
        self.worker = worker
        self.captured: list[object] = []

    def run_worker(self, _fn: object, *, thread: bool) -> _FakeWorker:
        assert thread
        return self.worker

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)


def test_stale_workflow_worker_result_is_ignored() -> None:
    worker = _FakeWorker()
    panel = _AsyncPanel(worker)
    panel.start_workflow_detail_render(
        _make_agent(),
        generation=1,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=lambda *_args: False,
    )

    panel._apply_workflow_detail_worker_result(
        cast(Worker[Any], worker), WorkerState.SUCCESS
    )

    assert panel.captured == []
