"""Host-owned per-instance mutating-attempt budget and retry policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDeferralWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
    FinalizerOutcomeEvidenceWire,
)


RETRYABLE_DIAGNOSTIC_CODES = frozenset(
    {
        "command_failed",
        "execute_failed",
        "provider_execute_failed",
        "stitch_failed",
    }
)


class FinalizerBudgetError(RuntimeError):
    """Raised when a mutating instance execution would exceed ``max_attempts``."""


@dataclass
class InstanceLedger:
    """Controller-owned attempt, evidence, and budget state for one instance."""

    instance_id: str
    max_attempts: int
    consumed: int = 0
    next_attempt: int = 1
    attempts: list[FinalizerAttemptWire] = field(default_factory=list)
    evidence: list[FinalizerOutcomeEvidenceWire] = field(default_factory=list)
    diagnostics: list[FinalizerDiagnosticWire] = field(default_factory=list)
    refusal_reason: str | None = None
    deferral: FinalizerDeferralWire | None = None
    status: str = "pending"

    def remaining(self) -> int:
        return max(0, self.max_attempts - self.consumed)

    def consume_before_execute(self) -> int:
        """Allocate the next mutating attempt id, consuming budget first."""

        if self.consumed >= self.max_attempts:
            raise FinalizerBudgetError(
                f"finalizer {self.instance_id!r} exhausted {self.max_attempts} "
                "mutating attempt(s)"
            )
        self.consumed += 1
        return self.allocate_attempt()

    def allocate_attempt(self) -> int:
        """Return a unique increasing attempt id without consuming budget."""

        attempt = self.next_attempt
        self.next_attempt += 1
        return attempt

    def record(
        self, result: FinalizerInstanceResultWire
    ) -> FinalizerInstanceResultWire:
        """Merge *result* into this ledger without replacing prior evidence."""

        seen = {item.attempt for item in self.attempts}
        for attempt in result.attempts:
            if attempt.attempt not in seen:
                self.attempts.append(attempt)
                seen.add(attempt.attempt)
        self.evidence.extend(result.evidence)
        self.diagnostics.extend(result.diagnostics)
        if result.refusal_reason:
            self.refusal_reason = result.refusal_reason
        if result.deferral is not None:
            self.deferral = result.deferral
        self.status = result.status
        return self.to_result()

    def to_result(self) -> FinalizerInstanceResultWire:
        return FinalizerInstanceResultWire(
            instance_id=self.instance_id,
            status=self.status,
            attempts=list(self.attempts),
            refusal_reason=self.refusal_reason,
            deferral=self.deferral,
            evidence=list(self.evidence),
            diagnostics=list(self.diagnostics),
        )

    def exhausted_result(self) -> FinalizerInstanceResultWire:
        attempt = self.allocate_attempt()
        diagnostic = FinalizerDiagnosticWire(
            code="attempt_budget_exhausted",
            message=(
                f"finalizer {self.instance_id!r} exhausted {self.max_attempts} "
                "mutating attempt(s)"
            ),
            severity="error",
            instance_id=self.instance_id,
            attempt=attempt,
        )
        self.attempts.append(
            FinalizerAttemptWire(
                attempt=attempt,
                status="failed",
                diagnostic_code="attempt_budget_exhausted",
            )
        )
        self.diagnostics.append(diagnostic)
        self.status = "failed"
        return self.to_result()


def is_retryable_result(result: FinalizerInstanceResultWire) -> bool:
    """Return whether the host retry policy treats *result* as retryable."""

    if result.status != "failed":
        return False
    codes: list[str] = []
    if result.attempts:
        code = result.attempts[-1].diagnostic_code
        if code:
            codes.append(code)
    codes.extend(diagnostic.code for diagnostic in result.diagnostics)
    return any(code in RETRYABLE_DIAGNOSTIC_CODES for code in codes)


def run_budgeted_attempts(
    ledger: InstanceLedger,
    run_once: Callable[[], FinalizerInstanceResultWire],
) -> FinalizerInstanceResultWire:
    """Run mutating executions until success, a terminal failure, or budget end."""

    while True:
        if ledger.remaining() <= 0 and ledger.consumed > 0:
            return ledger.exhausted_result()
        consumed_before = ledger.consumed
        try:
            result = run_once()
        except FinalizerBudgetError:
            return ledger.exhausted_result()
        if result.status == "success":
            return ledger.record(result)
        if ledger.consumed == consumed_before:
            return ledger.record(result)
        merged = ledger.record(result)
        if is_retryable_result(merged) and ledger.remaining() > 0:
            continue
        return merged


def ledger_for_instance(
    ledgers: dict[str, InstanceLedger],
    instance_id: str,
    max_attempts: int,
) -> InstanceLedger:
    """Return the durable per-instance ledger, creating it on first use."""

    existing = ledgers.get(instance_id)
    if existing is not None:
        return existing
    created = InstanceLedger(instance_id=instance_id, max_attempts=max(1, max_attempts))
    ledgers[instance_id] = created
    return created


__all__ = [
    "FinalizerBudgetError",
    "InstanceLedger",
    "is_retryable_result",
    "ledger_for_instance",
    "run_budgeted_attempts",
]
