"""End-to-end shaped ``,X`` regressions for durable proc-id re-keying."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agent_workflow._launch_procs import _LaunchProcOutcome
from sase.ace.tui.actions.agent_workflow._launch_records import (
    LaunchRecordState,
    push_launch_record,
    rename_launch_record_proc_id,
    stamp_launch_record_results,
)
from tests.ace.tui._kill_and_edit_last_launch_helpers import (
    _FakeAgent,
    _context,
    _matchable_result,
)
from tests.ace.tui.test_kill_and_edit_inflight import (
    _DeferredKillApp,
    _completion,
    _running_row,
)
from tests.ace.tui.test_kill_and_edit_last_launch_dispatch import _DispatchApp


def test_durable_rekey_makes_resolved_launch_immediately_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _DispatchApp()
    placeholder = "pending-abc-uuid"
    durable = "durable-1"
    record = push_launch_record(
        app,
        proc_ids=(placeholder,),
        prompt="p",
        context=_context("demo"),
        submitted_prompts={placeholder: "p"},
    )
    assert record is not None
    rename_launch_record_proc_id(app, placeholder, durable)
    stamp_launch_record_results(app, durable, (_matchable_result("proj", "1"),))
    agent = _FakeAgent("solo")
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, agents: [agent],
    )

    app._kill_and_edit_last_launch()

    assert app.single_targets == [agent]
    assert app.edit_calls == []
    assert not any(
        "when its launch finishes" in message for message, _ in app.notifications
    )


def test_pending_placeholder_kill_survives_durable_proc_id_rekey() -> None:
    app = _DeferredKillApp()
    placeholder = "pending-abc-uuid"
    durable = "durable-1"
    record = push_launch_record(
        app,
        proc_ids=(placeholder,),
        prompt="do work",
        context=_context("demo"),
    )
    assert record is not None
    agent = _running_row("solo", "20260903170000")
    app._agents_with_children = [agent]

    app._kill_and_edit_last_launch()
    timeout = next(
        timer for timer in app.timers if timer.name == "pending-launch-kill-timeout"
    )
    assert record.state is LaunchRecordState.KILL_PENDING
    assert (placeholder,) in app._pending_launch_kill_timers

    rename_launch_record_proc_id(app, placeholder, durable)
    assert record.proc_ids == (durable,)
    assert (placeholder,) not in app._pending_launch_kill_timers
    assert app._pending_launch_kill_timers[(durable,)] is timeout

    result = _matchable_result("proj", "20260903170000")
    app._on_launch_proc_complete(
        _completion(
            durable,
            _LaunchProcOutcome("Started 1 agent", results=(result,)),
        )
    )

    assert app.killed == [agent]
    assert record.state is LaunchRecordState.CONSUMED
    assert timeout.stopped is True
    assert app._pending_launch_kill_timers == {}
    timeout.callback()
    assert app.killed == [agent]
