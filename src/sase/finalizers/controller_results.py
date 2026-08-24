"""Result bookkeeping and publication for the finalizer controller."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from sase.core.finalizer_facade import aggregate_finalizer_outcomes
from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
    finalizer_wire_to_json_dict,
)
from sase.finalizers.artifacts import write_finalizer_result
from sase.telemetry.metrics import FINALIZER_ATTEMPTS, FINALIZER_DURATION


def remember_result(
    results_by_id: dict[str, FinalizerInstanceResultWire],
    result: FinalizerInstanceResultWire,
) -> None:
    """Store a result, merging evidence from earlier attempts of the instance."""
    previous = results_by_id.get(result.instance_id)
    if previous is None:
        results_by_id[result.instance_id] = result
        return
    seen = {item.attempt for item in previous.attempts}
    merged_attempts = [
        *previous.attempts,
        *[item for item in result.attempts if item.attempt not in seen],
    ]
    results_by_id[result.instance_id] = replace(
        result,
        attempts=merged_attempts,
        evidence=[*previous.evidence, *result.evidence],
        diagnostics=[*previous.diagnostics, *result.diagnostics],
        refusal_reason=result.refusal_reason or previous.refusal_reason,
    )


def failed_result(
    instance_id: str,
    code: str,
    message: str,
) -> FinalizerInstanceResultWire:
    """Create a standardized failed result for a controller-level error."""
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="failed",
        attempts=[
            FinalizerAttemptWire(
                attempt=1,
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
                attempt=1,
            )
        ],
    )


_STATUS_RANK = {"success": 0, "deferred": 1, "pending": 2, "refused": 3, "failed": 4}


def _fail_closed_status(requested: str, aggregated: str) -> str:
    if _STATUS_RANK.get(requested, 0) >= _STATUS_RANK.get(aggregated, 0):
        return requested
    return aggregated


def write_aggregate_result(
    artifacts_dir: str | None,
    instance_results: list[FinalizerInstanceResultWire],
    status: str,
    *,
    cycles: int,
    extra_diagnostics: Sequence[FinalizerDiagnosticWire] = (),
) -> None:
    """Aggregate instance results and publish the fail-closed controller result.

    ``extra_diagnostics`` carries plan-level diagnostics (e.g. sealed-config
    drift) that apply to the whole turn rather than to one instance's attempts.
    """
    requested = status
    diagnostics: list[Any]
    if instance_results:
        try:
            aggregate = aggregate_finalizer_outcomes(instance_results)
            status = _fail_closed_status(requested, aggregate.status)
            diagnostics = list(aggregate.diagnostics)
            if status == "failed" and aggregate.status == "success":
                diagnostics = [
                    FinalizerDiagnosticWire(
                        code="controller_failed",
                        severity="error",
                        message=(
                            "controller failed closed; aggregate success was "
                            "not published"
                        ),
                    ),
                    *diagnostics,
                ]
        except Exception:
            status = requested if requested != "success" else "failed"
            diagnostics = [
                diagnostic
                for result in instance_results
                for diagnostic in result.diagnostics
            ]
            if not diagnostics:
                diagnostics = [
                    FinalizerDiagnosticWire(
                        code="aggregate_integrity_failed",
                        severity="error",
                        message="finalizer aggregation failed closed",
                    )
                ]
    else:
        diagnostics = []
    payload = {
        "schema_version": 1,
        "status": status,
        "cycles": cycles,
        "instances": [
            finalizer_wire_to_json_dict(result) for result in instance_results
        ],
        "diagnostics": [
            finalizer_wire_to_json_dict(diagnostic)
            for diagnostic in (*diagnostics, *extra_diagnostics)
        ],
    }
    write_finalizer_result(artifacts_dir, payload)


def record_instance_metrics(
    provider_ref: str,
    instance_id: str,
    status: str,
    attempts: int,
    duration_seconds: float,
) -> None:
    """Record timing and attempt metrics for one finalizer instance."""
    labels = {
        "provider": provider_ref,
        "instance": instance_id,
        "result": status,
    }
    FINALIZER_DURATION.labels(**labels).observe(duration_seconds)
    for _ in range(max(1, attempts)):
        FINALIZER_ATTEMPTS.labels(**labels).inc()


def result_failure_message(result: FinalizerInstanceResultWire) -> str:
    """Return the most useful error message exposed by a failed result."""
    if result.diagnostics:
        return result.diagnostics[0].message
    return f"finalizer {result.instance_id!r} failed"
