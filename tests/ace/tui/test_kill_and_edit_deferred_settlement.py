"""Focused and marked ``,x`` kill-and-edit must defer prompt mounting.

Kill/dismiss persistence for a kill-and-edit relaunch runs as a tracked
background proc. The prompt bar (focused row) or prompt stack (marked rows)
must not mount until that proc has settled, so a late bundle write from the
old cleanup cannot resurrect the name a replacement agent is about to reuse.
These tests drive the real ``_dismiss_done_agent`` / ``_do_kill_agent`` /
``_do_bulk_kill_agents`` persistence chain through
:class:`TrackedProcRecorderMixin`, which records the submitted proc instead
of running it immediately, so the test can assert nothing is mounted before
settlement and exactly the expected panes are mounted after.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.actions.agent_workflow._entry_relaunch import EntryRelaunchMixin
from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals import ConfirmKillAllModal, ConfirmKillModal
from sase.ace.tui.widgets import PromptInputBar
from tests._agent_cleanup_proc_helpers import TrackedProcRecorderMixin


class _DeferredKillEditApp(
    TrackedProcRecorderMixin, EntryRelaunchMixin, AgentsMixin, App[None]
):
    """Real Textual app driving the real persistence-proc submission chain."""

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
        self._agent_pre_question_status = {}
        self._dismissed_agents = set()
        self._dismissed_agent_objects = []
        self._marked_agents = set()
        self._marked_agent_order = []
        self._recent_dismissed_agent_groups = []
        self._prompt_context = None
        self.selected = selected
        self.notifications: list[tuple[str, str]] = []
        self.refresh_sources: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="host")

    def notify(
        self, message: str, *, severity: str = "information", **_kwargs: object
    ) -> None:
        self.notifications.append((message, severity))

    def _get_selected_agent(self) -> Agent | None:
        return (
            self.selected
            if self.selected is not None and self.selected in self._agents_with_children
            else None
        )

    def _unmount_prompt_bar(self) -> str:
        return ""

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


def _prompt_bar_ready(app: _DeferredKillEditApp) -> bool:
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


async def test_focused_dismiss_kill_and_edit_defers_prompt_bar_until_settled(
    tmp_path: Path,
) -> None:
    agent = _done_agent(tmp_path, "feature", "20260801190000", "%id:foo\nDo work")
    app = _DeferredKillEditApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: bool(app.tracked_procs))

        # The optimistic in-memory removal already ran, but the durable
        # persistence proc has not settled: no prompt bar yet.
        assert app._agents_with_children == []
        assert not app.query(PromptInputBar)

        task = app.tracked_procs[-1]
        assert task["proc_type"] == "dismiss"
        task["proc_callable"]()

        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        bar = app.query_one(PromptInputBar)
        assert len(bar.all_prompt_texts()) == 1
        assert app._dismiss_persistence_inflight == set()


async def test_focused_dismiss_kill_and_edit_rejected_submission_mounts_immediately(
    tmp_path: Path,
) -> None:
    """A collision that rejects the proc submission cannot strand the prompt."""
    agent = _done_agent(tmp_path, "feature", "20260801190050", "%id:foo\nDo work")
    app = _DeferredKillEditApp([agent], selected=agent)
    # Simulate an already-in-flight dismiss persistence proc for this
    # identity so ``_submit_dismiss_persistence_task`` rejects submission
    # instead of queuing a new tracked proc.
    app._dismiss_persistence_inflight.add(agent.identity)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        # No proc was ever submitted, yet the prepared prompt still mounted
        # via the immediate on_settled() fallback.
        assert app.tracked_procs == []
        assert len(app.query_one(PromptInputBar).all_prompt_texts()) == 1


async def test_focused_kill_and_edit_defers_prompt_bar_until_settled(
    tmp_path: Path,
) -> None:
    agent = _running_agent(tmp_path, "feature", "20260801190100", "%id:foo\nDo work")
    app = _DeferredKillEditApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmKillModal))

        await pilot.press("y")
        await wait_for(pilot, lambda: bool(app.tracked_procs))

        assert app._agents_with_children == []
        assert not app.query(PromptInputBar)

        task = app.tracked_procs[-1]
        assert task["proc_type"] == "kill"
        task["proc_callable"]()

        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        assert len(app.query_one(PromptInputBar).all_prompt_texts()) == 1
        assert app._kill_persistence_inflight == set()


async def test_focused_kill_and_edit_cancel_stays_non_destructive_and_unsubmitted(
    tmp_path: Path,
) -> None:
    agent = _running_agent(tmp_path, "feature", "20260801190200", "%id:foo\nDo work")
    app = _DeferredKillEditApp([agent], selected=agent)

    async with app.run_test(size=(100, 35)) as pilot:
        app._kill_and_edit_agent()
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmKillModal))

        await pilot.press("n")
        await wait_for(pilot, lambda: not isinstance(app.screen, ConfirmKillModal))

        assert app._agents_with_children == [agent]
        assert app.tracked_procs == []
        assert not app.query(PromptInputBar)


async def test_marked_bulk_kill_and_edit_defers_prompt_stack_until_settled(
    tmp_path: Path,
) -> None:
    killed = _running_agent(tmp_path, "live", "20260801190300", "%id:live\nFirst")
    dismissed = _done_agent(tmp_path, "done", "20260801190400", "%id:done\nSecond")
    app = _DeferredKillEditApp([killed, dismissed])
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
        assert not app.query(PromptInputBar)

        task = app.tracked_procs[-1]
        task["proc_callable"]()

        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        bar = app.query_one(PromptInputBar)
        assert bar.all_prompt_texts() == ["%id:!live\nFirst", "%id:!done\nSecond"]
