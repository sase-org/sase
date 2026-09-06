"""Dispatcher state-machine tests for ``,X`` kill-and-edit-last-launch."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
    KillAndEditLastLaunchMixin,
    _launch_result_key,
)
from sase.ace.tui.actions.agent_workflow._launch_records import (
    push_launch_record,
    stamp_launch_record_results,
)
from sase.ace.tui.actions.agent_workflow._types import (
    PromptContext,
    RelaunchOperation,
    begin_prompt_session,
)

from tests.ace.tui._kill_and_edit_last_launch_helpers import (
    _FakeAgent,
    _context,
    _matchable_result,
)

# --- dispatch state machine -------------------------------------------------


class _DispatchApp(KillAndEditLastLaunchMixin):
    """Records which delegate the dispatcher chose, without exercising it."""

    def __init__(self) -> None:
        self._agents_with_children: list[_FakeAgent] = []
        self.notifications: list[tuple[str, str | None]] = []
        self.single_targets: list[_FakeAgent] = []
        self.set_targets: list[list[_FakeAgent]] = []
        self.revealed: list[Any] = []
        self.edit_calls: list[tuple[str, str, str, bool]] = []
        self.bulk_edit_calls: list[dict[str, Any]] = []
        self.timers: list[Any] = []
        self._prompt_bar: Any | None = None
        self._prompt_context: PromptContext | None = None

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _reveal_last_launch_target(self, target_identity: Any) -> None:
        self.revealed.append(target_identity)

    def _kill_and_edit_agent(
        self,
        target: _FakeAgent | None = None,
        *,
        on_initiated: Callable[[bool], None] | None = None,
        **_kwargs: object,
    ) -> None:
        assert target is not None
        self.single_targets.append(target)
        if on_initiated is not None:
            on_initiated(True)

    def _kill_and_edit_last_launch_set(
        self,
        agents: list[_FakeAgent],
        *,
        on_initiated: Callable[[bool], None] | None = None,
        **_kwargs: object,
    ) -> None:
        self.set_targets.append(agents)
        if on_initiated is not None:
            on_initiated(True)

    def _edit_and_relaunch_agent(
        self,
        raw_prompt: str,
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
        **_kwargs: object,
    ) -> None:
        self.edit_calls.append((raw_prompt, project_file, cl_name, is_project_agent))

    def _edit_and_relaunch_agents_bulk(
        self,
        raw_prompts: list[str],
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
        **_kwargs: object,
    ) -> None:
        self.bulk_edit_calls.append(
            {
                "prompts": list(raw_prompts),
                "project_file": project_file,
                "cl_name": cl_name,
                "is_project_agent": is_project_agent,
            }
        )

    def _mounted_prompt_bar(self) -> Any | None:
        return self._prompt_bar

    def set_timer(
        self, delay: float, callback: Callable[[], None], name: str = ""
    ) -> Any:
        timer = SimpleNamespace(
            stop=lambda: None, callback=callback, delay=delay, name=name
        )
        self.timers.append(timer)
        return timer


def test_no_live_record_notifies_and_does_nothing() -> None:
    app = _DispatchApp()

    app._kill_and_edit_last_launch()

    assert app.notifications == [("No recent launch to kill and edit", "warning")]
    assert app.single_targets == []
    assert app.set_targets == []


def test_in_flight_record_restores_prompt_and_marks_kill_pending() -> None:
    app = _DispatchApp()
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="do the thing", context=_context("demo")
    )
    assert record is not None

    app._kill_and_edit_last_launch()

    assert app.edit_calls == [
        ("do the thing", record.context.project_file, record.context.cl_name, True)
    ]
    assert app.single_targets == []
    assert app.set_targets == []
    assert app.notifications == [('Will kill "demo" when its launch finishes', None)]
    from sase.ace.tui.actions.agent_workflow._launch_records import (
        LaunchRecordState,
    )

    assert record.state is LaunchRecordState.KILL_PENDING
    assert len(app.timers) == 1
    assert app.timers[0].name == "pending-launch-kill-timeout"


def test_kill_pending_repeat_refocuses_and_does_not_advance() -> None:
    app = _DispatchApp()
    older = push_launch_record(
        app, proc_ids=("older",), prompt="older", context=_context("older")
    )
    newer = push_launch_record(
        app, proc_ids=("newer",), prompt="newer", context=_context("newer")
    )
    assert older is not None and newer is not None
    bar = SimpleNamespace(focus_count=0)

    def focus() -> None:
        bar.focus_count += 1

    bar.focus = focus
    app._prompt_bar = bar

    app._kill_and_edit_last_launch()
    assert newer.state.value == "kill_pending"
    assert app.edit_calls == [
        ("newer", newer.context.project_file, newer.context.cl_name, True)
    ]
    begin_prompt_session(
        app,
        _prompt_context_for_record(newer),
        relaunch_operation=newer.relaunch_operation,
    )

    app._kill_and_edit_last_launch()

    assert bar.focus_count == 1
    assert app.edit_calls == [
        ("newer", newer.context.project_file, newer.context.cl_name, True)
    ]
    assert app.single_targets == []
    assert len(app.timers) == 1
    from sase.ace.tui.actions.agent_workflow._launch_records import (
        LaunchRecordState,
        latest_live_launch_record,
    )

    assert newer.state is LaunchRecordState.KILL_PENDING
    assert older.state is LaunchRecordState.IN_FLIGHT
    assert latest_live_launch_record(app) is newer


def test_kill_pending_repeat_remounts_when_an_unrelated_prompt_is_mounted() -> None:
    app = _DispatchApp()
    record = push_launch_record(
        app, proc_ids=("newer",), prompt="newer", context=_context("newer")
    )
    assert record is not None
    bar = SimpleNamespace(focus_count=0)

    def focus() -> None:
        bar.focus_count += 1

    bar.focus = focus
    app._prompt_bar = bar

    app._kill_and_edit_last_launch()
    assert app.edit_calls == [
        ("newer", record.context.project_file, record.context.cl_name, True)
    ]

    begin_prompt_session(
        app,
        _prompt_context_for_record(record),
        relaunch_operation=RelaunchOperation("unrelated prompt"),
    )
    app._kill_and_edit_last_launch()

    assert bar.focus_count == 0
    assert app.edit_calls == [
        ("newer", record.context.project_file, record.context.cl_name, True),
        ("newer", record.context.project_file, record.context.cl_name, True),
    ]


def _prompt_context_for_record(record: Any) -> PromptContext:
    return PromptContext(
        project_name="home",
        cl_name=None,
        project_file=record.context.project_file,
        workspace_dir="/tmp",
        workspace_num=0,
        workflow_name="ace(run)-test",
        timestamp="test",
        history_sort_key=record.context.cl_name,
        display_name=record.context.display_name,
        update_target="",
        is_home_mode=True,
    )


def test_inflight_bulk_record_mounts_per_unit_prompts() -> None:
    app = _DispatchApp()
    record = push_launch_record(
        app,
        proc_ids=("p1", "p2"),
        prompt="shared",
        context=_context("bulk 2 Patches"),
        submitted_prompts={"p1": "#gh:alpha shared", "p2": "#gh:beta shared"},
    )
    assert record is not None

    app._kill_and_edit_last_launch()

    assert app.edit_calls == []
    assert app.bulk_edit_calls == [
        {
            "prompts": ["#gh:alpha shared", "#gh:beta shared"],
            "project_file": record.context.project_file,
            "cl_name": record.context.cl_name,
            "is_project_agent": True,
        }
    ]


def test_inflight_handler_does_no_synchronous_disk_or_proc_store_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _DispatchApp()
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("demo")
    )
    assert record is not None

    def fail_disk(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("in-flight ,X must not touch disk or the proc store")

    monkeypatch.setattr("os.stat", fail_disk)
    monkeypatch.setattr("os.listdir", fail_disk)
    monkeypatch.setattr("pathlib.Path.exists", fail_disk)
    monkeypatch.setattr("pathlib.Path.is_dir", fail_disk)
    monkeypatch.setattr("pathlib.Path.read_text", fail_disk)

    app._kill_and_edit_last_launch()

    assert record.state.value == "kill_pending"
    assert app.edit_calls


def test_resolved_single_match_reveals_and_delegates_to_kill_and_edit_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _DispatchApp()
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("demo")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))

    agent = _FakeAgent("solo")
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, agents: [agent],
    )

    app._kill_and_edit_last_launch()

    assert app.single_targets == [agent]
    assert app.set_targets == []
    assert app.revealed == [agent.identity]
    from sase.ace.tui.actions.agent_workflow._launch_records import (
        LaunchRecordState,
        latest_live_launch_record,
    )

    assert record.state is LaunchRecordState.CONSUMED
    assert latest_live_launch_record(app) is None


def test_resolved_multi_match_delegates_to_bulk_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _DispatchApp()
    record = push_launch_record(
        app, proc_ids=("p1", "p2"), prompt="p", context=_context("bulk 2 Patches")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))

    agents = [_FakeAgent("alpha"), _FakeAgent("beta")]
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: agents,
    )

    app._kill_and_edit_last_launch()

    assert app.single_targets == []
    assert app.set_targets == [agents]
    assert app.revealed == [agents[0].identity]


def test_unresolved_newest_target_stays_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _DispatchApp()
    stale = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("stale")
    )
    live = push_launch_record(
        app, proc_ids=("p2",), prompt="p", context=_context("live")
    )
    assert stale is not None and live is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))

    calls: list[Any] = []

    def fake_matcher(record: Any, loaded: Any) -> list[_FakeAgent]:
        del loaded
        calls.append(record)
        return []

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        fake_matcher,
    )

    app._kill_and_edit_last_launch()

    assert calls == [live]
    assert app.single_targets == []
    assert app.set_targets == []
    from sase.ace.tui.actions.agent_workflow._launch_records import (
        LaunchRecordState,
        latest_live_launch_record,
    )

    assert stale.state is LaunchRecordState.RESOLVED
    assert live.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is live
    assert any(
        "still has 1 launch target resolving" in message
        for message, _severity in app.notifications
    )


def test_confirmed_handled_target_pops_to_next_live_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _DispatchApp()
    stale = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("stale")
    )
    live = push_launch_record(
        app, proc_ids=("p2",), prompt="p", context=_context("live")
    )
    assert stale is not None and live is not None
    stale_result = _matchable_result("proj", "1")
    live_result = _matchable_result("proj", "2")
    stamp_launch_record_results(app, "p1", (stale_result,))
    stamp_launch_record_results(app, "p2", (live_result,))
    live.handled_result_keys.add(_launch_result_key(live_result))

    agent = _FakeAgent("still-here")
    calls: list[Any] = []

    def fake_matcher(record: Any, loaded: Any) -> list[_FakeAgent]:
        del loaded
        calls.append(record)
        return [agent] if record is stale else []

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        fake_matcher,
    )

    app._kill_and_edit_last_launch()

    assert calls == [stale]
    assert app.single_targets == [agent]
    from sase.ace.tui.actions.agent_workflow._launch_records import LaunchRecordState

    assert stale.state is LaunchRecordState.CONSUMED
    assert live.state is LaunchRecordState.CONSUMED


def test_second_press_after_consumption_targets_next_record_via_fresh_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeat ``,X`` after a record is consumed only reaches an older one.

    Consuming the newest record makes it invisible to
    ``latest_live_launch_record``; a second dispatch call naturally falls
    through to whatever live record remains, exactly as a second keypress
    would after the first one already initiated a kill.
    """
    app = _DispatchApp()
    older = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("older")
    )
    newer = push_launch_record(
        app, proc_ids=("p2",), prompt="p", context=_context("newer")
    )
    assert older is not None and newer is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))

    older_agent = _FakeAgent("older-agent")
    newer_agent = _FakeAgent("newer-agent")
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [newer_agent] if rec is newer else [older_agent],
    )

    app._kill_and_edit_last_launch()
    assert app.single_targets == [newer_agent]

    app._kill_and_edit_last_launch()
    assert app.single_targets == [newer_agent, older_agent]
