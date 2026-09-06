"""Multi-result ``,X`` bulk kill-and-edit composition tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
    KillAndEditLastLaunchMixin,
)
from sase.ace.tui.actions.agent_workflow._launch_records import (
    LaunchRecordState,
    latest_live_launch_record,
    push_launch_record,
    stamp_launch_record_results,
)
from sase.ace.tui.actions.agents._marking import AgentMarkingMixin

from tests.ace.tui._kill_and_edit_last_launch_helpers import (
    _FakeAgent,
    _context,
    _matchable_result,
)

# --- resolved multi-result: bulk kill-and-edit composition ------------------


class _BulkSetApp(AgentMarkingMixin, KillAndEditLastLaunchMixin):
    """Exercises ``_kill_and_edit_last_launch_set`` with the real bulk modal."""

    def __init__(self, agents: list[_FakeAgent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._marked_agents: set[Any] = set()
        self._marked_agent_order: list[Any] = []
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.bulk_kill_calls: list[tuple[list[Any], list[Any]]] = []
        self.edit_calls: list[dict[str, Any]] = []
        self.bulk_kill_result = True

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _do_bulk_kill_agents(
        self,
        killable: list[Any],
        dismissable: list[Any] | None = None,
        *,
        on_settled: Callable[[], None] | None = None,
    ) -> bool:
        dismissable = dismissable or []
        self.bulk_kill_calls.append((list(killable), list(dismissable)))
        if not self.bulk_kill_result:
            return False
        ids = {a.identity for a in killable} | {a.identity for a in dismissable}
        self._agents = [a for a in self._agents if a.identity not in ids]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in ids
        ]
        if on_settled is not None:
            on_settled()
        return True

    def _edit_and_relaunch_agents_bulk(
        self,
        prompts: list[str],
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        self.edit_calls.append(
            {
                "prompts": list(prompts),
                "project_file": project_file,
                "cl_name": cl_name,
                "is_project_agent": is_project_agent,
            }
        )


def test_multi_result_set_yields_n_kills_and_n_panes_in_order() -> None:
    running = _FakeAgent(
        "run", raw_prompt="%i:run\nWork run", status="RUNNING", pid=111
    )
    done = _FakeAgent("done", raw_prompt="%id:done\nWork done", status="DONE")
    app = _BulkSetApp([running, done])

    # Launch order is done, then running -- distinct from row order.
    app._kill_and_edit_last_launch_set([done, running])

    assert app.pushed_modals, "Expected the bulk confirmation modal"
    app.pushed_callbacks[-1](True)

    assert len(app.bulk_kill_calls) == 1
    killable, dismissable = app.bulk_kill_calls[0]
    assert [a.name for a in killable] == ["run"]
    assert [a.name for a in dismissable] == ["done"]

    assert len(app.edit_calls) == 1
    assert app.edit_calls[0]["prompts"] == [
        "%id:!done\nWork done",
        "%id:!run\nWork run",
    ]


def test_resolved_bulk_confirmation_cancel_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = _FakeAgent(
        "run", raw_prompt="%i:run\nWork run", status="RUNNING", pid=111
    )
    done = _FakeAgent("done", raw_prompt="%id:done\nWork done", status="DONE")
    app = _BulkSetApp([running, done])
    record = push_launch_record(
        app, proc_ids=("p1", "p2"), prompt="p", context=_context("bulk")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [done, running],
    )

    app._kill_and_edit_last_launch()
    app._kill_and_edit_last_launch()

    assert len(app.pushed_modals) == 1
    assert record.state is LaunchRecordState.RESOLVED_ACTION_PENDING

    app.pushed_callbacks[-1](False)

    assert app.bulk_kill_calls == []
    assert app.edit_calls == []
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record


def test_resolved_bulk_initiation_refusal_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = _FakeAgent(
        "run", raw_prompt="%i:run\nWork run", status="RUNNING", pid=111
    )
    done = _FakeAgent("done", raw_prompt="%id:done\nWork done", status="DONE")
    app = _BulkSetApp([running, done])
    app.bulk_kill_result = False
    record = push_launch_record(
        app, proc_ids=("p1", "p2"), prompt="p", context=_context("bulk")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [done, running],
    )

    app._kill_and_edit_last_launch()
    app.pushed_callbacks[-1](True)

    assert len(app.bulk_kill_calls) == 1
    assert app.edit_calls == []
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record


def test_resolved_bulk_identity_loss_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = _FakeAgent(
        "run", raw_prompt="%i:run\nWork run", status="RUNNING", pid=111
    )
    done = _FakeAgent("done", raw_prompt="%id:done\nWork done", status="DONE")
    app = _BulkSetApp([running, done])
    record = push_launch_record(
        app, proc_ids=("p1", "p2"), prompt="p", context=_context("bulk")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [done, running],
    )

    def resolve_then_lose_rows(
        _owner: object,
        resolver: Callable[[], list[str | None]],
        on_complete: Callable[[list[str | None]], None],
        **_kwargs: object,
    ) -> None:
        resolved = resolver()
        app._agents = []
        app._agents_with_children = []
        on_complete(resolved)

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "schedule_relaunch_prompt_resolution",
        resolve_then_lose_rows,
    )

    app._kill_and_edit_last_launch()

    assert app.pushed_modals == []
    assert app.bulk_kill_calls == []
    assert app.edit_calls == []
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record
    assert app.notifications == [
        ("A launched agent is no longer available; nothing killed", "warning")
    ]
