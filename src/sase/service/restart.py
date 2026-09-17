"""Typed facade for Rust-owned service restart decisions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class ServiceExit:
    """Observed service proc exit information."""

    exit_code: int | None = None
    signal: int | None = None
    spawn_error: str | None = None
    stop_requested: bool = False

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"stop_requested": self.stop_requested}
        if self.exit_code is not None:
            payload["exit_code"] = self.exit_code
        if self.signal is not None:
            payload["signal"] = self.signal
        if self.spawn_error is not None:
            payload["spawn_error"] = self.spawn_error
        return payload


@dataclass(frozen=True)
class ServiceRestartTuning:
    """Backoff and crash-loop thresholds for one restart decision."""

    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    healthy_run_seconds: float = 300.0
    crash_loop_window_seconds: float = 60.0
    crash_loop_threshold: int = 3

    def to_wire(self) -> dict[str, Any]:
        return {
            "initial_backoff_seconds": self.initial_backoff_seconds,
            "max_backoff_seconds": self.max_backoff_seconds,
            "healthy_run_seconds": self.healthy_run_seconds,
            "crash_loop_window_seconds": self.crash_loop_window_seconds,
            "crash_loop_threshold": self.crash_loop_threshold,
        }


@dataclass(frozen=True)
class ServiceRestartHistory:
    """Per-service restart history that Rust advances after each exit."""

    started_at: float | None = None
    backoff_seconds: float = 0.0
    consecutive_failures: int = 0
    recent_failures: tuple[float, ...] = ()
    alert_sent: bool = False

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ServiceRestartHistory:
        return cls(
            started_at=payload.get("started_at"),
            backoff_seconds=float(payload.get("backoff_seconds", 0.0)),
            consecutive_failures=int(payload.get("consecutive_failures", 0)),
            recent_failures=tuple(
                float(item) for item in payload.get("recent_failures", ())
            ),
            alert_sent=bool(payload.get("alert_sent", False)),
        )

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "backoff_seconds": self.backoff_seconds,
            "consecutive_failures": self.consecutive_failures,
            "recent_failures": list(self.recent_failures),
            "alert_sent": self.alert_sent,
        }
        if self.started_at is not None:
            payload["started_at"] = self.started_at
        return payload


@dataclass(frozen=True)
class ServiceRestartDecision:
    """Rust restart decision plus the advanced restart history."""

    schema_version: int
    action: str
    clean_exit: bool
    delay_seconds: float
    restart_at: float | None
    reason: str
    crash_loop: bool
    notify: bool
    history: ServiceRestartHistory

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ServiceRestartDecision:
        return cls(
            schema_version=int(payload["schema_version"]),
            action=str(payload["action"]),
            clean_exit=bool(payload["clean_exit"]),
            delay_seconds=float(payload["delay_seconds"]),
            restart_at=(
                None
                if payload.get("restart_at") is None
                else float(payload["restart_at"])
            ),
            reason=str(payload["reason"]),
            crash_loop=bool(payload["crash_loop"]),
            notify=bool(payload["notify"]),
            history=ServiceRestartHistory.from_wire(payload["history"]),
        )


def decide_service_restart(
    policy: str,
    exit: ServiceExit,
    history: ServiceRestartHistory,
    *,
    now: float,
    success_exit_codes: Sequence[int] = (),
    tuning: ServiceRestartTuning | None = None,
) -> ServiceRestartDecision:
    """Ask Rust whether a service proc should restart after an exit."""
    binding = require_rust_binding("service_restart_decide")
    payload = binding(
        {
            "policy": policy,
            "success_exit_codes": [int(item) for item in success_exit_codes],
            "exit": exit.to_wire(),
            "history": history.to_wire(),
            "now": now,
            "tuning": (tuning or ServiceRestartTuning()).to_wire(),
        }
    )
    return ServiceRestartDecision.from_wire(payload)


__all__ = [
    "ServiceExit",
    "ServiceRestartDecision",
    "ServiceRestartHistory",
    "ServiceRestartTuning",
    "decide_service_restart",
]
