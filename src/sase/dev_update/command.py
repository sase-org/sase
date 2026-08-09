"""Command execution helpers for editable-install dev updates."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from sase.dev_update.models import (
    DevCommandResult,
    DevCommandRunner,
    DevExecutedCommand,
)
from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider.utils import non_interactive_git_env

DEV_UPDATE_COMMAND_TIMEOUT_SECONDS = 300.0


def run_dev_update_command(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = DEV_UPDATE_COMMAND_TIMEOUT_SECONDS,
) -> DevCommandResult:
    """Run a dev-update command in a non-interactive subprocess."""
    command = list(argv)
    command_env, git_stdin = _subprocess_options(command, env)

    def attempt() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=command_env,
            stdin=git_stdin,
        )

    try:
        if command and command[0] == "git":
            completed, _outcome = run_with_git_lock_retry(
                attempt,
                cwd=_git_command_cwd(command, cwd),
            )
        else:
            completed = attempt()
    except FileNotFoundError as exc:
        return DevCommandResult(returncode=127, stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        return DevCommandResult(
            returncode=124,
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr="command timed out",
        )
    except OSError as exc:
        return DevCommandResult(returncode=1, stderr=str(exc))
    return DevCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_recorded_command(
    run: DevCommandRunner,
    argv: Sequence[str],
    *,
    cwd: Path | None,
    env: Mapping[str, str] | None = None,
    label: str,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
) -> DevCommandResult:
    """Run a command and append its result and duration to ``commands``."""
    start = clock()
    if env is None:
        result = run(argv, cwd=cwd)
    else:
        result = run(argv, cwd=cwd, env=env)
    duration = max(0.0, clock() - start)
    commands.append(
        DevExecutedCommand(
            label=label,
            command=tuple(argv),
            cwd=str(cwd) if cwd else None,
            returncode=result.returncode,
            duration_seconds=duration,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    )
    return result


def command_failure(prefix: str, result: DevCommandResult) -> str:
    """Format a failed command result for a dev-update outcome."""
    detail = result.stderr.strip() or result.stdout.strip()
    if detail:
        return f"{prefix}: {detail}"
    return f"{prefix}: exit {result.returncode}"


def _subprocess_options(
    argv: Sequence[str],
    env: Mapping[str, str] | None,
) -> tuple[dict[str, str] | None, int | None]:
    base_env = _merged_subprocess_env(env)
    if not argv or argv[0] != "git":
        return base_env, None
    return non_interactive_git_env(base_env), subprocess.DEVNULL


def _merged_subprocess_env(env: Mapping[str, str] | None) -> dict[str, str] | None:
    if env is None:
        return None
    merged = dict(os.environ)
    merged.update(env)
    return merged


def _git_command_cwd(argv: Sequence[str], cwd: Path | None) -> Path:
    try:
        index = argv.index("-C")
        configured = Path(argv[index + 1])
    except (ValueError, IndexError):
        return Path.cwd() if cwd is None else cwd
    if configured.is_absolute() or cwd is None:
        return configured
    return cwd / configured
