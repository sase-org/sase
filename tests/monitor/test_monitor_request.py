"""Tests for monitor-start request identity."""

from __future__ import annotations

from sase.monitor.request import StartMonitorRequest, monitor_request_fingerprint


def _request(**overrides: object) -> StartMonitorRequest:
    values: dict[str, object] = {
        "command": "just check-full",
        "reason": "verify",
        "timeout_seconds": 30.0,
        "cwd": "/tmp/work",
        "project_name": "proj",
        "start_status": "TESTING",
        "stop_status": "TESTED",
        "next_action": "Fix failures.",
    }
    values.update(overrides)
    return StartMonitorRequest(**values)  # type: ignore[arg-type]


def test_fingerprint_changes_when_successor_model_differs() -> None:
    """Otherwise-identical starts with different ``--model`` values are distinct."""
    shared = {"lane": "acme", "label": "just check-full"}
    inherit = monitor_request_fingerprint(_request(), **shared)
    small = monitor_request_fingerprint(_request(next_model="@small"), **shared)
    opus = monitor_request_fingerprint(_request(next_model="opus@high"), **shared)
    blank = monitor_request_fingerprint(_request(next_model=""), **shared)

    assert inherit != small
    assert small != opus
    assert inherit == blank


def test_fingerprint_ignores_execution_argv() -> None:
    shared = {"lane": "acme", "label": "just check-full"}
    plain = monitor_request_fingerprint(_request(), **shared)
    guarded = monitor_request_fingerprint(
        _request(execution_argv=["/usr/bin/python", "bootstrap.py", "--", "just"]),
        **shared,
    )

    assert plain == guarded


def test_fingerprint_is_stable_for_the_same_successor_model() -> None:
    first = monitor_request_fingerprint(
        _request(next_model="@small"), lane="acme", label="just check-full"
    )
    second = monitor_request_fingerprint(
        _request(next_model="@small"), lane="acme", label="just check-full"
    )

    assert first == second
    assert first.startswith("sha256:")
