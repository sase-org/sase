"""Shared result types for axe process lifecycle helpers."""

from dataclasses import dataclass


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
    failed_pids: tuple[int, ...] = ()
    lock_was_held: bool = False
    lock_still_held: bool = False
    error: str | None = None
    blocked_in_tests: bool = False

    @property
    def terminated_anything(self) -> bool:
        return self.orchestrator_signaled or self.lumberjacks_stopped > 0

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
            parts.append(f"{self.lumberjacks_stopped} routine process(es)")
        if parts:
            return "Stopped " + " + ".join(parts)
        if self.lock_was_held and self.lock_still_held:
            return (
                "Axe lifecycle lock is still held, but no live PID could be "
                "resolved; run `sase scheduler restart`, and if the lock remains "
                "stuck, stop the process holding it."
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
