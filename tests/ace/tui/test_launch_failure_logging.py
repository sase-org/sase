"""Per-category launch-failure persistence tests.

Asserts that each TUI launch path (single, fan-out, multi-prompt, repeat, bulk,
workflow, chop) durably records a ``launch_failures.jsonl`` entry with the
correct ``kind`` when the launch fails. ``~/.sase`` is isolated per test, so
the canonical log paths resolve into a tmpdir automatically.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sase.logs import launch_failures_jsonl_path, launch_failures_log_path
from tests.ace.tui._launch_fan_out_helpers import (
    _BulkApp,
    _ctx,
    _FakeMultiPrompt,
    _launch_result,
    _MultiModelApp,
    _MultiPromptApp,
    _RepeatApp,
)


def _records() -> list[dict[str, Any]]:
    path = launch_failures_jsonl_path()
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().strip().splitlines()
        if line.strip()
    ]


def _assert_persisted(kind: str) -> dict[str, Any]:
    records = _records()
    assert records, f"no launch-failure record persisted for kind={kind}"
    record = records[-1]
    assert record["kind"] == kind
    assert "traceback" in record and record["traceback"]
    # The human-readable sidecar log is always written too.
    assert launch_failures_log_path().exists()
    return record


def test_fanout_failure_persists_record() -> None:
    app = _MultiModelApp()
    with (
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=RuntimeError("fanout boom"),
        ),
        patch("sase.history.prompt.record_failed_launch_prompt"),
    ):
        outcome = app._run_multi_model_launch(
            ["a", "b"], _ctx(), None, False, "model", {}, "submitted", None
        )
    assert outcome.severity == "error"
    record = _assert_persisted("fanout")
    assert record["fanout_kind"] == "model"


def test_partial_fanout_failure_uses_log_hint_and_persists_record() -> None:
    from sase.agent.multi_prompt_launcher import MultiPromptPartialLaunchError

    app = _MultiModelApp()
    exc = MultiPromptPartialLaunchError([_launch_result()], RuntimeError("slot boom"))
    with (
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=exc,
        ),
        patch("sase.agent.partial_launch.rollback_partial_launch_results"),
        patch("sase.history.prompt.record_failed_launch_prompt"),
    ):
        outcome = app._run_multi_model_launch(
            ["a", "b"], _ctx(), None, False, "model", {}, "submitted", None
        )

    assert outcome.message == (
        "Prompt fan-out launch failed; spawned agents terminated "
        "- see Logs in SASE Admin Center (#)"
    )
    assert outcome.severity == "error"
    record = _assert_persisted("fanout")
    assert record["fanout_kind"] == "model"


def test_multi_prompt_failure_persists_record() -> None:
    app = _MultiPromptApp()
    multi = _FakeMultiPrompt(["one", "two"])
    with (
        patch("sase.agent.multi_prompt.MultiPrompt", _FakeMultiPrompt, create=True),
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=RuntimeError("mp boom"),
        ),
        patch("sase.history.prompt.record_failed_launch_prompt"),
    ):
        app._run_multi_prompt_launch(multi, _ctx(), None, "submitted")
    record = _assert_persisted("multi_prompt")
    assert record["segment_count"] == 2


def test_partial_multi_prompt_failure_uses_log_hint_and_persists_record() -> None:
    from sase.agent.multi_prompt_launcher import MultiPromptPartialLaunchError

    app = _MultiPromptApp()
    multi = _FakeMultiPrompt(["one", "two"])
    exc = MultiPromptPartialLaunchError([_launch_result()], RuntimeError("slot boom"))
    with (
        patch("sase.agent.multi_prompt.MultiPrompt", _FakeMultiPrompt, create=True),
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=exc,
        ),
        patch("sase.agent.partial_launch.rollback_partial_launch_results"),
        patch("sase.history.prompt.record_failed_launch_prompt"),
    ):
        outcome = app._run_multi_prompt_launch(multi, _ctx(), None, "submitted")

    assert outcome.message == (
        "Partial multi-prompt launch failed; spawned agents terminated "
        "- see Logs in SASE Admin Center (#)"
    )
    assert outcome.severity == "error"
    record = _assert_persisted("multi_prompt")
    assert record["partial"] is True
    assert record["segment_count"] == 2


def test_repeat_generic_failure_persists_record() -> None:
    app = _RepeatApp()
    with (
        patch(
            "sase.agent.repeat_launcher.extract_repeat_and_name",
            side_effect=RuntimeError("repeat boom"),
        ),
        patch("sase.history.prompt.record_failed_launch_prompt"),
    ):
        app._run_repeat_launch("%r:3 do it", _ctx(), None, False)
    record = _assert_persisted("repeat")
    assert record["name_collision"] is False


def test_repeat_name_collision_persists_record() -> None:
    from sase.agent.repeat_launcher import NameCollisionError

    app = _RepeatApp()
    with (
        patch(
            "sase.agent.repeat_launcher.extract_repeat_and_name",
            side_effect=NameCollisionError("dup name"),
        ),
        patch("sase.history.prompt.record_failed_launch_prompt"),
    ):
        outcome = app._run_repeat_launch("%r:3 do it", _ctx(), None, False)
    assert outcome.message == "dup name - see Logs in SASE Admin Center (#)"
    assert outcome.severity == "error"
    record = _assert_persisted("repeat")
    assert record["name_collision"] is True


def test_bulk_failure_persists_record() -> None:
    app = _BulkApp()
    with patch(
        "sase.agent.launch_timing.LaunchTimingRecorder",
        side_effect=RuntimeError("bulk boom"),
    ):
        outcome = app._run_bulk_launch("prompt", [])
    assert outcome.severity == "error"
    _assert_persisted("bulk")


def test_bulk_missing_project_file_item_persists_record() -> None:
    app = _BulkApp()
    cs = SimpleNamespace(name="cl-missing", project_basename="proj")

    outcome = app._run_bulk_launch("prompt", [cs])

    assert outcome.message == "Started 0 agent(s), 1 failed"
    assert outcome.severity == "warning"
    record = _assert_persisted("bulk")
    assert record["display_name"] == "cl-missing"
    assert record["project"] == "proj"
    assert record["stage"] == "project_file"
    assert record["slot_index"] == 0
    assert record["slot_count"] == 1
    assert record["exc_type"] == "FileNotFoundError"
    assert record["prompt_preview"] == "prompt"
    assert record["project_file"].endswith("/proj/proj.sase")


def test_bulk_workspace_allocation_item_persists_record() -> None:
    from sase.core.paths import sase_projects_dir

    project_dir = sase_projects_dir() / "proj"
    project_dir.mkdir(parents=True)
    (project_dir / "proj.sase").write_text("# Project\n", encoding="utf-8")

    app = _BulkApp()
    cs = SimpleNamespace(name="cl-workspace", project_basename="proj")
    with patch(
        "sase.running_field.get_first_available_axe_workspace",
        side_effect=RuntimeError("no workspace"),
    ):
        outcome = app._run_bulk_launch("prompt", [cs])

    assert outcome.message == "Started 0 agent(s), 1 failed"
    assert outcome.severity == "warning"
    record = _assert_persisted("bulk")
    assert record["display_name"] == "cl-workspace"
    assert record["project"] == "proj"
    assert record["stage"] == "workspace_allocation"
    assert record["slot_index"] == 0
    assert record["slot_count"] == 1
    assert record["exc_message"] == "no workspace"
    assert record["prompt_preview"] == "prompt"
    assert record["project_file"].endswith("/proj/proj.sase")


def test_single_body_failure_persists_record() -> None:
    from sase.ace.tui.actions.agent_workflow._launch_body import AgentLaunchBodyMixin

    class _BodyApp(AgentLaunchBodyMixin):
        def __init__(self) -> None:
            self.notifications: list[tuple[str, str | None]] = []

        def notify(self, msg: str, *, severity: str | None = None) -> None:
            self.notifications.append((msg, severity))

        def _schedule_prompt_stash_badge_refresh(self) -> None:
            pass

        def _run_agent_launch_body(self, prompt: str, ctx: Any = None) -> Any:
            raise RuntimeError("body boom")

    app = _BodyApp()
    asyncio.run(app._run_agent_launch_body_async("a prompt", _ctx()))
    assert app.notifications and app.notifications[-1][1] == "error"
    record = _assert_persisted("single")
    assert record["display_name"] == "cl"


def test_workflow_failure_persists_record(monkeypatch) -> None:
    from sase.ace.tui.actions.agent_workflow._workflow_exec import WorkflowExecMixin

    class _SyncThread:
        """Run the target synchronously on start() so the test is deterministic."""

        def __init__(self, *, target: Any = None, daemon: bool = False) -> None:
            self._target = target

        def start(self) -> None:
            if self._target is not None:
                self._target()

    class _WorkflowApp(WorkflowExecMixin):
        def __init__(self) -> None:
            self._prompt_context = None
            self.scheduled: list[Any] = []

        def call_later(self, fn: Any, *args: Any, **kwargs: Any) -> None:
            self.scheduled.append((fn, args))

        def notify(self, msg: str, *, severity: str | None = None) -> None:
            pass

    monkeypatch.setattr("threading.Thread", _SyncThread)
    monkeypatch.setattr(
        "sase.xprompt.execute_workflow",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("workflow boom")),
    )

    app = _WorkflowApp()
    assert app._execute_workflow_in_thread("eval/foo", [], {}) is True
    record = _assert_persisted("workflow")
    assert record["workflow_name"] == "eval/foo"
    assert record["project"] == "eval"


def test_chop_failure_persists_record() -> None:
    from sase.ace.tui.actions.axe_chop_run import AxeChopRunMixin

    class _ChopApp(AxeChopRunMixin):
        def __init__(self) -> None:
            self.notifications: list[tuple[str, str | None]] = []

        def notify(self, msg: str, *, severity: str | None = None) -> None:
            self.notifications.append((msg, severity))

        def _schedule_axe_async_refresh(self) -> None:
            pass

    match = SimpleNamespace(
        chop=SimpleNamespace(name="my-chop"),
        lumberjack=SimpleNamespace(chop_timeout=30),
    )
    app = _ChopApp()
    with (
        patch(
            "sase.ace.tui.actions.axe_chop_run.load_axe_config",
            return_value=object(),
        ),
        patch(
            "sase.ace.tui.actions.axe_chop_run.find_configured_chop",
            return_value=match,
        ),
        patch(
            "sase.ace.tui.actions.axe_chop_run.run_configured_chop_once",
            side_effect=RuntimeError("chop boom"),
        ),
    ):
        asyncio.run(app._launch_chop_run_async("lumber", "my-chop"))
    record = _assert_persisted("chop")
    assert record["chop"] == "my-chop"
    assert record["lumberjack"] == "lumber"
    assert app.notifications[-1] == (
        "Failed to launch chop 'my-chop': chop boom "
        "- see Logs in SASE Admin Center (#)",
        "error",
    )


def test_payloadless_launch_task_failure_persists_record() -> None:
    from sase.ace.tui.actions.agent_workflow._launch_tasks import LaunchTaskMixin
    from sase.ace.tui.actions.task_actions import TrackedTaskCompletion
    from sase.ace.tui.task_queue import TaskInfo

    class _TaskApp(LaunchTaskMixin):
        def __init__(self) -> None:
            self.notifications: list[tuple[str, str | None]] = []

        def notify(self, msg: str, *, severity: str | None = None) -> None:
            self.notifications.append((msg, severity))

    app = _TaskApp()
    app._on_launch_task_complete(
        TrackedTaskCompletion(
            task_info=TaskInfo(
                task_id="task-1",
                task_type="launch",
                cl_name="cl",
                project_file="/tmp/proj.sase",
                status="error",
                message="launch cl started",
                started_at=datetime.now(),
                display_name="launch cl",
            ),
            success=False,
            message="worker died",
            output="captured output",
            payload=None,
            error="worker died",
        )
    )

    assert app.notifications == [
        ("Launch failed - see Logs in SASE Admin Center (#)", "error")
    ]
    record = _assert_persisted("single")
    assert record["display_name"] == "launch cl"
    assert record["stage"] == "launch_task"
    assert record["task_id"] == "task-1"
    assert record["output"] == "captured output"


def test_chop_missing_script_outcome_persists_record() -> None:
    from sase.ace.tui.actions.axe_chop_run import AxeChopRunMixin
    from sase.axe.chop_runner_types import ChopRunOutcome

    class _ChopApp(AxeChopRunMixin):
        def __init__(self) -> None:
            self.notifications: list[tuple[str, str | None]] = []

        def notify(self, msg: str, *, severity: str | None = None) -> None:
            self.notifications.append((msg, severity))

        def _schedule_axe_async_refresh(self) -> None:
            pass

    match = SimpleNamespace(
        chop=SimpleNamespace(name="my-chop"),
        lumberjack=SimpleNamespace(chop_timeout=30),
    )
    outcome = ChopRunOutcome(
        lumberjack_name="lumber",
        chop_name="my-chop",
        status="missing_script",
        run_id="run-1",
        error=RuntimeError("script not found"),
        traceback="script traceback",
    )
    app = _ChopApp()
    with (
        patch(
            "sase.ace.tui.actions.axe_chop_run.load_axe_config",
            return_value=object(),
        ),
        patch(
            "sase.ace.tui.actions.axe_chop_run.find_configured_chop",
            return_value=match,
        ),
        patch(
            "sase.ace.tui.actions.axe_chop_run.run_configured_chop_once",
            return_value=outcome,
        ),
    ):
        asyncio.run(app._launch_chop_run_async("lumber", "my-chop"))

    assert app.notifications[-1] == (
        "Chop 'my-chop': script not found - see Logs in SASE Admin Center (#)",
        "error",
    )
    record = _assert_persisted("chop")
    assert record["chop"] == "my-chop"
    assert record["lumberjack"] == "lumber"
    assert record["status"] == "missing_script"
    assert record["run_id"] == "run-1"
