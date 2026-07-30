"""Multi-prompt launch fan-out tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from tests.ace.tui._launch_fan_out_helpers import (
    _ctx,
    _FakeMultiPrompt,
    _launch_result,
    _MultiPromptApp,
)


def test_multi_prompt_launch_submits_tracked_task_not_inline_worker() -> None:
    """The multi-prompt fan-out appears as one tracked launch task."""
    app = _MultiPromptApp()
    multi = _FakeMultiPrompt(["one", "two", "three"])

    with patch("sase.agent.multi_prompt.MultiPrompt", _FakeMultiPrompt, create=True):
        with patch("sase.agent.multi_prompt_launcher.launch_multi_prompt_agents"):
            app._launch_multi_prompt_agents(multi, _ctx(), None)

    assert app.scheduled == []
    assert len(app.launch_tasks) == 1
    task = app.launch_tasks[0]
    assert task["display_name"] == "launch multi-prompt cl"
    assert task["cl_name"] == "cl"


def test_multi_prompt_burst_collapses_to_single_refresh() -> None:
    """5 spawned agents across one fan-out become one artifact-delta batch."""
    app = _MultiPromptApp()
    segments = ["a", "b", "c", "d", "e"]
    multi = _FakeMultiPrompt(segments)

    def _fake_launch(**_kwargs: Any) -> list[Any]:
        return [_launch_result(i) for i in range(5)]

    with patch("sase.agent.multi_prompt.MultiPrompt", _FakeMultiPrompt, create=True):
        with patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=_fake_launch,
        ):
            app._launch_multi_prompt_agents(multi, _ctx(), None)
            app._run_submitted_launch_tasks()

    assert app.refresh_requests == []
    assert len(app.launch_delta_batches) == 1
    assert [result.pid for result in app.launch_delta_batches[0]] == [
        1000,
        1001,
        1002,
        1003,
        1004,
    ]


def test_multi_prompt_launch_context_is_immutable_snapshot() -> None:
    """Mutating ``_prompt_context`` after dispatch does not affect the worker."""
    app = _MultiPromptApp()
    ctx = _ctx()
    multi = _FakeMultiPrompt(["x"])

    captured: dict[str, str] = {}

    def _capture(**kwargs: Any) -> list[Any]:
        captured["display_name"] = kwargs.get("cl_name", "")
        return []

    with patch("sase.agent.multi_prompt.MultiPrompt", _FakeMultiPrompt, create=True):
        with patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=_capture,
        ):
            app._launch_multi_prompt_agents(multi, ctx, None)
            # Mutate the original ctx; the worker must not see this.
            ctx.display_name = "MUTATED"
            app._run_submitted_launch_tasks()
    assert captured["display_name"] == "cl"


def test_multi_prompt_launch_forwards_submitted_prompt_text() -> None:
    app = _MultiPromptApp()
    multi = _FakeMultiPrompt(["one", "two"])
    submitted = "one\n---\ntwo"
    captured: dict[str, str] = {}

    def _capture(**kwargs: Any) -> list[Any]:
        captured["multi_agent_prompt_text"] = kwargs.get("multi_agent_prompt_text", "")
        return []

    with patch("sase.agent.multi_prompt.MultiPrompt", _FakeMultiPrompt, create=True):
        with patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=_capture,
        ):
            app._launch_multi_prompt_agents(multi, _ctx(), None, submitted)
            app._run_submitted_launch_tasks()

    assert captured["multi_agent_prompt_text"] == submitted


def test_multi_prompt_launch_forwards_swarm_provenance() -> None:
    app = _MultiPromptApp()
    multi = _FakeMultiPrompt(["one", "two"])
    multi.swarm_xprompts = [("outer",), ("outer", "inner")]
    captured: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    with patch("sase.agent.multi_prompt.MultiPrompt", _FakeMultiPrompt, create=True):
        with patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=_capture,
        ):
            app._launch_multi_prompt_agents(multi, _ctx(), None)
            app._run_submitted_launch_tasks()

    assert captured["segment_swarm_xprompts"] == [
        ("outer",),
        ("outer", "inner"),
    ]


def test_multi_prompt_launch_failure_records_failed_history() -> None:
    app = _MultiPromptApp()
    multi = _FakeMultiPrompt(["first prompt", "second prompt"])
    submitted = "first prompt\n---\nsecond prompt"

    with (
        patch("sase.agent.multi_prompt.MultiPrompt", _FakeMultiPrompt, create=True),
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=RuntimeError("workspace claim failed"),
        ),
        patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
    ):
        outcome = app._run_multi_prompt_launch(multi, _ctx(), None, submitted)

    record_failed.assert_called_once_with(submitted)
    assert outcome.message == (
        "Multi-prompt launch failed - see Logs in SASE Admin Center (#)"
    )
    assert outcome.severity == "error"
