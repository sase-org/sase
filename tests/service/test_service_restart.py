"""Contract tests for the Rust-backed service restart facade."""

from __future__ import annotations

import pytest

from sase.service.restart import (
    ServiceExit,
    ServiceRestartHistory,
    decide_service_restart,
)


def test_restart_decision_advances_orchestrator_backoff_history() -> None:
    decision = decide_service_restart(
        "always",
        ServiceExit(exit_code=1),
        ServiceRestartHistory(started_at=0.0),
        now=1.0,
    )

    assert decision.action == "restart"
    assert decision.delay_seconds == 1.0
    assert decision.restart_at == 2.0
    assert decision.reason == "exited with code 1; retrying in 1s"
    assert decision.history.consecutive_failures == 1
    assert decision.history.recent_failures == (1.0,)

    next_decision = decide_service_restart(
        "always",
        ServiceExit(exit_code=1),
        ServiceRestartHistory(
            started_at=1.0,
            backoff_seconds=decision.history.backoff_seconds,
            consecutive_failures=decision.history.consecutive_failures,
            recent_failures=decision.history.recent_failures,
            alert_sent=decision.history.alert_sent,
        ),
        now=2.0,
    )
    assert next_decision.delay_seconds == 2.0


def test_on_failure_clean_exit_gives_up() -> None:
    decision = decide_service_restart(
        "on-failure",
        ServiceExit(exit_code=75),
        ServiceRestartHistory(started_at=10.0),
        now=11.0,
        success_exit_codes=(75,),
    )

    assert decision.action == "give_up"
    assert decision.clean_exit is True
    assert (
        decision.reason
        == "exited with code 75; clean exit, not restarting (restart: on-failure)"
    )
    assert decision.history.started_at is None


def test_invalid_restart_request_surfaces_value_error() -> None:
    with pytest.raises(ValueError):
        decide_service_restart(
            "always",
            ServiceExit(exit_code=1),
            ServiceRestartHistory(),
            now=float("nan"),
        )
