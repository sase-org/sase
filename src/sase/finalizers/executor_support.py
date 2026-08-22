"""Shared types and utilities for finalizer executors."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import os
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
)
from sase.finalizers.bounded_subprocess import (
    BoundedCompletedProcess,
    clamp_timeout_seconds,
    run_bounded_subprocess,
)
from sase.finalizers.config import ConfiguredFinalizerInstance
from sase.finalizers.providers import FinalizerProviderRecord


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


def sanitized_env(allowlist: Sequence[str]) -> dict[str, str]:
    """Return the minimal environment allowed in a finalizer subprocess."""

    allowed = set(_BASE_ENV_KEYS)
    allowed.update(allowlist)
    env = {key: os.environ[key] for key in sorted(allowed) if key in os.environ}
    env["SASE_FINALIZER_SUBPROCESS"] = "1"
    return env


def allowed_env_names(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Extract valid environment allowlist names from provider configuration."""

    value = config.get("env")
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def run_subprocess(
    argv: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    input_bytes: bytes | None,
    timeout: float,
) -> BoundedCompletedProcess:
    """Run a subprocess with the finalizer runtime's hard bounds."""

    return run_bounded_subprocess(
        argv,
        cwd=cwd,
        env=env,
        input_bytes=input_bytes,
        timeout=clamp_timeout_seconds(timeout),
    )
