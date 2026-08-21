"""Shared types for built-in commit finalizer execution."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
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
) -> FinalizerInstanceResultWire:
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="success",
        attempts=list(attempts),
        evidence=list(evidence),
    )


def refused_result(instance_id: str, reason: str) -> FinalizerInstanceResultWire:
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="refused",
        refusal_reason=reason,
        attempts=[
            FinalizerAttemptWire(
                attempt=1,
                status="refused",
                diagnostic_code="commit_refused",
            )
        ],
        diagnostics=[
            FinalizerDiagnosticWire(
                code="commit_refused",
                severity="error",
                message=reason,
                instance_id=instance_id,
            )
        ],
    )


def failed_result(
    instance_id: str,
    code: str,
    message: str,
    *,
    attempts: Sequence[FinalizerAttemptWire] = (),
    evidence: Sequence[FinalizerOutcomeEvidenceWire] = (),
) -> FinalizerInstanceResultWire:
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="failed",
        attempts=list(attempts)
        or [
            FinalizerAttemptWire(
                attempt=1,
                status="failed",
                diagnostic_code=code,
            )
        ],
        evidence=list(evidence),
        diagnostics=[
            FinalizerDiagnosticWire(
                code=code,
                severity="error",
                message=message,
                instance_id=instance_id,
            )
        ],
    )


__all__ = [
    "BuiltinCommitExecution",
    "BuiltinCommitFinalizerError",
    "ResumeRunner",
    "StitchCommandResult",
    "StitchRunner",
    "failed_result",
    "refused_result",
    "success_result",
]
