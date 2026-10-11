"""Command execution helpers for editable-install dev updates."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from inspect import Parameter, signature
from pathlib import Path
from typing import Any

from sase.dev_update.models import (
    DevCommandResult,
    DevCommandRunner,
    DevExecutedCommand,
    OutputSink,
)
from sase.dev_update.stream_command import run_streaming
from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider.utils import non_interactive_git_env

DEV_UPDATE_COMMAND_TIMEOUT_SECONDS = 300.0

# Reconcile steps that shell out to cargo are minutes-scale, not seconds-scale:
# a prebuild-cache miss makes `just rust-dev-install-uv-tool` build sase_core_py
# and the macro LSP from scratch, which routinely outruns the generic command
# timeout above. Bound those steps with the same ceiling the prebuild producer
# uses so a wedged build still cannot hang an update forever.
DEV_UPDATE_BUILD_COMMAND_TIMEOUT_SECONDS = 3600.0


DevAttemptRunner = Callable[..., subprocess.CompletedProcess[str]]
RecoveryHook = Callable[[str], None]
CancelCheck = Callable[[], bool]


def run_dev_update_command(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    on_output: OutputSink | None = None,
    run_attempt: DevAttemptRunner | None = None,
    on_recovery: RecoveryHook | None = None,
    cancel_check: CancelCheck | None = None,
    unix_clock: Callable[[], float] | None = None,
    monotonic_clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> DevCommandResult:
    """Run a dev-update command in a non-interactive subprocess.

    ``timeout`` of ``None`` selects :data:`DEV_UPDATE_COMMAND_TIMEOUT_SECONDS`.
    A non-``None`` ``on_output`` streams each output line through
    :func:`sase.dev_update.stream_command.run_streaming` unless *run_attempt*
    is injected; ``None`` keeps the legacy ``capture_output`` path
    byte-for-byte. Retries share one monotonic deadline and do not multiply
    the command timeout.
    """
    command = list(argv)
    total_timeout = DEV_UPDATE_COMMAND_TIMEOUT_SECONDS if timeout is None else timeout
    command_env, git_stdin = _subprocess_options(command, env)
    monotonic = monotonic_clock or time.monotonic
    started = monotonic()
    deadline = started + total_timeout
    first_attempt = True

    def remaining() -> float:
        return max(0.0, deadline - monotonic())

    def attempt() -> subprocess.CompletedProcess[str]:
        nonlocal first_attempt
        if first_attempt:
            first_attempt = False
            allowance = total_timeout
        else:
            allowance = remaining()
        if cancel_check is not None and cancel_check():
            raise RuntimeError("dev-update command cancelled")
        if allowance <= 0:
            raise subprocess.TimeoutExpired(command, total_timeout)
        if run_attempt is not None:
            kwargs: dict[str, Any] = {
                "cwd": cwd,
                "env": command_env,
                "timeout": allowance,
            }
            if _runner_accepts_keyword(run_attempt, "stdin"):
                kwargs["stdin"] = git_stdin
            return run_attempt(command, **kwargs)
        if on_output is not None:
            return run_streaming(
                command,
                cwd=cwd,
                env=command_env,
                stdin=git_stdin,
                timeout=allowance,
                on_line=on_output,
            )
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=allowance,
            env=command_env,
            stdin=git_stdin,
        )

    try:
        if command and command[0] == "git":
            completed, _outcome = run_with_git_lock_retry(
                attempt,
                cwd=_git_command_cwd(command, cwd),
                argv=command,
                env=command_env,
                on_recovery=on_recovery,
                cancel_check=cancel_check,
                unix_clock=unix_clock,
                monotonic_clock=monotonic,
                sleeper=sleeper,
                remaining_timeout=remaining,
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
    except RuntimeError as exc:
        if "cancelled" in str(exc):
            return DevCommandResult(returncode=130, stderr=str(exc))
        raise
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
    timeout: float | None = None,
    on_output: OutputSink | None = None,
    label: str,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
) -> DevCommandResult:
    """Run a command and append its result and duration to ``commands``.

    ``env`` and ``timeout`` are only forwarded when set. ``on_output`` is
    only forwarded when set and the injected runner accepts it, so an
    injected test fake that does not accept ``on_output`` keeps working even
    when a progress session is active (it just gets the legacy captured
    behavior instead of streamed lines).
    """
    start = clock()
    overrides: dict[str, Any] = {}
    if env is not None:
        overrides["env"] = _merged_subprocess_env(env)
    if timeout is not None:
        overrides["timeout"] = timeout
    if on_output is not None and _runner_accepts_keyword(run, "on_output"):
        overrides["on_output"] = on_output
    result = run(argv, cwd=cwd, **overrides)
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


def _runner_accepts_keyword(run: Callable[..., Any], name: str) -> bool:
    """Whether the injected runner accepts the ``name`` keyword."""
    try:
        params = signature(run).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        param.kind is Parameter.VAR_KEYWORD
        or (
            param.name == name
            and param.kind in (Parameter.KEYWORD_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
        )
        for param in params
    )


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
