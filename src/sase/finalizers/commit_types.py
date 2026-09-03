"""Shared types for built-in commit finalizer execution."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDeferralWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult


class BuiltinCommitFinalizerError(RuntimeError):
    """Raised when the built-in commit finalizer cannot prove completion."""

    def __init__(
        self,
        message: str,
        *,
        result: FinalizerInstanceResultWire,
        invoke_result: InvokeResult | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result
        self.invoke_result = invoke_result

    @property
    def code(self) -> str:
        if self.result.diagnostics:
            return self.result.diagnostics[0].code
        return "commit_failed"


@dataclass(frozen=True)
class BuiltinCommitExecution:
    """Commit finalizer execution output."""

    invoke_result: InvokeResult
    result: FinalizerInstanceResultWire


@dataclass(frozen=True)
class StitchCommandResult:
    """Result from one ``sase stitch create`` subprocess."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    argv: tuple[str, ...] = ()
    message_file: str | None = None


StitchRunner = Callable[
    [DirtyRepo, str, Sequence[str], FinalizerExecutionContext],
    StitchCommandResult,
]
ResumeRunner = Callable[
    [DirtyRepo, FinalizerExecutionContext],
    StitchCommandResult,
]


def success_result(
    instance_id: str,
    *,
    attempts: Sequence[FinalizerAttemptWire],
    evidence: Sequence[FinalizerOutcomeEvidenceWire],
    diagnostics: Sequence[FinalizerDiagnosticWire] = (),
) -> FinalizerInstanceResultWire:
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="success",
        attempts=list(attempts),
        evidence=list(evidence),
        diagnostics=list(diagnostics),
    )


def deferred_result(
    instance_id: str,
    *,
    deferral: FinalizerDeferralWire,
    attempts: Sequence[FinalizerAttemptWire],
    evidence: Sequence[FinalizerOutcomeEvidenceWire],
    diagnostics: Sequence[FinalizerDiagnosticWire] = (),
) -> FinalizerInstanceResultWire:
    """Build a non-failing result for a host-upheld commit deferral."""

    merged = [
        FinalizerDiagnosticWire(
            code="commit_deferred",
            severity="warning",
            message=(
                f"commit finalizer accepted a deferral ({deferral.reason}) for: "
                + ", ".join(deferral.paths)
            ),
            instance_id=instance_id,
            attempt=attempts[-1].attempt if attempts else None,
        ),
        *diagnostics,
    ]
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="deferred",
        attempts=list(attempts),
        deferral=deferral,
        evidence=list(evidence),
        diagnostics=merged,
    )


def failed_result(
    instance_id: str,
    code: str,
    message: str,
    *,
    attempts: Sequence[FinalizerAttemptWire] = (),
    evidence: Sequence[FinalizerOutcomeEvidenceWire] = (),
) -> FinalizerInstanceResultWire:
    recorded_attempts = list(attempts) or [
        FinalizerAttemptWire(
            attempt=1,
            status="failed",
            diagnostic_code=code,
        )
    ]
    attempt_number = recorded_attempts[-1].attempt
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="failed",
        attempts=recorded_attempts,
        evidence=list(evidence),
        diagnostics=[
            FinalizerDiagnosticWire(
                code=code,
                severity="error",
                message=message,
                instance_id=instance_id,
                attempt=attempt_number,
            )
        ],
    )


__all__ = [
    "BuiltinCommitExecution",
    "BuiltinCommitFinalizerError",
    "ResumeRunner",
    "StitchCommandResult",
    "StitchRunner",
    "deferred_result",
    "failed_result",
    "success_result",
]
