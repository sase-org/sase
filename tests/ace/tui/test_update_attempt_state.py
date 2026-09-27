"""Revisioned view handling in ``UpdateAttemptStateMixin``."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace._update_attempts_model import UpdateAttemptsView, UpdateFailure
from sase.ace.tui.actions._update_attempt_state import UpdateAttemptStateMixin
from sase.ace.tui.modals import UpdateFailureModal


def _failure(attempt_id: str = "a1") -> UpdateFailure:
    return UpdateFailure(
        attempt_id=attempt_id,
        label="sase update",
        proc_type="comprehensive-update",
        stage="apply",
        started_at=1700000000.0,
        finished_at=1700000010.0,
        error="boom",
        output_tail="tail",
        interrupted=False,
    )


class _FakeIndicator:
    def __init__(self) -> None:
        self.failures: list[Any] = []

    def set_last_failure(self, failure: Any) -> None:
        self.failures.append(failure)


class _StateHost(UpdateAttemptStateMixin):
    def __init__(self) -> None:
        self._update_attempts_view: Any = None
        self._update_attempts_refresh_in_flight = False
        self.workers: list[Any] = []
        self.pushed: list[Any] = []
        self.indicator = _FakeIndicator()
        self.shortcut_calls = 0

    def run_worker(
        self,
        fn: Any,
        *,
        thread: bool = False,
        exclusive: bool = False,
        group: Any = None,
    ) -> Any:
        worker = SimpleNamespace(_fn=fn)
        self.workers.append(worker)
        return worker

    def call_from_thread(self, fn: Any, *args: Any) -> Any:
        return fn(*args)

    def query_one(self, selector: Any, type_: Any) -> Any:
        return self.indicator

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self.pushed.append((screen, callback))

    def action_update_sase_shortcut(self) -> None:
        self.shortcut_calls += 1


def test_apply_drops_stale_revision() -> None:
    host = _StateHost()
    newer = UpdateAttemptsView(revision=2, failure=_failure())
    stale = UpdateAttemptsView(revision=1, failure=None)

    host._apply_update_attempts_view(newer)
    host._apply_update_attempts_view(stale)

    assert host._update_attempts_view == newer
    assert host.indicator.failures == [newer.failure]


def test_apply_accepts_same_revision_for_optimistic_dismiss() -> None:
    host = _StateHost()
    host._apply_update_attempts_view(UpdateAttemptsView(revision=2, failure=_failure()))
    host._apply_update_attempts_view(UpdateAttemptsView(revision=2, failure=None))

    assert host._update_attempts_view == UpdateAttemptsView(revision=2, failure=None)
    assert host.indicator.failures == [_failure(), None]


def test_refresh_coalesces_and_applies_view(
    monkeypatch: Any,
) -> None:
    import sase.ace.tui.actions._update_attempt_state as state

    sentinel = UpdateAttemptsView(revision=7, failure=_failure())
    monkeypatch.setattr(state, "load_update_attempts", lambda: sentinel)
    host = _StateHost()

    host._schedule_update_attempts_refresh()
    host._schedule_update_attempts_refresh()

    assert len(host.workers) == 1
    assert host._update_attempts_refresh_in_flight is True
    host.workers[0]._fn()

    assert host._update_attempts_refresh_in_flight is False
    assert host._update_attempts_view == sentinel
    assert host.indicator.failures == [sentinel.failure]


def test_dismiss_is_optimistic_then_persisted(monkeypatch: Any) -> None:
    import sase.ace.tui.actions._update_attempt_state as state

    persisted = UpdateAttemptsView(revision=6, failure=None)
    seen: list[str] = []
    monkeypatch.setattr(
        state,
        "dismiss_update_failure",
        lambda attempt_id: seen.append(attempt_id) or persisted,
    )
    host = _StateHost()
    host._apply_update_attempts_view(UpdateAttemptsView(revision=5, failure=_failure()))

    host._dismiss_update_failure("a1")

    assert host._update_attempts_view == UpdateAttemptsView(revision=5, failure=None)
    assert len(host.workers) == 1
    host.workers[0]._fn()

    assert seen == ["a1"]
    assert host._update_attempts_view == persisted


def test_open_failure_without_failure_pushes_nothing() -> None:
    host = _StateHost()

    host.action_open_update_failure()

    assert host.pushed == []


def test_open_failure_result_routes_dismiss_and_open_update() -> None:
    host = _StateHost()
    host._apply_update_attempts_view(UpdateAttemptsView(revision=5, failure=_failure()))
    dismissed: list[str] = []
    host._dismiss_update_failure = dismissed.append  # type: ignore[method-assign]

    host.action_open_update_failure()

    assert len(host.pushed) == 1
    screen, callback = host.pushed[0]
    assert isinstance(screen, UpdateFailureModal)
    assert screen.failure == _failure()

    callback("dismiss")
    assert dismissed == ["a1"]

    callback("open_update")
    assert host.shortcut_calls == 1

    callback(None)
    assert dismissed == ["a1"]
    assert host.shortcut_calls == 1
