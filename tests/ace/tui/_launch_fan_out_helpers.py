"""Shared harnesses for launch fan-out tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.ace.tui.actions.agent_workflow._launch_bulk import BulkLaunchMixin
from sase.ace.tui.actions.agent_workflow._launch_delta import LaunchDeltaMixin
from sase.ace.tui.actions.agent_workflow._launch_multi_model import (
    MultiModelLaunchMixin,
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

    def _spawn_agents_refresh_task(self) -> None:
        self._scheduled.append((self._run_agents_async_refresh, ()))

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self._timer_calls.append((delay, callback))

    async def _load_agents_async(self) -> None:  # type: ignore[override]
        return


class _FanOutHarness:
    """Common attrs and shims used by the fan-out tests."""

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
        submitted_prompt: str | None = None,
    ) -> bool:
        self.launch_tasks.append(
            {
                "display_name": display_name,
                "cl_name": cl_name,
                "project_file": project_file,
                "task_callable": task_callable,
                "dedup_key": dedup_key,
                "submitted_prompt": submitted_prompt,
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
