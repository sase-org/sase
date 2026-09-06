"""Focused and marked ``,x`` kill-and-edit mount immediately; the launch waits.

The prompt bar (focused row) or prompt stack (marked rows) mounts as soon as
the kill/dismiss is applied optimistically in memory -- it no longer waits
for that cleanup's durable persistence proc to settle. Instead, a relaunch
cleanup barrier (``agent_workflow/_relaunch_barrier.py``) holds the eventual
*launch* until every open barrier settles, so a late bundle write from the
old cleanup still cannot resurrect the name a replacement agent is about to
reuse. These tests drive the real ``_dismiss_done_agent`` / ``_do_kill_agent``
/ ``_do_bulk_kill_agents`` persistence chain and the real
``_submit_resolved_launch`` gate through :class:`TrackedProcRecorderMixin`,
which records submitted procs instead of running them immediately.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.actions.agent_workflow import _relaunch_barrier
from sase.ace.tui.actions.agent_workflow._entry_relaunch import EntryRelaunchMixin
from sase.ace.tui.actions.agent_workflow._launch_procs import LaunchProcMixin
from sase.ace.tui.actions.agent_workflow._launch_start import AgentLaunchStartMixin
from sase.ace.tui.actions.agent_workflow._prompt_bar_mount import PromptBarMountMixin
from sase.ace.tui.actions.agent_workflow._prompt_bar_submit import PromptBarSubmitMixin
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.actions.agent_workflow._types import (
    RelaunchOperation,
    begin_prompt_session,
)
from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals import ConfirmKillAllModal, ConfirmKillModal
from sase.ace.tui.widgets import PromptInputBar
from tests._agent_cleanup_proc_helpers import TrackedProcRecorderMixin


class _LaunchBarrierApp(
    TrackedProcRecorderMixin,
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


class _PromptLifecycleApp(
    TrackedProcRecorderMixin,
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


def _prompt_bar_ready(app: _LaunchBarrierApp) -> bool:
    for bar in app.query(PromptInputBar):
        if bar.query("#frontmatter-raw"):
            return True
    return False


def _write_prompt(directory: Path, prompt: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "raw_xprompt.md").write_text(prompt, encoding="utf-8")
    return directory


def _done_agent(tmp_path: Path, cl_name: str, raw_suffix: str, prompt: str) -> Agent:
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


def _done_agent_without_raw_suffix(tmp_path: Path, cl_name: str, prompt: str) -> Agent:
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


def _running_agent(tmp_path: Path, cl_name: str, raw_suffix: str, prompt: str) -> Agent:
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


def _home_prompt_context(display_name: str = "home-prompt") -> PromptContext:
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


def _submit_launch(
    app: _LaunchBarrierApp, prompt: str, *, keep_bar: bool = False
) -> None:
    with patch(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
        return_value=["forced-ts"],
    ):
        app._submit_resolved_launch(prompt, keep_bar=keep_bar)


def _waiting_notified(app: _LaunchBarrierApp) -> bool:
    return any(
        "Waiting for kill/dismiss cleanup" in message
        for message, _ in app.notifications
    )


def _launch_procs(app: _LaunchBarrierApp) -> list[dict[str, Any]]:
    return [task for task in app.tracked_procs if task["proc_type"] == "launch"]


def _barriers(app: _LaunchBarrierApp) -> list[Any]:
    # The barrier list is created lazily on first use; a scenario that opens
    # no barrier (e.g. a cancelled kill) never touches the attribute at all.
    return getattr(app, "_relaunch_cleanup_barriers", [])


# --- Focused / marked ``,x`` mounts immediately -----------------------------


async def test_focused_dismiss_kill_and_edit_mounts_prompt_bar_immediately(
    tmp_path: Path,
) -> None:
    agent = _done_agent(tmp_path, "feature", "20260801190000", "%id:foo\nDo work")
    app = _LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: bool(app.tracked_procs))

        # The optimistic in-memory removal already ran, and the prompt bar
        # is ready without waiting for the durable persistence proc.
        assert app._agents_with_children == []
        await wait_for(pilot, lambda: _prompt_bar_ready(app))
        bar = app.query_one(PromptInputBar)
        assert len(bar.all_prompt_texts()) == 1

        # The barrier is still open: settling it releases nothing (there's
        # no pending launch), but it must clear on settlement.
        assert _barriers(app)

        task = app.tracked_procs[-1]
        assert task["proc_type"] == "dismiss"
        task["proc_callable"]()

        assert app._dismiss_persistence_inflight == set()
        assert _barriers(app) == []


async def test_focused_dismiss_kill_and_edit_rejected_submission_mounts_and_settles(
    tmp_path: Path,
) -> None:
    """A collision that rejects the proc submission cannot strand the prompt."""
    agent = _done_agent(tmp_path, "feature", "20260801190050", "%id:foo\nDo work")
    app = _LaunchBarrierApp([agent], selected=agent)
    # Simulate an already-in-flight dismiss persistence proc for this
    # identity so ``_submit_dismiss_persistence_task`` rejects submission
    # instead of queuing a new tracked proc.
    app._dismiss_persistence_inflight.add(agent.identity)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        # No proc was ever submitted, yet the prepared prompt still mounted
        # via the immediate on_settled() fallback, and no barrier is left
        # pending.
        assert app.tracked_procs == []
        assert len(app.query_one(PromptInputBar).all_prompt_texts()) == 1
        assert _barriers(app) == []


async def test_focused_kill_and_edit_mounts_prompt_bar_immediately(
    tmp_path: Path,
) -> None:
    agent = _running_agent(tmp_path, "feature", "20260801190100", "%id:foo\nDo work")
    app = _LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmKillModal))

        await pilot.press("y")
        await wait_for(pilot, lambda: bool(app.tracked_procs))

        assert app._agents_with_children == []
        await wait_for(pilot, lambda: _prompt_bar_ready(app))
        assert len(app.query_one(PromptInputBar).all_prompt_texts()) == 1
        assert _barriers(app)

        task = app.tracked_procs[-1]
        assert task["proc_type"] == "kill"
        task["proc_callable"]()

        assert app._kill_persistence_inflight == set()
        assert _barriers(app) == []


async def test_focused_kill_and_edit_cancel_mounts_nothing_and_leaves_no_barrier(
    tmp_path: Path,
) -> None:
    agent = _running_agent(tmp_path, "feature", "20260801190200", "%id:foo\nDo work")
    app = _LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmKillModal))

        await pilot.press("n")
        await wait_for(pilot, lambda: not isinstance(app.screen, ConfirmKillModal))

        assert app._agents_with_children == [agent]
        assert app.tracked_procs == []
        assert not app.query(PromptInputBar)
        assert not _barriers(app)


async def test_focused_dismiss_kill_and_edit_missing_raw_suffix_mounts_nothing(
    tmp_path: Path,
) -> None:
    agent = _done_agent_without_raw_suffix(tmp_path, "feature", "%id:foo\nDo work")
    app = _LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(
            pilot,
            lambda: any(
                "Cannot dismiss agent" in message for message, _ in app.notifications
            ),
        )

        assert app._agents_with_children == [agent]
        assert app.tracked_procs == []
        assert not app.query(PromptInputBar)
        assert not _barriers(app)


async def test_marked_bulk_kill_and_edit_mounts_prompt_stack_immediately(
    tmp_path: Path,
) -> None:
    killed = _running_agent(tmp_path, "live", "20260801190300", "%id:live\nFirst")
    dismissed = _done_agent(tmp_path, "done", "20260801190400", "%id:done\nSecond")
    app = _LaunchBarrierApp([killed, dismissed])
    app._marked_agents = {killed.identity, dismissed.identity}
    app._marked_agent_order = [killed.identity, dismissed.identity]

    async with app.run_test(size=(100, 35)) as pilot:
        app._bulk_kill_marked_agents_and_edit()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmKillAllModal))

        # ConfirmKillAllModal needs an extra settle tick before its key
        # binding takes effect once freshly mounted; matches the double
        # ``pilot.press("y")`` pattern used elsewhere for this modal.
        await pilot.press("y")
        await pilot.pause()
        if isinstance(app.screen, ConfirmKillAllModal):
            await pilot.press("y")
        await wait_for(pilot, lambda: bool(app.tracked_procs))

        # One combined bulk proc handles both the killed and dismissed rows.
        assert app._agents_with_children == []
        await wait_for(pilot, lambda: _prompt_bar_ready(app))
        bar = app.query_one(PromptInputBar)
        assert bar.all_prompt_texts() == ["%id:!live\nFirst", "%id:!done\nSecond"]
        assert _barriers(app)

        task = app.tracked_procs[-1]
        task["proc_callable"]()

        assert _barriers(app) == []


# --- The relaunch cleanup barrier gates the launch, not the mount ----------


async def test_launch_held_while_barrier_pending_then_replays_once_settled(
    tmp_path: Path,
) -> None:
    """Direct regression test for 1b2381366: order, not mount, is protected."""
    agent = _done_agent(tmp_path, "feature", "20260801190500", "%id:foo\nDo work")
    app = _LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: bool(app.tracked_procs))
        await wait_for(pilot, lambda: _prompt_bar_ready(app))
        assert app._prompt_context is not None

        cleanup_task = app.tracked_procs[-1]
        prompt = "%id:!foo\nDo work edited"
        _submit_launch(app, prompt)

        # No launch proc submitted while the barrier is pending.
        assert _launch_procs(app) == []
        assert _waiting_notified(app)

        cleanup_task["proc_callable"]()
        await wait_for(pilot, lambda: bool(_launch_procs(app)))

        launched = _launch_procs(app)
        assert len(launched) == 1
        assert launched[0]["request"]["prompt"] == prompt
        assert _barriers(app) == []


async def test_submit_resolved_launch_without_pending_barrier_submits_immediately() -> (
    None
):
    app = _LaunchBarrierApp([])

    async with app.run_test(size=(100, 35)):
        app._prompt_context = _home_prompt_context()
        _submit_launch(app, "%id:!foo\nDo work")

        launched = _launch_procs(app)
        assert len(launched) == 1
        assert not _waiting_notified(app)


async def test_cancelling_prompt_bar_during_hold_drops_parked_launch(
    tmp_path: Path,
) -> None:
    agent = _done_agent(tmp_path, "feature", "20260801190600", "%id:foo\nDo work")
    app = _LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: bool(app.tracked_procs))
        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        cleanup_task = app.tracked_procs[-1]
        _submit_launch(app, "%id:!foo\nDo work edited")
        assert _launch_procs(app) == []

        # The user cancelled the prompt bar while the launch was held; the
        # cancel path already saved the text to prompt history.
        app._prompt_context = None

        cleanup_task["proc_callable"]()
        await pilot.pause()

        assert _barriers(app) == []
        assert _launch_procs(app) == []


def test_cancelled_hold_drops_old_submit_and_new_prompt_launches() -> None:
    app = _PromptLifecycleApp()
    operation = RelaunchOperation("old kill-and-edit")

    barrier = _relaunch_barrier.open_relaunch_cleanup_barrier(
        app,
        "old cleanup",
        operation=operation,
    )
    begin_prompt_session(
        app,
        _home_prompt_context("old"),
        relaunch_operation=operation,
    )

    _submit_launch(app, "%id:!old\nold edited")
    assert _launch_procs(app) == []

    app.on_prompt_input_bar_cancelled(
        PromptInputBar.Cancelled(
            "%id:!old\nold",
            "prompt",
            record_segments=False,
        )
    )
    assert app._prompt_context is None
    assert app.saved_cancelled == ["%id:!old\nold"]

    begin_prompt_session(app, _home_prompt_context("new"))
    _submit_launch(app, "%id:new\nnew")

    launched = _launch_procs(app)
    assert len(launched) == 1
    assert launched[0]["request"]["prompt"] == "%id:new\nnew"

    _relaunch_barrier.settle_relaunch_cleanup_barrier(app, barrier)

    launched = _launch_procs(app)
    assert len(launched) == 1
    assert launched[0]["request"]["prompt"] == "%id:new\nnew"


def test_repeated_whole_bar_submit_while_held_replays_once() -> None:
    app = _PromptLifecycleApp()
    operation = RelaunchOperation("duplicate submit cleanup")

    barrier = _relaunch_barrier.open_relaunch_cleanup_barrier(
        app,
        "duplicate cleanup",
        operation=operation,
    )
    begin_prompt_session(
        app,
        _home_prompt_context("duplicate"),
        relaunch_operation=operation,
    )

    prompt = "%id:!dup\none edited"
    _submit_launch(app, prompt)
    _submit_launch(app, prompt)

    assert _launch_procs(app) == []

    _relaunch_barrier.settle_relaunch_cleanup_barrier(app, barrier)

    launched = _launch_procs(app)
    assert len(launched) == 1
    assert launched[0]["request"]["prompt"] == prompt


async def test_barrier_timeout_releases_held_launch_with_warning(
    tmp_path: Path,
) -> None:
    agent = _done_agent(tmp_path, "feature", "20260801190700", "%id:foo\nDo work")
    app = _LaunchBarrierApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: bool(app.tracked_procs))
        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        prompt = "%id:!foo\nDo work edited"
        _submit_launch(app, prompt)
        assert _launch_procs(app) == []

        # The cleanup proc's callable never runs (a hung supervisor);
        # simulate the timer firing directly rather than sleeping in real
        # time for ``RELAUNCH_CLEANUP_BARRIER_TIMEOUT_SECONDS``.
        barrier = _barriers(app)[0]
        _relaunch_barrier._settle_on_timeout(app, barrier)

        assert _barriers(app) == []
        launched = _launch_procs(app)
        assert len(launched) == 1
        assert launched[0]["request"]["prompt"] == prompt
        assert any(
            "did not settle in time" in message and severity == "warning"
            for message, severity in app.notifications
        )


async def test_two_overlapping_barriers_replay_parked_launch_once(
    tmp_path: Path,
) -> None:
    """Two overlapping ``,x`` cleanups; only the second settling drains the launch.

    Each kill-and-edit still mounts its own prompt bar in production; that
    mounting is already covered by the single-agent tests above, so here the
    mount itself is stubbed out to isolate the barrier bookkeeping (two open
    barriers, one shared parked launch) from unrelated Textual widget-ID
    plumbing.
    """
    first = _done_agent(tmp_path, "one", "20260801190800", "%id:one\nFirst")
    second = _done_agent(tmp_path, "two", "20260801190900", "%id:two\nSecond")
    app = _LaunchBarrierApp([first, second], selected=first)
    app._edit_and_relaunch_agent = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: len(app.tracked_procs) == 1)

        app.selected = second
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: len(app.tracked_procs) == 2)

        assert len(_barriers(app)) == 2

        operation = _barriers(app)[1].operation
        begin_prompt_session(
            app,
            _home_prompt_context(),
            relaunch_operation=operation,
        )
        prompt = "%id:!two\nSecond edited"
        _submit_launch(app, prompt)
        assert _launch_procs(app) == []

        app.tracked_procs[0]["proc_callable"]()
        assert len(_barriers(app)) == 1
        assert _launch_procs(app) == []

        app.tracked_procs[1]["proc_callable"]()
        await wait_for(pilot, lambda: bool(_launch_procs(app)))

        launched = _launch_procs(app)
        assert len(launched) == 1
        assert launched[0]["request"]["prompt"] == prompt
        assert _barriers(app) == []
