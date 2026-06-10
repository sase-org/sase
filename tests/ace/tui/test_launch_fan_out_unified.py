"""Phase 5 (sase-12.5) — unified launch fan-out + source-aware refresh coalescing.

Multi-prompt / multi-model / repeat / bulk launches were each spinning up a
``threading.Thread`` directly, mutating the shared ``PromptContext`` dataclass,
and scheduling ``_schedule_agents_async_refresh`` once per spawned agent. This
test module pins the unified worker model and the
``request_agents_refresh("launch", ...)`` debounce that collapses bursts into
one deferred refresh.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agent_workflow._launch_bulk import BulkLaunchMixin
from sase.ace.tui.actions.agent_workflow._launch_delta import LaunchDeltaMixin
from sase.ace.tui.actions.agent_workflow._launch_multi_model import (
    MultiModelLaunchMixin,
    _write_fanout_failure_report,
)
from sase.ace.tui.actions.agent_workflow._launch_multi_prompt import (
    MultiPromptLaunchMixin,
)
from sase.ace.tui.actions.agent_workflow._launch_repeat import RepeatLaunchMixin
from sase.ace.tui.actions.agent_workflow._launch_tasks import LaunchTaskOutcome
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.agent.launch_types import AgentLaunchResult
from sase.xprompt.models import XPrompt


def _ctx() -> PromptContext:
    return PromptContext(
        project_name="proj",
        cl_name="cl",
        project_file="/tmp/proj.sase",
        workspace_dir="/tmp/ws",
        workspace_num=1,
        workflow_name="ace(run)-ts",
        timestamp="ts",
        history_sort_key="cl",
        display_name="cl",
        update_target="cl",
        is_home_mode=False,
    )


def _launch_result(
    index: int = 0,
    *,
    project_name: str = "proj",
    timestamp: str | None = None,
) -> AgentLaunchResult:
    timestamp = timestamp or f"260501_12000{index}"
    return AgentLaunchResult(
        pid=1000 + index,
        workspace_num=index + 1,
        workspace_dir=f"/tmp/ws{index + 1}",
        output_path=f"/tmp/out{index}.txt",
        project_file=f"/tmp/{project_name}/{project_name}.sase",
        project_name=project_name,
        workflow_name=f"ace(run)-{timestamp}",
        cl_name="cl",
        timestamp=timestamp,
    )


class _CoalesceApp(AgentLoadingMixin):
    """Minimal harness exposing the request_agents_refresh debounce."""

    def __init__(self) -> None:
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_scheduled = False
        self._agents_refresh_debounce_armed = False
        self._scheduled: list[Any] = []
        self._timer_calls: list[tuple[float, Callable[[], Any]]] = []
        self._nav_gate = NavigationGate(window_s=0.25)

    def call_later(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        del kwargs
        self._scheduled.append((callback, args))

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self._timer_calls.append((delay, callback))

    async def _load_agents_async(self) -> None:  # type: ignore[override]
        return


def test_request_agents_refresh_arms_one_timer_for_burst() -> None:
    """A burst of fan-out callbacks collapses into one deferred refresh."""
    app = _CoalesceApp()

    for _ in range(5):
        app.request_agents_refresh("launch")

    assert len(app._timer_calls) == 1
    delay, _ = app._timer_calls[0]
    assert delay == pytest.approx(0.150)
    assert app._agents_refresh_debounce_armed is True


def test_request_agents_refresh_re_arms_after_fire() -> None:
    """Once the debounce fires, the next burst arms a fresh timer."""
    app = _CoalesceApp()

    app.request_agents_refresh("launch")
    assert len(app._timer_calls) == 1

    # Simulate the timer firing.
    _, fire = app._timer_calls[-1]
    fire()  # type: ignore[misc]
    assert app._agents_refresh_debounce_armed is False
    # The fired timer hands off to _schedule_agents_async_refresh, which
    # call_laters _run_agents_async_refresh exactly once.
    scheduled_runs = [
        cb for cb, _ in app._scheduled if cb == app._run_agents_async_refresh
    ]
    assert len(scheduled_runs) == 1

    app.request_agents_refresh("launch")
    assert len(app._timer_calls) == 2


def test_request_agents_refresh_latest_only_false_resets_window() -> None:
    """``latest_only=False`` schedules a fresh timer for every request."""
    app = _CoalesceApp()

    app.request_agents_refresh("launch", latest_only=False)
    app.request_agents_refresh("launch", latest_only=False)
    app.request_agents_refresh("launch", latest_only=False)

    assert len(app._timer_calls) == 3


@pytest.mark.asyncio
async def test_launch_refresh_respects_navigation_gate() -> None:
    """While j/k is active, the post-burst refresh defers via set_timer."""
    app = _CoalesceApp()
    app._nav_gate.record()

    app.request_agents_refresh("launch")
    assert len(app._timer_calls) == 1

    # Fire the debounce timer manually to simulate the deferred dispatch.
    _, fire = app._timer_calls[0]
    fire()  # type: ignore[misc]

    # _schedule_agents_async_refresh posts _run_agents_async_refresh on
    # the loop. Run it: the gate is hot, so it must defer via set_timer
    # (no actual load yet).
    pending_runs = [
        cb for cb, _ in app._scheduled if cb == app._run_agents_async_refresh
    ]
    assert len(pending_runs) == 1
    app._scheduled.clear()
    await app._run_agents_async_refresh()

    # The gated refresh re-armed itself with a small delay rather than
    # running the apply leg.
    boundary_timers = [
        (d, cb) for d, cb in app._timer_calls if cb == app._run_agents_async_refresh
    ]
    assert boundary_timers, (
        "expected a gate-boundary set_timer for _run_agents_async_refresh"
    )


# ---- Fan-out helper tests ---------------------------------------------------


class _FanOutHarness:
    """Common attrs / shims used by all four fan-out tests."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.scheduled: list[tuple[Any, tuple[Any, ...]]] = []
        self.refresh_requests: list[str] = []
        self.launch_delta_batches: list[list[AgentLaunchResult]] = []
        self.launch_tasks: list[dict[str, Any]] = []
        self.launched: list[dict[str, Any]] = []
        self.refresh_display_calls: int = 0
        self.notification_refresh_count: int = 0

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def call_later(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        del kwargs
        self.scheduled.append((fn, args))

    def request_agents_refresh(
        self,
        source: str,
        *,
        debounce_ms: int = 150,
        latest_only: bool = True,
    ) -> None:
        del debounce_ms, latest_only
        self.refresh_requests.append(source)

    def _refresh_display(self) -> None:
        self.refresh_display_calls += 1

    def _refresh_notification_count(self) -> None:
        self.notification_refresh_count += 1

    def _submit_launch_task(
        self,
        *,
        display_name: str,
        cl_name: str,
        project_file: str,
        task_callable: Callable[[], LaunchTaskOutcome],
        dedup_key: str | None = None,
    ) -> bool:
        self.launch_tasks.append(
            {
                "display_name": display_name,
                "cl_name": cl_name,
                "project_file": project_file,
                "task_callable": task_callable,
                "dedup_key": dedup_key,
            }
        )
        return True

    def _apply_launch_outcome(self, outcome: LaunchTaskOutcome) -> None:
        if outcome.results:
            self._handle_launch_results_delta(list(outcome.results))
        if outcome.request_agents_refresh:
            self.request_agents_refresh("launch")
        if outcome.refresh_notifications:
            self._refresh_notification_count()
        if outcome.notify:
            self.notify(outcome.message, severity=outcome.severity)

    def _run_submitted_launch_tasks(self) -> None:
        while self.launch_tasks:
            task = self.launch_tasks.pop(0)
            self._apply_launch_outcome(task["task_callable"]())

    def _launch_background_agent(self, **kwargs: Any) -> AgentLaunchResult:
        self.launched.append(kwargs)
        return AgentLaunchResult(
            pid=123,
            workspace_num=kwargs["workspace_num"],
            workspace_dir=kwargs["workspace_dir"],
            output_path="/tmp/out.txt",
            project_file=kwargs["project_file"],
            project_name=kwargs["project_name"],
            workflow_name=kwargs["workflow_name"],
            cl_name=kwargs["cl_name"],
            timestamp=kwargs["timestamp"],
        )

    def _handle_launch_results_delta(
        self,
        results: list[AgentLaunchResult],
        *,
        source: str = "launch",
    ) -> None:
        assert source == "launch"
        self.launch_delta_batches.append(list(results))


class _MultiPromptApp(_FanOutHarness, MultiPromptLaunchMixin):
    pass


class _MultiModelApp(_FanOutHarness, MultiModelLaunchMixin):
    pass


class _RepeatApp(_FanOutHarness, RepeatLaunchMixin):
    pass


class _BulkApp(_FanOutHarness, BulkLaunchMixin):
    def __init__(self) -> None:
        super().__init__()
        self._bulk_changespecs = None
        self._prompt_context = None
        self.marked_indices = set()


class _LaunchDeltaApp(LaunchDeltaMixin):
    def __init__(self) -> None:
        self.delta_refreshes: list[tuple[list[str], str]] = []
        self.broad_refreshes: list[str] = []
        self._agents_refresh_trace_records: list[Any] = []

    def _schedule_agent_artifact_delta_refresh(
        self,
        artifact_dirs: list[Path],
        *,
        source: str = "launch",
    ) -> None:
        self.delta_refreshes.append(([str(path) for path in artifact_dirs], source))

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        self.broad_refreshes.append(source)


class _FakeMultiPrompt:
    """Stand-in for sase.agent.multi_prompt.MultiPrompt that bypasses isinstance."""

    def __init__(self, segments: list[str]) -> None:
        self.segments = segments
        self.local_xprompts: dict[str, Any] = {}


def test_launch_delta_handler_schedules_exact_artifact_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _LaunchDeltaApp()
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    app._handle_launch_results_delta(
        [
            _launch_result(
                0,
                project_name="proj",
                timestamp="260501_120000",
            )
        ]
    )

    assert app.broad_refreshes == []
    assert app.delta_refreshes == [
        (
            [
                str(
                    tmp_path
                    / ".sase"
                    / "projects"
                    / "proj"
                    / "artifacts"
                    / "ace-run"
                    / "20260501120000"
                )
            ],
            "launch",
        )
    ]


def test_launch_delta_handler_missing_result_falls_back_to_broad_refresh() -> None:
    app = _LaunchDeltaApp()

    app._handle_launch_results_delta([])

    assert app.delta_refreshes == []
    assert app.broad_refreshes == ["launch"]
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "missing_launch_result"
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

    def _fake_launch(**_kwargs: Any) -> list[AgentLaunchResult]:
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


def test_multi_model_launch_uses_canonical_multi_prompt_launcher() -> None:
    app = _MultiModelApp()
    ctx = _ctx()
    local_xprompts = {"_plan": XPrompt(name="_plan", content="Plan locally")}
    launched = [_launch_result(0), _launch_result(1)]

    with patch(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        return_value=launched,
    ) as launch_multi:
        outcome = app._run_multi_model_launch(
            ["%model:a p", "%model:b p"],
            ctx,
            ("git", "proj"),
            has_wait=False,
            fanout_kind="model",
            local_xprompts=local_xprompts,
        )

    launch_multi.assert_called_once()
    kwargs = launch_multi.call_args.kwargs
    assert kwargs["segments"] == ["%model:a p", "%model:b p"]
    assert kwargs["local_xprompts"] == local_xprompts
    assert kwargs["cl_name"] == "cl"
    assert kwargs["project_file"] == "/tmp/proj.sase"
    assert kwargs["project_name"] == "proj"
    assert kwargs["is_home_mode"] is False
    assert kwargs["vcs_ref"] == ("git", "proj")
    assert kwargs["default_bare_segments_to_home"] is False
    assert "on_agent_spawned" not in kwargs
    app._apply_launch_outcome(outcome)
    assert app.launch_delta_batches == [launched]


def test_multi_model_dispatch_snapshots_xprompts_without_broad_refresh() -> None:
    app = _MultiModelApp()
    ctx = _ctx()
    local_xprompts = {"_epic": XPrompt(name="_epic", content="Epic")}
    captured: dict[str, Any] = {}

    app._launch_multi_model_agents(
        ["#_epic"],
        ctx,
        None,
        has_wait=False,
        fanout_kind="alternatives",
        local_xprompts=local_xprompts,
    )
    local_xprompts["_late"] = XPrompt(name="_late", content="Late")

    assert app.refresh_requests == []
    assert len(app.launch_tasks) == 1

    def _capture_launch(**kwargs: Any) -> list[AgentLaunchResult]:
        captured["local_xprompts"] = kwargs["local_xprompts"]
        return []

    with patch(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        side_effect=_capture_launch,
    ):
        app._run_submitted_launch_tasks()

    assert set(captured["local_xprompts"]) == {"_epic"}


def test_multi_model_xprompt_alternatives_are_passed_as_planned_segments() -> None:
    app = _MultiModelApp()
    ctx = _ctx()
    segments = ["%name:ag.1\n#plan\nDo", "%name:ag.2\n#epic\nDo"]

    with patch(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        return_value=[_launch_result(0), _launch_result(1)],
    ) as launch_multi:
        app._run_multi_model_launch(
            segments,
            ctx,
            None,
            has_wait=False,
            fanout_kind="alternatives",
        )

    assert launch_multi.call_args.kwargs["segments"] == segments


def test_multi_model_failure_records_toast_and_persistent_notification() -> None:
    app = _MultiModelApp()
    ctx = _ctx()

    with (
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            side_effect=RuntimeError("workspace claim failed"),
        ),
        patch(
            "sase.ace.tui.actions.agent_workflow._launch_multi_model._write_fanout_failure_report",
            return_value=Path("/tmp/fanout_failure.txt"),
        ),
        patch("sase.notifications.append_notification") as append_notification,
    ):
        outcome = app._run_multi_model_launch(
            ["%name:ag.1\n#plan", "%name:ag.2\n#epic"],
            ctx,
            ("git", "proj"),
            has_wait=True,
            fanout_kind="alternatives",
        )

    append_notification.assert_called_once()
    notification = append_notification.call_args.args[0]
    assert notification.sender == "user-agent"
    assert notification.action == "ViewErrorReport"
    assert notification.action_data["source"] == "tui_prompt_fanout"
    assert notification.action_data["fanout_kind"] == "alternatives"
    assert "workspace claim failed" in notification.notes[1]

    app._apply_launch_outcome(outcome)

    assert app.notification_refresh_count == 1
    assert (
        "Prompt fan-out launch failed (see log)",
        "error",
    ) in app.notifications


def test_fanout_failure_report_includes_submitted_xprompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    submitted = "#swarm\n```text\nkeep fence safe\n```"

    report_path = _write_fanout_failure_report(
        "RuntimeError: workspace claim failed",
        ctx=_ctx(),
        vcs_ref=("git", "proj"),
        has_wait=True,
        fanout_kind="alternatives",
        slot_count=2,
        submitted_xprompt=submitted,
    )

    text = report_path.read_text(encoding="utf-8")
    assert "## Submitted XPrompt" in text
    assert "````markdown" in text
    assert submitted in text


def test_repeat_launch_runs_off_main_thread_and_batches_delta() -> None:
    from sase.agent.repeat_launcher import RepeatAgentSpec

    app = _RepeatApp()
    ctx = _ctx()

    def _fake_batch(
        prompt: str,
        *,
        base_spawn_fn: Callable[[RepeatAgentSpec], None],
        sleep_between: float = 0.0,
        timestamps: list[str] | None = None,
    ) -> list[RepeatAgentSpec]:
        del prompt, sleep_between
        assert timestamps == ["260501_120000", "260501_120001", "260501_120002"]
        specs = [
            RepeatAgentSpec(
                prompt="p",
                name=f"n{i}",
                iteration=i,
                total=3,
                timestamp=timestamps[i],
            )
            for i in range(3)
        ]
        for spec in specs:
            base_spawn_fn(spec)
        return specs

    with patch("sase.running_field.claim_next_axe_workspace", return_value=2):
        with patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/tmp/ws", None),
        ):
            with patch(
                "sase.running_field.get_workspace_directory", return_value="/tmp/ws"
            ):
                with patch(
                    "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
                    return_value=[
                        "260501_120000",
                        "260501_120001",
                        "260501_120002",
                    ],
                ):
                    with patch(
                        "sase.agent.repeat_launcher.spawn_repeat_batch",
                        side_effect=_fake_batch,
                    ):
                        outcome = app._run_repeat_launch(
                            "p %r:3", ctx, None, has_wait=False
                        )

    assert len(app.launched) == 3
    app._apply_launch_outcome(outcome)
    assert app.refresh_requests == []
    assert len(app.launch_delta_batches) == 1
    assert [result.timestamp for result in app.launch_delta_batches[0]] == [
        "260501_120000",
        "260501_120001",
        "260501_120002",
    ]


def test_bulk_launch_takes_changespec_snapshot() -> None:
    """Mutating ``_bulk_changespecs`` after dispatch must not affect the worker."""

    class _CS:
        def __init__(self, name: str) -> None:
            self.name = name
            self.project_basename = "proj"

    app = _BulkApp()
    app._bulk_changespecs = [_CS("a"), _CS("b")]  # type: ignore[list-item]
    app._prompt_context = _ctx()

    with patch("os.path.isfile", return_value=False):
        app._launch_bulk_agents("the prompt")

    # The bulk-launch entry zeros out the live ref before dispatch so a
    # subsequent mutation is impossible.  The worker received its own
    # local copy.
    assert app._bulk_changespecs is None
    # A tracked launch task was submitted to drive the worker.
    assert len(app.launch_tasks) == 1
    assert app.launch_tasks[0]["display_name"] == "launch bulk 2 CLs"
