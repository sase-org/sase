"""Rust-backed deterministic retryability classifier facade.

The Rust core classifies observed ``git``/``gh`` stdout, stderr, exit
status, and operation kind. Python owns subprocess execution, sleeps,
deadline arithmetic, and call-site policy.
"""

from __future__ import annotations

from sase.core.retryability_wire import (
    RETRY_OPERATION_GIT_CLONE,
    RetryabilityVerdictWire,
    retryability_verdict_from_dict,
)
from sase.core.rust import require_rust_binding


def classify_failure_retryability(
    operation_kind: str,
    *,
    exit_status: int | None = None,
    stdout: str = "",
    stderr: str = "",
) -> RetryabilityVerdictWire:
    """Classify one observed failure through ``sase_core_rs``."""
    binding = require_rust_binding("classify_failure_retryability")
    raw: dict[str, object] = binding(operation_kind, exit_status, stdout, stderr)
    return retryability_verdict_from_dict(raw)


def is_retryable_failure(
    *,
    operation_kind: str,
    exit_status: int | None = None,
    stdout: str = "",
    stderr: str = "",
) -> bool:
    """Return whether the shared classifier says the failure can be retried."""
    return classify_failure_retryability(
        operation_kind,
        exit_status=exit_status,
        stdout=stdout,
        stderr=stderr,
    ).retryable


def is_retryable_git_clone_failure(detail: str) -> bool:
    """Compatibility helper for the legacy SDD clone retry call site."""
    return is_retryable_failure(
        operation_kind=RETRY_OPERATION_GIT_CLONE,
        stderr=detail,
    )


__all__ = [
    "classify_failure_retryability",
    "is_retryable_failure",
    "is_retryable_git_clone_failure",
]
