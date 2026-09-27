"""Shared types and utilities for finalizer executors."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
import os
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
)
from sase.finalizers.artifacts import instance_artifact_dir
from sase.finalizers.bounded_subprocess import (
    BoundedCompletedProcess,
    clamp_timeout_seconds,
    run_bounded_subprocess,
)
from sase.finalizers.config import ConfiguredFinalizerInstance
from sase.finalizers.providers import FinalizerProviderRecord
from sase.finalizers.steps import (
    STEPS_ENV_VAR,
    live_file_for,
    make_progress_tick,
    steps_file_for,
)


_BASE_ENV_KEYS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TERM",
    "TMPDIR",
    "USER",
)


class FinalizerExecutionError(RuntimeError):
    """Raised when a selected finalizer instance cannot complete."""


@dataclass(frozen=True)
class FinalizerExecutionContext:
    """Immutable context shared by finalizer executors."""

    artifacts_dir: str | None
    plan_digest: str | None
    run_id: str | None = None
    agent_id: str | None = None
    turn_nonce: str | None = None
    context_digest: str | None = None
    selected: tuple[str, ...] = ()
    accepted_payloads: Mapping[str, Any] = field(default_factory=dict)
    obligations: tuple[Mapping[str, Any], ...] = ()
    attempt: int | None = None
    assigned_bead_id: str | None = None
    assigned_bead_primary_repo_id: str | None = None
    journal: Any = None
    tracker: Any = None


ProviderOperationRunner = Callable[
    [
        ConfiguredFinalizerInstance,
        FinalizerProviderRecord,
        str,
        Mapping[str, Any],
        FinalizerExecutionContext,
    ],
    Mapping[str, Any],
]


def failed_result(
    instance_id: str,
    code: str,
    message: str,
    *,
    attempt: int = 1,
) -> FinalizerInstanceResultWire:
    """Build the standard failed result for a host-side execution error."""

    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="failed",
        attempts=[
            FinalizerAttemptWire(
                attempt=attempt,
                status="failed",
                diagnostic_code=code,
            )
        ],
        diagnostics=[
            FinalizerDiagnosticWire(
                code=code,
                severity="error",
                message=message,
                instance_id=instance_id,
                attempt=attempt,
            )
        ],
    )


def sanitized_env(
    allowlist: Sequence[str],
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the minimal environment allowed in a finalizer subprocess.

    *extra* entries are injected explicitly (for example the per-op
    ``SASE_FINALIZER_STEPS_FILE`` channel) and never allowlisted from the
    parent environment.
    """

    allowed = set(_BASE_ENV_KEYS)
    allowed.update(allowlist)
    env = {key: os.environ[key] for key in sorted(allowed) if key in os.environ}
    env["SASE_FINALIZER_SUBPROCESS"] = "1"
    if extra:
        for key, value in extra.items():
            if isinstance(key, str) and isinstance(value, str):
                env[key] = value
    return env


def allowed_env_names(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Extract valid environment allowlist names from provider configuration."""

    value = config.get("env")
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def op_channel_paths(
    context: FinalizerExecutionContext,
    instance_id: str,
    prefix: str,
) -> tuple[str | None, str | None]:
    """Return absolute ``(steps_path, live_path)`` for an op artifact prefix.

    Returns ``(None, None)`` when there is no artifacts dir, in which case
    the op runs without a step channel or live sink.
    """

    artifact_dir = instance_artifact_dir(
        getattr(context, "artifacts_dir", None), instance_id
    )
    if artifact_dir is None:
        return None, None
    return (
        str(artifact_dir / steps_file_for(prefix)),
        str(artifact_dir / live_file_for(prefix)),
    )


def op_steps_extra(steps_path: str | None) -> dict[str, str]:
    """Return the explicit env extra carrying the step channel, if any."""

    if not steps_path:
        return {}
    return {STEPS_ENV_VAR: steps_path}


def retain_live_sink(completed: Any) -> bool:
    """Return whether the live sink must survive this outcome.

    Accepts any outcome with ``timed_out``/``returncode`` attributes (both
    :class:`BoundedCompletedProcess` and ``StitchCommandResult`` qualify).
    The sink is retained on timeout, signal kill, or output-cap kill so
    the tail survives for diagnosis; otherwise the caller removes it once
    the terminal artifacts land.
    """

    timed_out = bool(getattr(completed, "timed_out", False))
    returncode = getattr(completed, "returncode", 0)
    return bool(timed_out or (isinstance(returncode, int) and returncode < 0))


def op_progress_tick(
    context: FinalizerExecutionContext,
    instance_id: str,
    steps_path: str | None,
) -> Callable[[], None] | None:
    """Build the wait-loop tick refreshing tracker step state, if possible."""

    tracker = getattr(context, "tracker", None)
    if tracker is None or not steps_path:
        return None
    return make_progress_tick(tracker, instance_id, steps_path)


def run_subprocess(
    argv: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    input_bytes: bytes | None,
    timeout: float,
    live_path: str | Path | None = None,
    live_streams: Collection[str] | None = None,
    progress_tick: Callable[[], None] | None = None,
    progress_tick_interval: float | None = None,
) -> BoundedCompletedProcess:
    """Run a subprocess with the finalizer runtime's hard bounds.

    *live_path* tees output to a bounded rotating sink, *live_streams*
    selects which streams are teed, and *progress_tick* refreshes step
    state while the process runs.
    """

    kwargs: dict[str, Any] = {}
    if live_path is not None:
        kwargs["live_path"] = live_path
    if live_streams is not None:
        kwargs["live_streams"] = live_streams
    if progress_tick is not None:
        kwargs["progress_tick"] = progress_tick
    if progress_tick_interval is not None:
        kwargs["progress_tick_interval"] = progress_tick_interval
    return run_bounded_subprocess(
        argv,
        cwd=cwd,
        env=env,
        input_bytes=input_bytes,
        timeout=clamp_timeout_seconds(timeout),
        **kwargs,
    )
