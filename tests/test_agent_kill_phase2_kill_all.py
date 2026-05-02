"""Phase 2 (TUI Performance v2) regression tests.

Verifies that ``_kill_and_dismiss_all_agents`` routes through the bulk
path (``_do_bulk_kill_agents``) instead of looping over each killable
agent and calling ``_do_kill_agent`` per row, so kill-all becomes one
optimistic UI transaction with one persistence worker.

See ``sdd/tales/202604/tui_perf_v2.md`` (Phase 2).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.models.agent import Agent, AgentType


def _running_agent(*, cl_name: str, pid: int) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=pid,
        raw_suffix=f"fix_hook-{pid}-251230_151429",
    )


def _done_agent(*, cl_name: str, suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
        agent_name=cl_name,
        raw_suffix=suffix,
    )


class _MockApp(AgentsMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self._agents_with_children = list(agents)
        self.current_idx = 0
        self.current_tab = "agents"
        self._kill_persistence_inflight: set[Any] = set()
        self._agent_status_overrides: dict[Any, Any] = {}
        self._agent_pre_question_status: dict[Any, Any] = {}
        self._dismissed_agents: set[Any] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._marked_agents: set[Any] = set()
        self._notifications: list[tuple[str, str]] = []
        self._scheduled: list[tuple[object, tuple[object, ...]]] = []
        self._pushed: list[tuple[Any, Any]] = []
        self.refresh_calls: list[tuple[bool, bool]] = []
        self.bulk_kill_calls: list[tuple[list[Agent], list[Agent] | None]] = []
        self.single_kill_calls: list[Agent] = []
        self.dismiss_all_calls: list[list[Agent]] = []

    def notify(self, msg: str, severity: str = "information") -> None:
        self._notifications.append((msg, severity))

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self._pushed.append((screen, callback))

    def call_later(self, callback: object, *args: object) -> None:
        self._scheduled.append((callback, args))

    def _refresh_notification_count(self) -> None:
        return

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        self.refresh_calls.append((list_changed, defer_detail))

    def _schedule_agents_async_refresh(self) -> None:
        return


class _SpyApp(_MockApp):
    """MockApp that intercepts ``_do_bulk_kill_agents`` / ``_do_kill_agent`` /
    ``_do_dismiss_all`` so we can verify dispatch without running the bulk path.
    """

    def _do_bulk_kill_agents(  # type: ignore[override]
        self, killable: list[Agent], dismissable: list[Agent] | None = None
    ) -> None:
        self.bulk_kill_calls.append(
            (list(killable), list(dismissable) if dismissable else None)
        )

    def _do_kill_agent(self, agent: Agent) -> None:  # type: ignore[override]
        self.single_kill_calls.append(agent)

    def _do_dismiss_all(self, agents: list[Agent]) -> None:  # type: ignore[attr-defined]
        self.dismiss_all_calls.append(list(agents))


def _confirm(app: _MockApp) -> None:
    """Invoke the most-recent pushed modal's callback with ``True``."""
    assert app._pushed, "no modal was pushed"
    _, cb = app._pushed[-1]
    assert cb is not None
    cb(True)


def test_kill_all_uses_bulk_path() -> None:
    """Panel kill-all confirm dispatches one bulk call, not one call per row."""
    run1 = _running_agent(cl_name="r1", pid=111)
    run2 = _running_agent(cl_name="r2", pid=222)
    done1 = _done_agent(cl_name="d1", suffix="20240101120000")
    app = _SpyApp([run1, run2, done1])

    app._kill_and_dismiss_all_agents()
    _confirm(app)

    assert len(app.bulk_kill_calls) == 1
    killable, dismissable = app.bulk_kill_calls[0]
    assert killable == [run1, run2]
    assert dismissable == [done1]
    assert app.single_kill_calls == []
    assert app.dismiss_all_calls == []


def test_kill_all_single_refresh() -> None:
    """The bulk path produces exactly one ``_refresh_agents_display`` call."""
    run1 = _running_agent(cl_name="r1", pid=111)
    run2 = _running_agent(cl_name="r2", pid=222)
    done1 = _done_agent(cl_name="d1", suffix="20240101120000")
    app = _MockApp([run1, run2, done1])

    app._kill_and_dismiss_all_agents()
    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        _confirm(app)

    assert len(app.refresh_calls) == 1
    assert app.refresh_calls[0] == (True, True)


def test_kill_all_only_dismissable() -> None:
    """Empty ``killable`` + non-empty ``dismissable`` still routes through the bulk path."""
    done1 = _done_agent(cl_name="d1", suffix="20240101120000")
    done2 = _done_agent(cl_name="d2", suffix="20240101120001")
    app = _SpyApp([done1, done2])

    app._kill_and_dismiss_all_agents()
    _confirm(app)

    assert len(app.bulk_kill_calls) == 1
    killable, dismissable = app.bulk_kill_calls[0]
    assert killable == []
    assert dismissable == [done1, done2]
    assert app.single_kill_calls == []
    assert app.dismiss_all_calls == []


def test_kill_all_only_dismissable_removes_agents() -> None:
    """End-to-end: dismissable-only kill-all empties ``_agents`` after confirm."""
    done1 = _done_agent(cl_name="d1", suffix="20240101120000")
    done2 = _done_agent(cl_name="d2", suffix="20240101120001")
    app = _MockApp([done1, done2])

    app._kill_and_dismiss_all_agents()
    _confirm(app)

    assert app._agents == []
    assert {done1.identity, done2.identity}.issubset(app._dismissed_agents)
