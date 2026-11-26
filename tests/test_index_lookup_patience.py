"""Bounded, opt-in retries for busy index lookup results."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from sase.core import agent_artifact_lookup, dismissed_bundle_lookup
from sase.core.index_lookup_patience import (
    LookupPatience,
    LookupRetryEvent,
    _get_process_lookup_patience,
    process_lookup_patience,
    retry_while_busy,
    set_process_lookup_patience,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _busy(*, complete: bool = False, availability: str = "busy") -> object:
    return SimpleNamespace(
        availability=availability,
        complete=complete,
        diagnostic="database is locked",
    )


def _is_busy(result: object) -> bool:
    return result.availability == "busy" and not result.complete


def _diagnostic(result: object) -> str | None:
    return result.diagnostic


def test_retry_without_policy_calls_attempt_exactly_once() -> None:
    calls: list[int] = []
    set_process_lookup_patience(None)

    result = retry_while_busy(
        lambda: calls.append(1) or _busy(),
        is_busy=_is_busy,
        diagnostic=_diagnostic,
        lookup="test index",
        sleep=lambda _seconds: pytest.fail("unexpected sleep"),
        monotonic=lambda: pytest.fail("unexpected clock read"),
    )

    assert result.availability == "busy"
    assert calls == [1]


def test_retry_busy_then_ready_uses_injected_clock() -> None:
    clock = _Clock()
    results = [
        _busy(),
        SimpleNamespace(availability="ready", complete=True, diagnostic=None),
    ]
    events: list[LookupRetryEvent] = []

    with process_lookup_patience(LookupPatience(2, on_retry=events.append)):
        result = retry_while_busy(
            lambda: results.pop(0),
            is_busy=_is_busy,
            diagnostic=_diagnostic,
            lookup="test index",
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

    assert result.availability == "ready"
    assert clock.sleeps == [0.25]
    assert [event.recovered for event in events] == [False, True]
    assert events[-1].seconds_waited == 0.25


def test_retry_busy_through_deadline_returns_last_result_and_caps_backoff() -> None:
    clock = _Clock()
    events: list[LookupRetryEvent] = []
    calls = 0

    def attempt() -> object:
        nonlocal calls
        calls += 1
        return _busy()

    with process_lookup_patience(
        LookupPatience(
            2, initial_delay_seconds=0.25, max_delay_seconds=1, on_retry=events.append
        )
    ):
        result = retry_while_busy(
            attempt,
            is_busy=_is_busy,
            diagnostic=_diagnostic,
            lookup="test index",
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

    assert result.availability == "busy"
    assert calls == 5
    assert clock.sleeps == [0.25, 0.5, 1, 0.25]
    assert sum(clock.sleeps) == 2
    assert events[-1].gave_up
    assert events[-1].seconds_waited == 2
    assert events[-1].last_diagnostic == "database is locked"


@pytest.mark.parametrize(
    "result",
    [
        _busy(complete=True),
        _busy(availability="corrupt"),
        _busy(availability="missing"),
    ],
)
def test_complete_busy_and_non_busy_availability_are_not_retried(
    result: object,
) -> None:
    calls = 0

    def attempt() -> object:
        nonlocal calls
        calls += 1
        return result

    with process_lookup_patience(LookupPatience(10)):
        assert (
            retry_while_busy(
                attempt,
                is_busy=_is_busy,
                diagnostic=_diagnostic,
                lookup="test index",
                sleep=lambda _seconds: pytest.fail("unexpected sleep"),
                monotonic=lambda: 0.0,
            )
            is result
        )
    assert calls == 1


def test_retry_callback_exceptions_are_ignored() -> None:
    clock = _Clock()
    results = [
        _busy(),
        SimpleNamespace(availability="ready", complete=True, diagnostic=None),
    ]

    def fail(_event: LookupRetryEvent) -> None:
        raise RuntimeError("logging failed")

    with process_lookup_patience(LookupPatience(1, on_retry=fail)):
        result = retry_while_busy(
            lambda: results.pop(0),
            is_busy=_is_busy,
            diagnostic=_diagnostic,
            lookup="test index",
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

    assert result.availability == "ready"


def test_policy_context_restores_the_previous_process_value() -> None:
    previous = LookupPatience(5)
    temporary = LookupPatience(2)
    set_process_lookup_patience(previous)

    with process_lookup_patience(temporary):
        assert _get_process_lookup_patience() is temporary

    assert _get_process_lookup_patience() is previous
    set_process_lookup_patience(None)


def _fake_wire_result(availability: str, complete: bool) -> dict[str, Any]:
    return {
        "availability": availability,
        "complete": complete,
        "source": "fallback",
        "diagnostic": "database is locked" if availability == "busy" else None,
    }


def test_artifact_facade_retries_and_releases_its_lock_before_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    raw_results = [_fake_wire_result("busy", False), _fake_wire_result("ready", True)]
    lock_held = False

    @contextmanager
    def fake_lock(_timeout: float):
        nonlocal lock_held
        lock_held = True
        try:
            yield True
        finally:
            lock_held = False

    def fake_sleep(seconds: float) -> None:
        assert not lock_held, "process-local index lock held across backoff"
        clock.sleep(seconds)

    def fake_retry(attempt: Any, **kwargs: Any) -> Any:
        return retry_while_busy(
            attempt,
            **kwargs,
            sleep=fake_sleep,
            monotonic=clock.monotonic,
        )

    monkeypatch.setattr(
        agent_artifact_lookup, "try_agent_artifact_index_operation_lock", fake_lock
    )
    monkeypatch.setattr(agent_artifact_lookup, "retry_while_busy", fake_retry)
    monkeypatch.setattr(
        agent_artifact_lookup,
        "require_rust_binding",
        lambda _name: lambda *_args: raw_results.pop(0),
    )

    from sase.core.agent_artifact_lookup_wire import (
        AgentArtifactLookupQueryWire,
        AgentArtifactLookupTargetWire,
    )

    with process_lookup_patience(LookupPatience(1)):
        result = agent_artifact_lookup.lookup_agent_artifacts(
            "/index",
            "/projects",
            AgentArtifactLookupQueryWire(
                target=AgentArtifactLookupTargetWire(kind="names", names=("alice",))
            ),
        )

    assert result.availability == "ready"
    assert clock.sleeps == [0.25]
    assert not lock_held


def test_dismissed_bundle_facade_retries_only_under_patience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def lookup(*_args: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return (
            _fake_wire_result("busy", False)
            if calls == 1
            else _fake_wire_result("ready", True)
        )

    monkeypatch.setattr(
        dismissed_bundle_lookup,
        "require_rust_binding",
        lambda _name: lookup,
    )
    with process_lookup_patience(None):
        first = dismissed_bundle_lookup.lookup_named_dismissed_bundle("/bundles", "a")
    assert first.availability == "busy"
    assert calls == 1

    clock = _Clock()
    real_retry = retry_while_busy

    def fake_retry(attempt: Any, **kwargs: Any) -> Any:
        return real_retry(
            attempt,
            **kwargs,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

    monkeypatch.setattr(dismissed_bundle_lookup, "retry_while_busy", fake_retry)
    calls = 0
    with process_lookup_patience(LookupPatience(1)):
        second = dismissed_bundle_lookup.lookup_named_dismissed_bundle("/bundles", "a")
    assert second.availability == "ready"
    assert calls == 2
    assert clock.sleeps == [0.25]
