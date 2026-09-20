"""ACE recovery actions for a failed gate execution and off-loop refresh."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _notification_gate_recovery as recovery
from sase.ace.tui.actions.agents._notification_gate_execution import _PartialAttempt
from sase.ace.tui.actions.agents._notification_off_loop import run_off_loop
from sase.ace.tui.actions.agents._notification_polling import (
    AgentNotificationPollingMixin,
)
from sase.ace.tui.modals.gate_retry_modal import GateRetryModal
from sase.shells.settlement import touch_agent_refresh_pulse


class _App:
    def __init__(self) -> None:
        self.pushed: list[tuple[Any, Any]] = []
        self.notifications: list[tuple[str, str]] = []
        self.submitted: list[dict[str, Any]] = []
        self.snapshot_refreshes = 0

    def push_screen(self, screen: object, callback: Any = None) -> None:
        self.pushed.append((screen, callback))

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _schedule_notification_snapshot_refresh(self) -> None:
        self.snapshot_refreshes += 1

    def _submit_durable_proc(self, *args: object, **kwargs: Any) -> object:
        self.submitted.append(kwargs)
        return SimpleNamespace(proc_id="p")


def _failure(actions: str) -> Any:
    return SimpleNamespace(
        id="failed-1",
        action_data={
            "bundle_path": "/tmp/bundle",
            "request_id": "req-1",
            "request_kind": "custom",
            "stage": "command",
            "recovery_actions": actions,
        },
    )


@pytest.fixture
def _patched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.notification_gates.failure_notifications."
        "gate_failure_selected_option_ids",
        lambda _bundle, _data: ("approve", "commit"),
    )
    monkeypatch.setattr(
        recovery,
        "describe_partial_attempt",
        lambda _bundle: _PartialAttempt("a1", ("approve",), ("commit",)),
    )


def test_failure_offers_resume_restart_and_cancel(_patched: None) -> None:
    app = _App()

    recovery.handle_gate_execution_failed(app, _failure("resume,restart,cancel"))

    [(modal, callback)] = app.pushed
    assert isinstance(modal, GateRetryModal)
    callback("restart")
    [submitted] = app.submitted
    assert submitted["request"]["retry"] == "restart"
    assert submitted["request"]["option_ids"] == ["approve", "commit"]


def test_post_response_failure_only_offers_resume(_patched: None) -> None:
    app = _App()

    recovery.handle_gate_execution_failed(app, _failure("resume"))

    [(modal, callback)] = app.pushed
    assert modal._allow_restart is False
    assert modal._allow_cancel is False
    callback("resume")
    assert app.submitted[0]["request"]["retry"] == "resume"


def test_cancel_choice_cancels_the_gate_off_the_ui_path(
    _patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancelled: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        "sase.notification_gates.executor_cancellation.cancel_gate",
        lambda bundle, *, reason, source: cancelled.append((bundle, source)),
    )
    app = _App()

    recovery.handle_gate_execution_failed(app, _failure("resume,restart,cancel"))
    app.pushed[0][1]("cancel")

    assert cancelled == [(Path("/tmp/bundle"), "tui")]
    assert app.notifications == [("Gate cancelled", "information")]
    assert app.snapshot_refreshes == 1


async def test_run_off_loop_reads_on_a_thread_and_finishes_on_the_loop() -> None:
    import threading

    loop_thread = threading.get_ident()
    seen: list[tuple[int, int]] = []
    done = asyncio.Event()

    def work() -> int:
        return threading.get_ident()

    def on_done(worker_thread: int) -> None:
        seen.append((worker_thread, threading.get_ident()))
        done.set()

    run_off_loop(_App(), work, on_done, name="test")
    await asyncio.wait_for(done.wait(), 2)

    assert seen[0][0] != loop_thread
    assert seen[0][1] == loop_thread


def test_exact_agent_pulse_lands_inside_the_agent_directory(tmp_path: Path) -> None:
    touch_agent_refresh_pulse(tmp_path)
    touch_agent_refresh_pulse(tmp_path / "missing")

    assert (tmp_path / ".ace_refresh_pulse").exists()
    assert not (tmp_path / "missing").exists()


async def test_count_refresh_resolves_gates_that_disappeared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone = SimpleNamespace(id="gone")
    applied: list[tuple[Any, bool]] = []

    class _Indicator:
        def set_tabs(self, _tabs: object) -> None:
            pass

    class _Host(AgentNotificationPollingMixin):
        _notification_snapshot_cache = SimpleNamespace(notifications=[gone])
        _notification_snapshot_refresh_pending = True

        async def _read_notification_snapshot_guarded(self) -> Any:
            return SimpleNamespace(notifications=[], tabs=())

        def query_one(self, *_args: object) -> _Indicator:
            return _Indicator()

        def _reconcile_unread_from_cached_notifications(self) -> None:
            pass

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_polling."
        "prepare_disappeared_plan_notification_refresh",
        lambda _app, previous, _current: (
            ((Path("/exact"),), False) if previous == [gone] else ((), False)
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_polling."
        "apply_disappeared_plan_notification_refresh",
        lambda _app, dirs, *, needs_broad_fallback: applied.append(
            (dirs, needs_broad_fallback)
        ),
    )

    await _Host()._refresh_notification_count_async()

    assert applied == [((Path("/exact"),), False)]


def test_gate_decision_refresh_routes_exact_dirs_without_broad_fallback() -> None:
    from sase.ace.tui.actions.agents._notification_utils import (
        _request_gate_decision_refresh,
    )

    deltas: list[tuple[list[Path], str]] = []

    class _Host(_App):
        def _schedule_agent_artifact_delta_refresh(
            self, dirs: list[Path], *, source: str
        ) -> None:
            deltas.append((dirs, source))

        def _schedule_agents_refresh(self) -> None:
            raise AssertionError("broad refresh")

    _request_gate_decision_refresh(
        _Host(),
        notification=SimpleNamespace(id="n", action="X", action_data={}),
        allow_broad_fallback=False,
        artifact_dirs=(Path("/planner"), Path("/shell")),
    )

    assert deltas == [([Path("/planner"), Path("/shell")], "notification")]
