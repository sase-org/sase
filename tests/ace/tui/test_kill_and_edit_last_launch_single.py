"""Single-result ``,X`` kill-and-edit confirmation tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow._entry_relaunch import EntryRelaunchMixin
from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
    KillAndEditLastLaunchMixin,
)
from sase.ace.tui.actions.agent_workflow._launch_records import (
    LaunchRecordState,
    latest_live_launch_record,
    push_launch_record,
    stamp_launch_record_results,
)
from sase.ace.tui.modals import ConfirmKillModal

from tests.ace.tui._kill_and_edit_last_launch_helpers import (
    _FakeAgent,
    _context,
    _matchable_result,
)

# --- resolved single-result: same confirmation rule as ,x ------------------


class _SingleResultApp(KillAndEditLastLaunchMixin, EntryRelaunchMixin):
    """Exercises the real ``_kill_and_edit_agent`` delegation, unstubbed."""

    def __init__(
        self,
        agent: _FakeAgent,
        *,
        kill_result: bool = True,
        dismiss_result: bool = True,
    ) -> None:
        self._agents_with_children = [agent]
        self._agents = [agent]
        self.kill_result = kill_result
        self.dismiss_result = dismiss_result
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.notifications: list[tuple[str, str | None]] = []
        self.killed: list[Any] = []
        self.dismissed: list[Any] = []
        self.launched: tuple[str, str, str, bool] | None = None

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _do_kill_agent(
        self, agent: Any, *, on_settled: Callable[[], None] | None = None
    ) -> bool:
        self.killed.append(agent)
        if self.kill_result and on_settled is not None:
            on_settled()
        return self.kill_result

    def _dismiss_done_agent(
        self, agent: Any, *, on_settled: Callable[[], None] | None = None
    ) -> bool:
        self.dismissed.append(agent)
        if self.dismiss_result and on_settled is not None:
            on_settled()
        return self.dismiss_result

    def _edit_and_relaunch_agent(
        self,
        raw_prompt: str,
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        self.launched = (raw_prompt, project_file, cl_name, is_project_agent)


def test_single_result_dismissable_row_skips_confirmation_like_plain_x(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _FakeAgent("done-agent", status="DONE", pid=None)
    app = _SingleResultApp(agent)
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("done-agent")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [agent],
    )

    app._kill_and_edit_last_launch()

    assert app.dismissed == [agent]
    assert app.killed == []
    assert app.pushed_modals == []
    assert app.launched == ("Do work", agent.project_file, agent.cl_name, False)
    assert record.state is LaunchRecordState.CONSUMED


def test_single_result_live_pid_row_asks_for_confirmation_like_plain_x(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _FakeAgent("running-agent", status="RUNNING", pid=111)
    app = _SingleResultApp(agent)
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("running-agent")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [agent],
    )

    app._kill_and_edit_last_launch()

    assert len(app.pushed_modals) == 1
    assert isinstance(app.pushed_modals[0], ConfirmKillModal)
    assert app.killed == []
    assert record.state is LaunchRecordState.RESOLVED_ACTION_PENDING

    app.pushed_callbacks[-1](True)

    assert app.killed == [agent]
    assert app.launched == ("Do work", agent.project_file, agent.cl_name, False)
    assert record.state is LaunchRecordState.CONSUMED


def test_single_result_confirmation_cancel_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _FakeAgent("running-agent", status="RUNNING", pid=111)
    app = _SingleResultApp(agent)
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("running-agent")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [agent],
    )

    app._kill_and_edit_last_launch()
    app._kill_and_edit_last_launch()

    assert len(app.pushed_modals) == 1
    assert record.state is LaunchRecordState.RESOLVED_ACTION_PENDING

    app.pushed_callbacks[-1](False)

    assert app.killed == []
    assert app.launched is None
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record

    app._kill_and_edit_last_launch()

    assert len(app.pushed_modals) == 2
    assert latest_live_launch_record(app) is record


def test_single_result_initiation_refusal_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _FakeAgent("running-agent", status="RUNNING", pid=111)
    app = _SingleResultApp(agent, kill_result=False)
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("running-agent")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [agent],
    )

    app._kill_and_edit_last_launch()
    app.pushed_callbacks[-1](True)

    assert app.killed == [agent]
    assert app.launched is None
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record


def test_single_result_prompt_resolution_failure_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _FakeAgent("running-agent", status="RUNNING", pid=111)
    app = _SingleResultApp(agent)
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("running-agent")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [agent],
    )

    def fail_prompt_resolution(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("prompt disk read failed")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._entry_relaunch."
        "prepare_kill_edit_agent_prompt",
        fail_prompt_resolution,
    )

    app._kill_and_edit_last_launch()

    assert app.pushed_modals == []
    assert app.killed == []
    assert app.launched is None
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record
    assert app.notifications == [
        (
            "Unable to prepare agent relaunch prompt: prompt disk read failed",
            "error",
        )
    ]


class _DeferredPromptApp(_SingleResultApp):
    """Keeps scheduled prompt-resolution workers pending for repeat-key tests."""

    def __init__(self, agent: _FakeAgent) -> None:
        super().__init__(agent)
        self.workers: list[tuple[Any, dict[str, Any]]] = []

    def run_worker(self, worker: Any, **kwargs: Any) -> None:
        self.workers.append((worker, dict(kwargs)))
        worker.close()


def test_repeat_press_while_prompt_resolution_pending_does_not_advance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    newer_agent = _FakeAgent("newer-agent", status="RUNNING", pid=111)
    older_agent = _FakeAgent("older-agent", status="RUNNING", pid=222)
    app = _DeferredPromptApp(newer_agent)
    older = push_launch_record(
        app, proc_ids=("older",), prompt="older", context=_context("older")
    )
    newer = push_launch_record(
        app, proc_ids=("newer",), prompt="newer", context=_context("newer")
    )
    assert older is not None and newer is not None
    stamp_launch_record_results(app, "older", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "newer", (_matchable_result("proj", "2"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [newer_agent] if rec is newer else [older_agent],
    )

    app._kill_and_edit_last_launch()
    app._kill_and_edit_last_launch()

    assert len(app.workers) == 1
    assert newer.state is LaunchRecordState.RESOLVED_ACTION_PENDING
    assert older.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is newer
    assert app.pushed_modals == []
    assert app.killed == []
