"""Shared test doubles for Agents-tab wait and fork actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._wait_resume import AgentWaitResumeMixin
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.proc_queue import ProcInfo


def make_waiting_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "WAITING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
        "waiting_for": ["old_dep"],
        "wait_duration": 300.0,
        "wait_until": "2026-05-01T12:00:00",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeWaitResumeApp(AgentWaitResumeMixin):
    """Minimal app implementing what ``_apply_wait`` touches."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.refresh_calls = 0
        self.pushed_screens: list[tuple[object, object]] = []
        self.killed_agents: list[Agent] = []
        self.launch_prompts: list[str] = []
        self.prompt_contexts: list[dict[str, str | None]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        del list_changed, defer_detail
        self.refresh_calls += 1

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed_screens.append((screen, callback))

    def _submit_durable_proc(
        self,
        argv: Any,
        *,
        operation: str = "",
        request: Any = None,
        request_fingerprint: str = "",
        concurrency_keys: Any = (),
        proc_type: str | None = None,
        display_name: str | None = None,
        cl_name: str = "",
        project_file: str = "",
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
        **kwargs: Any,
    ) -> ProcInfo:
        del argv, operation, request_fingerprint, concurrency_keys
        del reload_on_complete, notify_on_complete, kwargs
        payload = dict(request or {})

        def _callable() -> TrackedProcResult[Any]:
            from sase.ops.commands.agent import _persist_directive_from_payload

            _persist_directive_from_payload(
                payload,
                artifacts_dir=str(payload.get("artifacts_dir") or project_file),
            )
            return TrackedProcResult(success=True, message="ok", payload=payload)

        return self._submit_tracked_proc(
            proc_type or "agent-directive",
            cl_name,
            project_file,
            _callable,
            display_name=display_name,
            on_complete=on_complete,
        )

    def _submit_tracked_proc(
        self,
        proc_type: str,
        cl_name: str,
        project_file: str,
        proc_callable: Any,
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> ProcInfo:
        del duplicate_message, reload_on_complete, notify_on_complete
        proc_info = ProcInfo(
            proc_id="task-0",
            proc_type=proc_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=datetime.now(),
            display_name=display_name,
            dedup_key=dedup_key,
        )
        try:
            result = proc_callable()
        except Exception as exc:
            result = TrackedProcResult(
                success=False,
                message=str(exc),
                error=str(exc),
            )
        proc_info.status = "success" if result.success else "error"
        proc_info.message = result.message
        proc_info.error = result.error
        if on_complete is not None:
            on_complete(
                TrackedProcCompletion(
                    proc_info=proc_info,
                    success=result.success,
                    message=result.message,
                    output="",
                    payload=result.payload,
                    error=result.error,
                )
            )
        return proc_info

    def _do_kill_agent(self, agent: Agent) -> None:
        self.killed_agents.append(agent)

    def _setup_home_prompt_context(
        self,
        *,
        display_name: str | None,
        history_sort_key: str | None,
    ) -> None:
        self.prompt_contexts.append(
            {
                "display_name": display_name,
                "history_sort_key": history_sort_key,
            }
        )

    def _finish_agent_launch(self, prompt: str) -> None:
        self.launch_prompts.append(prompt)


class FakeResumeActionApp(AgentWaitResumeMixin):
    """Minimal app implementing what the wait and fork actions touch."""

    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self._current_group_key: tuple[str, ...] | None = None
        self.panel_focus: object | None = None
        self.panel_keys: list[str | None] | None = None
        self.notifications: list[tuple[str, str]] = []
        self.prompt_bar_calls: list[dict[str, str | None]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _get_selected_agent(self) -> Agent | None:
        if self.panel_focus is not None:
            return None
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _resolve_focused_panel(self) -> object | None:
        return self.panel_focus

    def _panel_keys_per_agent(self) -> list[str | None]:
        if self.panel_keys is not None:
            return self.panel_keys
        return [agent.tribe for agent in self._agents]

    def _show_prompt_input_bar_for_home(
        self,
        *,
        initial_text: str = "",
        display_name: str | None = None,
        history_sort_key: str | None = None,
    ) -> None:
        self.prompt_bar_calls.append(
            {
                "initial_text": initial_text,
                "display_name": display_name,
                "history_sort_key": history_sort_key,
            }
        )


def make_clan_fixture(*, status: str = "RUNNING") -> tuple[Agent, Agent, Agent]:
    first = make_waiting_agent(
        cl_name="branch_one",
        raw_suffix="20240101120100",
        status=status,
        agent_name="one",
        agent_clan="builders",
        agent_clan_generation="gen-1",
    )
    second = make_waiting_agent(
        cl_name="branch_two",
        raw_suffix="20240101120200",
        status=status,
        agent_name="two",
        agent_clan="builders",
        agent_clan_generation="gen-1",
    )
    container = make_waiting_agent(
        cl_name="builders",
        raw_suffix=None,
        status=status,
        agent_clan="builders",
        agent_clan_generation="gen-1",
        is_clan_container=True,
    )
    container.runtime_children.extend((first, second))
    return container, first, second
