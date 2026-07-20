"""Shared result types for axe process lifecycle helpers."""

from dataclasses import dataclass
from typing import Literal


StartStatus = Literal[
    "started",
    "already_running",
    "failed",
    "blocked",
    "blocked_in_tests",
]


@dataclass(frozen=True)
class AxeStartAttempt:
    """One start-and-verification attempt within an axe restart."""

    number: int
    status: StartStatus
    pid: int | None = None
    message: str = ""
    verified: bool = False
    verification_error: str | None = None


@dataclass(frozen=True)
class AxeStartResult:
    """Result of an axe daemon start request."""

    status: StartStatus
    pid: int | None = None
    message: str = ""
    attempts: tuple[AxeStartAttempt, ...] = ()
    verified: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status in {"started", "already_running"} and self.pid is not None


@dataclass(frozen=True)
class AxeOrchestratorProbe:
    """Authoritative view of axe orchestrator liveness."""

    lock_held: bool
    lock_holder_pid: int | None
    orchestrator_pid_file_pid: int | None
    legacy_pid: int | None
    running_pid: int | None

    @property
    def running(self) -> bool:
        return self.lock_held or self.running_pid is not None


@dataclass(frozen=True)
class AxeStopResult:
    """Result of an axe daemon stop request."""

    orchestrator_pid: int | None = None
    orchestrator_signaled: bool = False
    orchestrator_stopped: bool = False
    lumberjack_pids: tuple[int, ...] = ()
    lumberjacks_stopped: int = 0
    force_killed_processes: int = 0
    failed_pids: tuple[int, ...] = ()
    lock_was_held: bool = False
    lock_still_held: bool = False
    force: bool = False
    error: str | None = None
    blocked_in_tests: bool = False

    @property
    def terminated_anything(self) -> bool:
        return (
            self.orchestrator_signaled
            or self.lumberjacks_stopped > 0
            or self.force_killed_processes > 0
        )

    @property
    def succeeded(self) -> bool:
        return self.terminated_anything and not self.failed_pids

    def summary(self) -> str:
        """Return a concise user-facing summary."""
        if self.error and not self.terminated_anything:
            return self.error
        parts: list[str] = []
        if self.orchestrator_signaled:
            if self.orchestrator_stopped:
                parts.append("orchestrator")
            else:
                parts.append("orchestrator signaled")
        if self.lumberjacks_stopped:
            parts.append(f"{self.lumberjacks_stopped} lumberjack(s)")
        if self.force_killed_processes:
            parts.append(f"{self.force_killed_processes} matched axe process(es)")
        if parts:
            return "Stopped " + " + ".join(parts)
        if self.lock_was_held and self.lock_still_held:
            return (
                "Axe lifecycle lock is still held, but no live PID could be "
                "resolved; retry with `sase axe stop --force`."
            )
        return "Axe orchestrator is not running."


@dataclass(frozen=True)
class TerminateResult:
    pid: int | None = None
    signaled: bool = False
    stopped: bool = False
    failed: bool = False


@dataclass(frozen=True)
class SweepResult:
    seen: tuple[tuple[str, int], ...] = ()
    stopped_pids: tuple[int, ...] = ()
    failed_pids: tuple[int, ...] = ()
