"""Per-entry finalizer execution for the host-owned controller loop."""

from __future__ import annotations

import time
from typing import Any

from sase.core.finalizer_wire import FinalizerInstanceResultWire
from sase.finalizers._controller_shared import (
    ensure_declaration_with_events,
    publish_aggregate,
    sync_instance_events,
)
from sase.finalizers.commit import (
    BuiltinCommitExecution,
    BuiltinCommitFinalizerError,
    execute_commit_finalizer,
)
from sase.finalizers.commit_repair import load_commit_results
from sase.finalizers.config import FinalizerConfigDiagnostic
from sase.finalizers.controller_context import (
    declaration_recovery_spent,
    ensure_current_declaration,
)
from sase.finalizers.controller_results import (
    record_instance_metrics,
    remember_result,
    result_failure_message,
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
from sase.finalizers.progress import ProgressJournal
from sase.finalizers.providers import BUILTIN_COMMIT_PROVIDER_REF
from sase.finalizers.status_summary import FinalizerStatusTracker
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.types import ModelTier


MAX_CONTROLLER_CYCLES = 8


def execute_pending_entry(
    *,
    entry: dict[str, Any],
    instance: Any,
    config: Any,
    context: FinalizerExecutionContext,
    ledgers: dict[str, InstanceLedger],
    journal: ProgressJournal,
    tracker: FinalizerStatusTracker,
    provider: Any,
    invoke_result: Any,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    options: Any,
    artifacts_dir: str | None,
    original_prompt: str | None,
    no_model: bool,
    results_by_id: dict[str, FinalizerInstanceResultWire],
    attempts_seen: dict[str, set[int]],
    started_instances: set[str],
    ran_non_commit: set[str],
    drift_by_key: dict[tuple[str, str], FinalizerConfigDiagnostic],
    published: dict[str, Any],
    cycles: int,
) -> Any:
    """Execute one pending finalizer entry and return the invoke result.

    Records instance events and metrics, publishes the aggregate result, and
    raises ``RuntimeError`` when the entry does not reach ``success``.
    """
    started = time.monotonic()
    provider_ref = entry["provider_ref"]
    instance_id = entry["instance_id"]
    if provider_ref == BUILTIN_COMMIT_PROVIDER_REF:
        if not no_model:
            invoke_result = ensure_declaration_with_events(
                journal,
                provider=provider,
                invoke_result=invoke_result,
                model_tier=model_tier,
                suppress_output=suppress_output,
                model_override=model_override,
                artifacts_dir=artifacts_dir,
                options=options,
                original_prompt=original_prompt,
            )
        ledger = ledger_for_instance(ledgers, instance_id, instance.max_attempts)
        execution = _run_budgeted_commit(
            instance,
            context,
            ledger,
            journal=journal,
            provider=provider,
            invoke_result=invoke_result,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            options=options,
            artifacts_dir=artifacts_dir,
            original_prompt=original_prompt,
            no_model=no_model,
        )
        invoke_result = execution.invoke_result
        remember_result(results_by_id, execution.result)
        sync_instance_events(
            journal,
            tracker,
            instance_id,
            execution.result,
            attempts_seen,
            started_instances,
            max_attempts=ledger.max_attempts,
        )
        record_instance_metrics(
            provider_ref,
            instance_id,
            execution.result.status,
            len(execution.result.attempts),
            time.monotonic() - started,
        )
        deferred_and_non_failing = (
            execution.result.status == "deferred" and instance.refusal == "defer"
        )
        if execution.result.status != "success" and not deferred_and_non_failing:
            publish_aggregate(
                artifacts_dir,
                list(results_by_id.values()),
                execution.result.status,
                cycles=cycles,
                drift_by_key=drift_by_key,
                published=published,
            )
            raise RuntimeError(result_failure_message(execution.result))
        return invoke_result

    ledger = ledger_for_instance(ledgers, instance_id, instance.max_attempts)

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
    remember_result(results_by_id, result)
    sync_instance_events(
        journal,
        tracker,
        instance_id,
        result,
        attempts_seen,
        started_instances,
        max_attempts=ledger.max_attempts,
    )
    record_instance_metrics(
        provider_ref,
        instance_id,
        result.status,
        len(result.attempts),
        time.monotonic() - started,
    )
    if result.status != "success":
        publish_aggregate(
            artifacts_dir,
            list(results_by_id.values()),
            "failed",
            cycles=cycles,
            drift_by_key=drift_by_key,
            published=published,
        )
        raise RuntimeError(result_failure_message(result))
    return invoke_result


def _run_budgeted_commit(
    instance: Any,
    context: FinalizerExecutionContext,
    ledger: InstanceLedger,
    *,
    journal: ProgressJournal | None = None,
    provider: Any,
    invoke_result: Any,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    options: Any,
    artifacts_dir: str | None,
    original_prompt: str | None = None,
    no_model: bool = False,
) -> BuiltinCommitExecution:
    current_result = invoke_result
    ledger_before_run = load_commit_results(artifact_root(context.artifacts_dir))
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
                and not no_model
                and not declaration_recovery_spent(artifacts_dir)
                and ledger.consumed == consumed_before
            ):
                if journal is not None:
                    current_result = ensure_declaration_with_events(
                        journal,
                        provider=provider,
                        invoke_result=exc.invoke_result or current_result,
                        model_tier=model_tier,
                        suppress_output=suppress_output,
                        model_override=model_override,
                        artifacts_dir=artifacts_dir,
                        options=options,
                        original_prompt=original_prompt,
                    )
                else:
                    current_result = ensure_current_declaration(
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
                result_failure_message(merged),
                result=merged,
                invoke_result=exc.invoke_result,
            ) from exc
        return BuiltinCommitExecution(
            invoke_result=execution.invoke_result,
            result=ledger.record(execution.result),
        )
