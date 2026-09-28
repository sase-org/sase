"""Helpers shared by more than one finalizer controller module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
)
from sase.finalizers.config import FinalizerConfigDiagnostic
from sase.finalizers.controller_context import ensure_current_declaration
from sase.finalizers.controller_results import write_aggregate_result
from sase.finalizers.progress import ProgressJournal
from sase.finalizers.status_summary import (
    FinalizerStatusTracker,
    count_result_warnings,
    headline_from_evidence,
    reason_for_result,
)
from sase.llm_provider.types import ModelTier


def ensure_declaration_with_events(
    journal: ProgressJournal,
    *,
    provider: Any,
    invoke_result: Any,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None,
    options: Any,
    original_prompt: str | None = None,
) -> Any:
    """Wrap declaration ensure with journal declaration/recovery events."""
    from sase.finalizers.declaration_recovery import (
        FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    )

    recovery_path = (
        Path(artifacts_dir) / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME
        if artifacts_dir
        else None
    )
    had_recovery = recovery_path.is_file() if recovery_path is not None else True
    journal.record("declaration_started")
    try:
        result = ensure_current_declaration(
            provider=provider,
            invoke_result=invoke_result,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            artifacts_dir=artifacts_dir,
            options=options,
            original_prompt=original_prompt,
        )
    except Exception as exc:
        ran_recovery = (
            recovery_path is not None and not had_recovery and recovery_path.is_file()
        )
        if ran_recovery:
            journal.record("recovery_turn_started")
            journal.record("recovery_turn_finished", ok=False)
        journal.record(
            "declaration_finished",
            status="failed",
            code=getattr(exc, "code", type(exc).__name__),
        )
        raise
    ran_recovery = (
        recovery_path is not None and not had_recovery and recovery_path.is_file()
    )
    if ran_recovery:
        journal.record("recovery_turn_started")
        journal.record("recovery_turn_finished", ok=True)
    journal.record(
        "declaration_finished", status="recovered" if ran_recovery else "accepted"
    )
    return result


def _result_code(result: FinalizerInstanceResultWire) -> str | None:
    """Return the most useful diagnostic code for an instance result."""
    if result.attempts and result.attempts[-1].diagnostic_code:
        return result.attempts[-1].diagnostic_code
    if result.diagnostics:
        return result.diagnostics[-1].code
    return None


def sync_instance_events(
    journal: ProgressJournal,
    tracker: FinalizerStatusTracker,
    instance_id: str,
    result: FinalizerInstanceResultWire,
    attempts_seen: dict[str, set[int]],
    started_instances: set[str],
    *,
    max_attempts: int = 1,
) -> None:
    """Emit journal/tracker instance and attempt events for a fresh result."""
    if instance_id not in started_instances:
        started_instances.add(instance_id)
        journal.record("instance_started", instance_id=instance_id)
        tracker.note_instance_started(instance_id, max_attempts=max_attempts)
    seen = attempts_seen.setdefault(instance_id, set())
    for attempt in result.attempts:
        if attempt.attempt in seen:
            continue
        seen.add(attempt.attempt)
        journal.record(
            "attempt_started",
            instance_id=instance_id,
            attempt=attempt.attempt,
            max_attempts=max_attempts,
        )
        tracker.note_attempt_started(instance_id, attempt.attempt, max_attempts)
        journal.record(
            "attempt_finished",
            instance_id=instance_id,
            attempt=attempt.attempt,
            max_attempts=max_attempts,
            status=attempt.status,
            code=attempt.diagnostic_code,
        )
        tracker.note_attempt_finished(
            instance_id, attempt.attempt, status=attempt.status
        )
    journal.record(
        "instance_finished",
        instance_id=instance_id,
        status=result.status,
        code=_result_code(result),
    )
    latest_attempt = result.attempts[-1].attempt if result.attempts else 0
    tracker.note_instance_finished(
        instance_id,
        status=result.status,
        reason=reason_for_result(result),
        headline=headline_from_evidence(result.evidence),
        warnings=count_result_warnings(result),
        attempt=latest_attempt,
        max_attempts=max_attempts,
    )


def _drift_diagnostic_wires(
    drift_by_key: dict[tuple[str, str], FinalizerConfigDiagnostic],
) -> tuple[FinalizerDiagnosticWire, ...]:
    return tuple(
        FinalizerDiagnosticWire(
            code=item.code,
            severity=item.severity,
            message=item.message,
        )
        for item in drift_by_key.values()
    )


def publish_aggregate(
    artifacts_dir: str | None,
    results: list[FinalizerInstanceResultWire],
    status: str,
    *,
    cycles: int,
    drift_by_key: dict[tuple[str, str], FinalizerConfigDiagnostic],
    published: dict[str, Any],
) -> None:
    """Publish the aggregate controller result and record its outcome."""
    write_aggregate_result(
        artifacts_dir,
        results,
        status,
        cycles=cycles,
        extra_diagnostics=_drift_diagnostic_wires(drift_by_key),
    )
    published["status"] = status
    published["cycles"] = cycles
