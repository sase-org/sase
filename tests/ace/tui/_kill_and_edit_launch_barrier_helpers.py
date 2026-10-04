"""Shared fixtures for kill-and-edit launch-barrier TUI tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.actions.agent_workflow._entry_relaunch import EntryRelaunchMixin
from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
    KillAndEditLastLaunchMixin,
)
from sase.ace.tui.actions.agent_workflow._launch_procs import LaunchProcMixin
from sase.ace.tui.actions.agent_workflow._launch_start import AgentLaunchStartMixin
from sase.ace.tui.actions.agent_workflow._prompt_bar_mount import PromptBarMountMixin
from sase.ace.tui.actions.agent_workflow._prompt_bar_submit import PromptBarSubmitMixin
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import PromptInputBar
from tests._agent_cleanup_proc_helpers import TrackedProcRecorderMixin


class LaunchBarrierApp(
    TrackedProcRecorderMixin,
    KillAndEditLastLaunchMixin,
    EntryRelaunchMixin,
    AgentsMixin,
    AgentLaunchStartMixin,
    LaunchProcMixin,
    App[None],
):
    """Real Textual app driving the real persistence + launch submission chain."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, agents: list[Agent], selected: Agent | None = None) -> None:
        super().__init__()
        self._init_tracked_task_recorder()
        self.current_tab = "agents"  # type: ignore[assignment]
        self.current_idx = 0
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._kill_persistence_inflight = set()
        self._dismiss_persistence_inflight = set()
        self._agent_status_overrides = {}
        self._dismissed_agents = set()
        self._dismissed_agent_objects = []
        self._marked_agents = set()
        self._marked_agent_order = []
        self._recent_dismissed_agent_groups = []
        self._prompt_context = None
        self._bulk_patches = None
        self.selected = selected
        self.notifications: list[tuple[str, str]] = []
        self.refresh_sources: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="host")

    def notify(
        self, message: str, *, severity: str = "information", **_kwargs: object
    ) -> None:
        self.notifications.append((message, severity))

    def _submit_durable_proc(
        self, argv: Any, *, request: Any = None, **kwargs: Any
    ) -> Any:
        proc_info = super()._submit_durable_proc(argv, request=request, **kwargs)
        self.tracked_procs[-1]["request"] = dict(request or {})
        return proc_info

    def _get_selected_agent(self) -> Agent | None:
        return (
            self.selected
            if self.selected is not None and self.selected in self._agents_with_children
            else None
        )

    def _unmount_prompt_bar(self) -> str:
        return ""

    def _unmount_prompt_bar_after_submit(self) -> None:
        pass

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        del list_changed, defer_detail

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        del prior_pos

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        self.refresh_sources.append(source)

    def _schedule_notification_snapshot_refresh(self) -> None:
        pass

    def _reload_and_reposition(self) -> None:
        pass


class PromptLifecycleApp(
    TrackedProcRecorderMixin,
    KillAndEditLastLaunchMixin,
    EntryRelaunchMixin,
    PromptBarMountMixin,
    PromptBarSubmitMixin,
    AgentLaunchStartMixin,
    LaunchProcMixin,
    App[None],
):
    """Real prompt-bar lifecycle harness with in-memory history/launch effects."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self._init_tracked_task_recorder()
        self.current_tab = "agents"  # type: ignore[assignment]
        self._prompt_context = None
        self._bulk_patches = None
        self._plan_feedback_context = None
        self._approve_prompt_context = None
        self.notifications: list[tuple[str, str | None]] = []
        self.saved_cancelled: list[str] = []
        self.timers: list[Any] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="host")

    def notify(
        self, message: str, *, severity: str | None = "information", **_kwargs: object
    ) -> None:
        self.notifications.append((message, severity))

    def _submit_durable_proc(
        self, argv: Any, *, request: Any = None, **kwargs: Any
    ) -> Any:
        proc_info = super()._submit_durable_proc(argv, request=request, **kwargs)
        self.tracked_procs[-1]["request"] = dict(request or {})
        return proc_info

    def _save_text_as_cancelled(
        self,
        text: str,
        *,
        record_segments: bool = True,
    ) -> str:
        del record_segments
        text = text.strip()
        if text:
            self.saved_cancelled.append(text)
        return text

    def set_timer(
        self, delay: float, callback: Callable[[], None], name: str = ""
    ) -> Any:
        timer = SimpleNamespace(
            stop=lambda: None, callback=callback, delay=delay, name=name
        )
        self.timers.append(timer)
        return timer

    def _mounted_prompt_bar(self) -> PromptInputBar | None:
        try:
            return self.query_one("#prompt-input-bar", PromptInputBar)
        except Exception:
            return None


class RealBarLaunchApp(PromptBarMountMixin, LaunchBarrierApp):
    """:class:`LaunchBarrierApp` with the real prompt-bar unmount.

    A submitted or cancelled prompt really removes its bar, so a restored
    prompt can mount a fresh one. History writes stay in memory.
    """

    def __init__(self, agents: list[Agent], selected: Agent | None = None) -> None:
        super().__init__(agents, selected)
        self.saved_cancelled: list[str] = []

    def _save_text_as_cancelled(
        self, text: str, *, record_segments: bool = True
    ) -> str:
        del record_segments
        text = text.strip()
        if text:
            self.saved_cancelled.append(text)
        return text

    def _mounted_prompt_bar(self) -> PromptInputBar | None:
        try:
            return self.query_one("#prompt-input-bar", PromptInputBar)
        except Exception:
            return None


def prompt_bar_ready(app: LaunchBarrierApp | PromptLifecycleApp) -> bool:
    for bar in app.query(PromptInputBar):
        if bar.query("#frontmatter-raw"):
            return True
    return False


def _write_prompt(directory: Path, prompt: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "raw_prompt.md").write_text(prompt, encoding="utf-8")
    return directory


def done_agent(tmp_path: Path, cl_name: str, raw_suffix: str, prompt: str) -> Agent:
    artifacts = _write_prompt(tmp_path / raw_suffix, prompt)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/projects/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 8, 1, 19, 0, 0),
        raw_suffix=raw_suffix,
        artifacts_dir=str(artifacts),
        agent_name=cl_name,
        pid=None,
    )


def done_agent_without_raw_suffix(tmp_path: Path, cl_name: str, prompt: str) -> Agent:
    """A DONE agent whose ``raw_suffix`` is unknown (the dismiss guard case)."""
    artifacts = _write_prompt(tmp_path / "no_suffix", prompt)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/projects/proj/proj.sase",
        status="DONE",
        start_time=datetime(2026, 8, 1, 19, 0, 0),
        raw_suffix=None,
        artifacts_dir=str(artifacts),
        agent_name=cl_name,
        pid=None,
    )


def running_agent(tmp_path: Path, cl_name: str, raw_suffix: str, prompt: str) -> Agent:
    artifacts = _write_prompt(tmp_path / raw_suffix, prompt)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/projects/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 8, 1, 19, 0, 0),
        raw_suffix=raw_suffix,
        artifacts_dir=str(artifacts),
        agent_name=cl_name,
        pid=4242,
    )


def home_prompt_context(display_name: str = "home-prompt") -> PromptContext:
    return PromptContext(
        project_name="home",
        cl_name=None,
        project_file="/tmp/home.sase",
        workspace_dir="/tmp",
        workspace_num=0,
        workflow_name="ace(run)-seed",
        timestamp="seed",
        history_sort_key=display_name,
        display_name=display_name,
        update_target="",
        is_home_mode=True,
    )


def submit_launch(
    app: LaunchBarrierApp | PromptLifecycleApp, prompt: str, *, keep_bar: bool = False
) -> None:
    with patch(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
        return_value=["forced-ts"],
    ):
        app._submit_resolved_launch(prompt, keep_bar=keep_bar)


def waiting_notified(app: LaunchBarrierApp | PromptLifecycleApp) -> bool:
    return any(
        "Waiting for kill/dismiss cleanup" in message
        for message, _ in app.notifications
    )


def launch_procs(app: LaunchBarrierApp | PromptLifecycleApp) -> list[dict[str, Any]]:
    return [task for task in app.tracked_procs if task["proc_type"] == "launch"]


def barriers(app: LaunchBarrierApp | PromptLifecycleApp) -> list[Any]:
    # The barrier list is created lazily on first use; a scenario that opens
    # no barrier (e.g. a cancelled kill) never touches the attribute at all.
    return getattr(app, "_relaunch_cleanup_barriers", [])
