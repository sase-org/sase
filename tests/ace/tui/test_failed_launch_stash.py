"""Failed-launch stash coverage for the ACE TUI launch boundaries.

These pin that a failed agent launch which still holds the submitted prompt
preserves it in the per-user prompt stash so it stays recoverable through
``@`` / ``Ctrl+G p`` after the prompt bar has been unmounted:

- the single-agent launch task carries the submitted prompt as recovery
  metadata,
- a payloadless launch-task failure (worker died before returning an outcome,
  e.g. a project-alias canonicalization conflict) stashes that metadata and
  refreshes the badge,
- a real single-agent spawn failure leaves a restorable stash row, and
- a failed/partial launch outcome refreshes the badge from disk.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agent_workflow._launch_tasks import (
    LaunchTaskMixin,
    LaunchTaskOutcome,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_stash import PromptBarStashMixin
from sase.ace.tui.actions.task_actions import TrackedTaskCompletion
from sase.ace.tui.task_queue import TaskInfo
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

from ._agent_launch_helpers import (
    _FakeApp,
    _LaunchBodyApp,
    _run_launch_body_with_common_patches,
)


def _skip_without_prompt_stash_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "append_prompt_stash"):
        pytest.skip("sase_core_rs is too old (no append_prompt_stash binding).")


def _point_store_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("sase.core.paths.prompt_stash_path", lambda: path, raising=True)


def _entries(path: Path) -> list:
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    return list(read_prompt_stash_snapshot(path).entries)


class _CompletionApp(LaunchTaskMixin, PromptBarStashMixin):
    """Real launch-completion + stash-badge glue without a live Textual DOM."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.applied_counts: list[int] = []
        self.applied_pinned_counts: list[int] = []
        self._prompt_context = None

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def _apply_prompt_stash_counts(self, count: int, pinned_count: int) -> None:
        self.applied_counts.append(count)
        self.applied_pinned_counts.append(pinned_count)

    # Payload-branch collaborators (unused by the error-only outcomes here).
    def _handle_launch_results_delta(self, results: Any) -> None:
        del results

    def request_agents_refresh(self, source: str) -> None:
        del source

    def _schedule_agents_async_refresh(self, *, source: str = "launch") -> None:
        del source


async def _drain_async_tasks(app: object) -> None:
    for attr in ("_prompt_stash_async_tasks", "_launch_failure_log_tasks"):
        tasks: list[Any] = list(getattr(app, attr, None) or [])
        for task in tasks:
            await task


def _completion(
    *,
    success: bool,
    payload: LaunchTaskOutcome | None,
    task_id: str = "task-1",
) -> TrackedTaskCompletion[LaunchTaskOutcome]:
    return TrackedTaskCompletion(
        task_info=TaskInfo(
            task_id=task_id,
            task_type="launch",
            cl_name="cl",
            project_file="/tmp/proj.sase",
            status="error" if not success else "success",
            message="m",
            started_at=datetime.now(),
            display_name="launch cl",
        ),
        success=success,
        message="m",
        output="",
        payload=payload,
        error=None if success else "worker died",
    )


# --- single-agent launch threads the submitted prompt as recovery metadata --


def test_launch_resolved_prompt_threads_submitted_prompt() -> None:
    app = _FakeApp()

    app._finish_agent_launch("a long prompt to keep recoverable")

    assert len(app.launch_tasks) == 1
    assert (
        app.launch_tasks[0]["submitted_prompt"] == "a long prompt to keep recoverable"
    )


# --- payloadless launch-task failure (the project-alias conflict regression) -


async def test_payloadless_failure_with_metadata_stashes_and_refreshes_badge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)

    app = _CompletionApp()
    lost = "#al:thing build the entire feature, this is a long prompt"
    app._launch_submitted_prompts = {"task-1": lost}

    app._on_launch_task_complete(_completion(success=False, payload=None))
    await _drain_async_tasks(app)

    entries = _entries(stash_path)
    assert [e.text for e in entries] == [lost]
    assert entries[0].source == "failed_launch"
    # The badge reflects the freshly stashed row.
    assert app.applied_counts and app.applied_counts[-1] == 1
    # Recovery metadata is consumed exactly once.
    assert app._launch_submitted_prompts == {}


async def test_payloadless_failure_without_metadata_does_not_stash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)

    app = _CompletionApp()
    app._on_launch_task_complete(_completion(success=False, payload=None))
    await _drain_async_tasks(app)

    assert not stash_path.exists()
    assert app.applied_counts == []


# --- failed/partial outcome refreshes the badge from disk -------------------


async def test_error_outcome_refreshes_badge_for_worker_stashed_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)

    # Simulate the worker having already stashed its prompt synchronously.
    from sase.agent.failed_launch_prompt_stash import stash_failed_launch_prompt

    stash_failed_launch_prompt("already stashed by the worker thread")

    app = _CompletionApp()
    app._on_launch_task_complete(
        _completion(
            success=False,
            payload=LaunchTaskOutcome("Launch failed", severity="error"),
        )
    )
    await _drain_async_tasks(app)

    assert app.applied_counts and app.applied_counts[-1] == 1
    assert app.notifications[-1] == ("Launch failed", "error")


# --- workflow start failure stashes the submitted prompt --------------------


def test_workflow_thread_start_failure_stashes_submitted_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)

    from sase.ace.tui.actions.agent_workflow._workflow_exec import WorkflowExecMixin

    class _WorkflowApp(WorkflowExecMixin):
        def __init__(self) -> None:
            self._prompt_context = None
            self.scheduled: list[Any] = []

        def call_later(self, fn: Any, *args: Any, **kwargs: Any) -> None:
            del kwargs
            self.scheduled.append((fn, args))

        def notify(self, msg: str, *, severity: str | None = None) -> None:
            del msg, severity

    def _boom_thread(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise RuntimeError("cannot spawn workflow thread")

    monkeypatch.setattr("threading.Thread", _boom_thread)

    app = _WorkflowApp()
    result = app._execute_workflow_in_thread(
        "eval/foo", [], {}, submitted_prompt="#!eval/foo run the workflow now"
    )

    assert result is False
    entries = _entries(stash_path)
    assert [e.text for e in entries] == ["#!eval/foo run the workflow now"]
    assert entries[0].source == "failed_launch"


# --- real single-agent spawn failure leaves a restorable stash row ----------


def test_single_agent_spawn_failure_leaves_stash_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)

    app = _LaunchBodyApp()
    prompt = "launch a single agent for this long unit of work"

    def _boom(**kwargs: Any) -> Any:
        del kwargs
        raise RuntimeError("spawn boom")

    with patch.object(_LaunchBodyApp, "_launch_background_agent", side_effect=_boom):
        outcome = _run_launch_body_with_common_patches(app, prompt)

    assert outcome.severity == "error"
    entries = _entries(stash_path)
    assert [e.text for e in entries] == [prompt]
    assert entries[0].source == "failed_launch"
