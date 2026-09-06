"""Host-owned finalizer controller entry point and execution loop."""

from __future__ import annotations

import time
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
)
from sase.finalizers.commit import (
    BuiltinCommitExecution,
    BuiltinCommitFinalizerError,
    execute_commit_finalizer,
)
from sase.finalizers.commit_repair import load_commit_results as _load_commit_results
from sase.finalizers.config import FinalizerConfigDiagnostic
from sase.finalizers.controller_context import (
    FinalizerControllerError,
    bind_execution_context as _bind_execution_context,
    cycle_fingerprint as _cycle_fingerprint,
    declaration_recovery_spent as _declaration_recovery_spent,
    ensure_current_declaration as _ensure_current_declaration,
    entries_from_plan as _entries_from_plan,
    pending_instance_ids as _pending_instance_ids,
    publish_final_context,
    should_skip_finalizers as _should_skip_finalizers,
)
from sase.finalizers.controller_results import (
    failed_result as _failed_result,
    record_instance_metrics as _record_instance_metrics,
    remember_result as _remember_result,
    result_failure_message as _result_failure_message,
    write_aggregate_result as _write_aggregate_result,
)
from sase.finalizers.executor import (
    FinalizerExecutionContext,
    execute_non_commit_finalizer,
)
from sase.finalizers.ledger import (
    InstanceLedger,
    is_retryable_result,
    ledger_for_instance,
    run_budgeted_attempts,
)
from sase.finalizers.plan import (
    FinalizerPlanIntegrityError,
    authenticate_resolved_finalizer_plan_full,
)
from sase.finalizers.providers import BUILTIN_COMMIT_PROVIDER_REF
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.types import ModelTier


MAX_CONTROLLER_CYCLES = 8


def _remember_drift(
    drift_by_key: dict[tuple[str, str], FinalizerConfigDiagnostic],
    drift: tuple[FinalizerConfigDiagnostic, ...],
) -> None:
    for item in drift:
        drift_by_key[(item.code, item.path)] = item


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


def _project_drift_to_agent_meta(
    artifacts_dir: str,
    drift_by_key: dict[tuple[str, str], FinalizerConfigDiagnostic],
) -> None:
    """Best-effort surface sealed-config drift on ``agent_meta.json`` for ACE."""

    from sase.axe.run_agent_helpers import update_meta_field

    try:
        update_meta_field(
            artifacts_dir,
            "finalizers_drift",
            [
                {"code": item.code, "severity": item.severity, "message": item.message}
                for item in drift_by_key.values()
            ],
        )
    except Exception:
        pass


def run_finalizers(
    *,
    provider: Any,
    original_prompt: str,
    invoke_result: Any,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None,
    options: Any = None,
) -> Any:
    """Drive selected finalizers to a bounded fixed point.

    The built-in commit instance consumes the accepted final declaration and
    dispatches repository mutations through ``sase stitch create``. Later
    mutating executors can reactivate commit; declaration recovery and
    conflict repair keep separate one-shot budgets.
    """

    if _should_skip_finalizers(artifacts_dir):
        return invoke_result

    drift_by_key: dict[tuple[str, str], FinalizerConfigDiagnostic] = {}
    try:
        authenticated = authenticate_resolved_finalizer_plan_full(artifacts_dir)
    except FinalizerPlanIntegrityError as exc:
        raise FinalizerControllerError(str(exc), code=exc.code) from exc
    plan = authenticated.plan
    _remember_drift(drift_by_key, authenticated.drift)
    entries = _entries_from_plan(plan)
    if not entries:
        _write_aggregate_result(
            artifacts_dir,
            [],
            "success",
            cycles=0,
            extra_diagnostics=_drift_diagnostic_wires(drift_by_key),
        )
        return invoke_result

    current_result = invoke_result
    results_by_id: dict[str, FinalizerInstanceResultWire] = {}
    ledgers: dict[str, InstanceLedger] = {}
    ran_non_commit: set[str] = set()
    fingerprints: set[str] = set()
    active_provider_ref: str | None = None
    active_instance_id: str | None = None
    active_started: float | None = None
    cycles = 0

    try:
        current_result = _ensure_current_declaration(
            provider=provider,
            invoke_result=current_result,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            artifacts_dir=artifacts_dir,
            options=options,
            original_prompt=original_prompt,
        )
        for cycle in range(1, MAX_CONTROLLER_CYCLES + 1):
            cycles = cycle
            authenticated = authenticate_resolved_finalizer_plan_full(artifacts_dir)
            plan = authenticated.plan
            _remember_drift(drift_by_key, authenticated.drift)
            entries = _entries_from_plan(plan)
            publication = publish_final_context(artifacts_dir=artifacts_dir)
            context = _bind_execution_context(artifacts_dir, plan, publication)
            pending = _pending_instance_ids(
                entries,
                publication.payload,
                results_by_id,
                ran_non_commit,
            )
            fingerprint = _cycle_fingerprint(
                publication.context.context_digest, pending
            )
            if fingerprint in fingerprints:
                raise FinalizerControllerError(
                    "finalizer controller made no progress; dirty state and "
                    "pending instances did not change",
                    code="controller_no_progress",
                )
            fingerprints.add(fingerprint)
            if not pending:
                break

            progressed = False
            for entry in entries:
                instance_id = entry["instance_id"]
                if instance_id not in pending:
                    continue
                authenticated = authenticate_resolved_finalizer_plan_full(artifacts_dir)
                plan = authenticated.plan
                _remember_drift(drift_by_key, authenticated.drift)
                entries = _entries_from_plan(plan)
                config = authenticated.config
                context = _bind_execution_context(artifacts_dir, plan, publication)
                provider_ref = entry["provider_ref"]
                instance = config.instances.get(instance_id)
                if instance is None:
                    raise FinalizerControllerError(
                        f"selected finalizer instance {instance_id!r} is not configured",
                        code="missing_instance",
                    )
                active_provider_ref = provider_ref
                active_instance_id = instance_id
                started = time.monotonic()
                active_started = started
                if provider_ref == BUILTIN_COMMIT_PROVIDER_REF:
                    current_result = _ensure_current_declaration(
                        provider=provider,
                        invoke_result=current_result,
                        model_tier=model_tier,
                        suppress_output=suppress_output,
                        model_override=model_override,
                        artifacts_dir=artifacts_dir,
                        options=options,
                        original_prompt=original_prompt,
                    )
                    ledger = ledger_for_instance(
                        ledgers, instance_id, instance.max_attempts
                    )
                    execution = _run_budgeted_commit(
                        instance,
                        context,
                        ledger,
                        provider=provider,
                        invoke_result=current_result,
                        model_tier=model_tier,
                        suppress_output=suppress_output,
                        model_override=model_override,
                        options=options,
                        artifacts_dir=artifacts_dir,
                        original_prompt=original_prompt,
                    )
                    current_result = execution.invoke_result
                    _remember_result(results_by_id, execution.result)
                    _record_instance_metrics(
                        provider_ref,
                        instance_id,
                        execution.result.status,
                        len(execution.result.attempts),
                        time.monotonic() - started,
                    )
                    deferred_and_non_failing = (
                        execution.result.status == "deferred"
                        and instance.refusal == "defer"
                    )
                    if (
                        execution.result.status != "success"
                        and not deferred_and_non_failing
                    ):
                        _write_aggregate_result(
                            artifacts_dir,
                            list(results_by_id.values()),
                            execution.result.status,
                            cycles=cycles,
                            extra_diagnostics=_drift_diagnostic_wires(drift_by_key),
                        )
                        raise RuntimeError(_result_failure_message(execution.result))
                    progressed = True
                    continue

                ledger = ledger_for_instance(
                    ledgers, instance_id, instance.max_attempts
                )

                def _run_non_commit(
                    bound_instance: Any = instance,
                    bound_config: Any = config,
                    bound_context: FinalizerExecutionContext = context,
                    bound_ledger: InstanceLedger = ledger,
                ) -> FinalizerInstanceResultWire:
                    return execute_non_commit_finalizer(
                        bound_instance,
                        bound_config,
                        bound_context,
                        ledger=bound_ledger,
                    )

                result = run_budgeted_attempts(ledger, _run_non_commit)
                ran_non_commit.add(instance_id)
                _remember_result(results_by_id, result)
                _record_instance_metrics(
                    provider_ref,
                    instance_id,
                    result.status,
                    len(result.attempts),
                    time.monotonic() - started,
                )
                if result.status != "success":
                    _write_aggregate_result(
                        artifacts_dir,
                        list(results_by_id.values()),
                        "failed",
                        cycles=cycles,
                        extra_diagnostics=_drift_diagnostic_wires(drift_by_key),
                    )
                    raise RuntimeError(_result_failure_message(result))
                progressed = True

            if not progressed:
                raise FinalizerControllerError(
                    "finalizer controller made no progress; no executor ran",
                    code="controller_no_progress",
                )
            authenticated = authenticate_resolved_finalizer_plan_full(artifacts_dir)
            plan = authenticated.plan
            _remember_drift(drift_by_key, authenticated.drift)
            entries = _entries_from_plan(plan)
            publication = publish_final_context(artifacts_dir=artifacts_dir)
            context = _bind_execution_context(artifacts_dir, plan, publication)
            if not _pending_instance_ids(
                entries,
                publication.payload,
                results_by_id,
                ran_non_commit,
            ):
                break
        else:
            raise FinalizerControllerError(
                f"finalizer controller exceeded {MAX_CONTROLLER_CYCLES} cycles "
                "without reaching a fixed point",
                code="controller_cycle_limit",
            )
    except FinalizerPlanIntegrityError as exc:
        raise FinalizerControllerError(str(exc), code=exc.code) from exc
    except BuiltinCommitFinalizerError as exc:
        if exc.invoke_result is not None:
            current_result = exc.invoke_result
        _remember_result(results_by_id, exc.result)
        if active_provider_ref is not None and active_instance_id is not None:
            _record_instance_metrics(
                active_provider_ref,
                active_instance_id,
                exc.result.status,
                len(exc.result.attempts),
                time.monotonic() - (active_started or time.monotonic()),
            )
        _write_aggregate_result(
            artifacts_dir,
            list(results_by_id.values()),
            exc.result.status
            if exc.result.status in {"failed", "refused"}
            else "failed",
            cycles=cycles,
            extra_diagnostics=_drift_diagnostic_wires(drift_by_key),
        )
        raise
    except FinalizerControllerError as exc:
        if exc.code == "plan_integrity_failed":
            raise
        instance_id = active_instance_id or (
            entries[0]["instance_id"] if entries else "controller"
        )
        _remember_result(
            results_by_id,
            _failed_result(instance_id, exc.code, str(exc)),
        )
        _write_aggregate_result(
            artifacts_dir,
            list(results_by_id.values()),
            "failed",
            cycles=cycles,
            extra_diagnostics=_drift_diagnostic_wires(drift_by_key),
        )
        raise
    except Exception as exc:
        if getattr(exc, "code", None) == "plan_integrity_failed":
            raise FinalizerControllerError(
                str(exc),
                code="plan_integrity_failed",
            ) from exc
        if not results_by_id or next(reversed(results_by_id.values())).status == (
            "success"
        ):
            instance_id = active_instance_id or entries[0]["instance_id"]
            _remember_result(
                results_by_id,
                _failed_result(
                    instance_id,
                    "controller_exception",
                    f"{type(exc).__name__}: {exc}",
                ),
            )
        _write_aggregate_result(
            artifacts_dir,
            list(results_by_id.values()),
            "failed",
            cycles=cycles,
            extra_diagnostics=_drift_diagnostic_wires(drift_by_key),
        )
        raise
    finally:
        if artifacts_dir and drift_by_key:
            _project_drift_to_agent_meta(artifacts_dir, drift_by_key)

    _write_aggregate_result(
        artifacts_dir,
        list(results_by_id.values()),
        "success",
        cycles=cycles,
        extra_diagnostics=_drift_diagnostic_wires(drift_by_key),
    )
    return current_result


def _run_budgeted_commit(
    instance: Any,
    context: FinalizerExecutionContext,
    ledger: InstanceLedger,
    *,
    provider: Any,
    invoke_result: Any,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    options: Any,
    artifacts_dir: str | None,
    original_prompt: str | None = None,
) -> BuiltinCommitExecution:
    current_result = invoke_result
    ledger_before_run = _load_commit_results(artifact_root(context.artifacts_dir))
    while True:
        consumed_before = ledger.consumed
        try:
            execution = execute_commit_finalizer(
                instance,
                context,
                provider=provider,
                invoke_result=current_result,
                model_tier=model_tier,
                suppress_output=suppress_output,
                model_override=model_override,
                options=options,
                ledger=ledger,
                ledger_before_already_clean=ledger_before_run,
            )
        except BuiltinCommitFinalizerError as exc:
            if (
                exc.code == "stale_commit_declaration"
                and not _declaration_recovery_spent(artifacts_dir)
                and ledger.consumed == consumed_before
            ):
                current_result = _ensure_current_declaration(
                    provider=provider,
                    invoke_result=exc.invoke_result or current_result,
                    model_tier=model_tier,
                    suppress_output=suppress_output,
                    model_override=model_override,
                    artifacts_dir=artifacts_dir,
                    options=options,
                    original_prompt=original_prompt,
                )
                execution = execute_commit_finalizer(
                    instance,
                    context,
                    provider=provider,
                    invoke_result=current_result,
                    model_tier=model_tier,
                    suppress_output=suppress_output,
                    model_override=model_override,
                    options=options,
                    ledger=ledger,
                    ledger_before_already_clean=ledger_before_run,
                )
                return BuiltinCommitExecution(
                    invoke_result=execution.invoke_result,
                    result=ledger.record(execution.result),
                )
            merged = ledger.record(exc.result)
            if (
                ledger.consumed > consumed_before
                and is_retryable_result(exc.result)
                and ledger.remaining() > 0
            ):
                if exc.invoke_result is not None:
                    current_result = exc.invoke_result
                continue
            raise BuiltinCommitFinalizerError(
                str(exc),
                result=merged,
                invoke_result=exc.invoke_result,
            ) from exc
        return BuiltinCommitExecution(
            invoke_result=execution.invoke_result,
            result=ledger.record(execution.result),
        )


__all__ = [
    "FinalizerControllerError",
    "run_finalizers",
]
