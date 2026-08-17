"""Shared harnesses for launch refresh and launch-delta tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.ace.tui.actions.agent_workflow._launch_delta import LaunchDeltaMixin
from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.agent.launch_types import AgentLaunchResult


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
