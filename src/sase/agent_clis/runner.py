"""Typed, shell-free subprocess boundary for agent-CLI operations."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

COMMAND_TIMEOUT_SECONDS = 300.0
PROBE_TIMEOUT_SECONDS = 5.0

RunFn = Callable[..., subprocess.CompletedProcess[str]]
ClockFn = Callable[[], float]


@dataclass(frozen=True)
class CommandResult:
    """Captured result from one command, including non-zero exits."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    elapsed: float = 0.0

    @property
    def output(self) -> str:
        return "\n".join(part for part in (self.stderr, self.stdout) if part)


class AgentCliRunnerError(Exception):
    """Base class for failures that prevent a command result."""

    def __init__(self, argv: Sequence[str], message: str) -> None:
        self.argv = tuple(argv)
        super().__init__(message)


class _CommandNotFoundError(AgentCliRunnerError):
    """The command's executable could not be started."""

    def __init__(self, argv: Sequence[str]) -> None:
        command = argv[0] if argv else "<empty command>"
        super().__init__(argv, f"command not found: {command}")


class _CommandTimedOutError(AgentCliRunnerError):
    """The command exceeded its timeout."""

    def __init__(self, argv: Sequence[str], timeout: float) -> None:
        self.timeout = timeout
        super().__init__(argv, f"command timed out after {timeout:g}s")


class _CommandExecutionError(AgentCliRunnerError):
    """The OS could not execute the command."""


def run_command(
    argv: Sequence[str],
    *,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
    run_fn: RunFn = subprocess.run,
    clock: ClockFn = time.monotonic,
) -> CommandResult:
    """Run *argv* without a shell and capture success or non-zero output."""
    args = tuple(str(item) for item in argv)
    start = clock()
    try:
        completed = run_fn(
            list(args),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise _CommandNotFoundError(args) from exc
    except subprocess.TimeoutExpired as exc:
        raise _CommandTimedOutError(args, timeout) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise _CommandExecutionError(args, f"{type(exc).__name__}: {exc}") from exc
    return CommandResult(
        argv=args,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        elapsed=max(0.0, clock() - start),
    )


__all__ = [
    "COMMAND_TIMEOUT_SECONDS",
    "PROBE_TIMEOUT_SECONDS",
    "AgentCliRunnerError",
    "CommandResult",
    "run_command",
]
