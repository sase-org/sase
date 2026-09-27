"""Host-owned finalizer controller entry point and execution loop."""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
)
from sase.core.process_identity import process_identity_token
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
from dataclasses import replace as _replace_context

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
from sase.finalizers.progress import ProgressJournal
from sase.finalizers.providers import BUILTIN_COMMIT_PROVIDER_REF, BUILTIN_PROVIDER_REFS
from sase.finalizers.status_summary import (
    FinalizerStatusTracker,
    count_result_warnings,
    headline_from_evidence,
    reason_for_result,
)
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.types import ModelTier


MAX_CONTROLLER_CYCLES = 8


def _journal_handoff_skip(artifacts_dir: str | None) -> None:
    """Best-effort record a handoff skip; silent without a dir and marker."""
    if not artifacts_dir:
        return
    if not os.environ.get("SASE_AGENT_TIMESTAMP"):
        return
    from sase.agent.pending_handoff import pending_handoff_kind

    kind = pending_handoff_kind(artifacts_dir)
    if kind is None:
        return
    reason = f"handoff:{kind}"
    try:
        ProgressJournal(artifacts_dir).record("phase_skipped", reason=reason)
    except Exception:
        pass
    try:
        FinalizerStatusTracker(artifacts_dir).mark_skipped(reason=reason)
    except Exception:
        pass


def _runner_fact() -> dict[str, Any]:
    """Return the runner identity fact for ``phase_started`` records."""
    pid = os.getpid()
    return {"pid": pid, "identity": process_identity_token(pid) or None}


def _bind_observed_context(
    artifacts_dir: str | None,
    plan: Any,
    publication: Any,
    journal: ProgressJournal,
    tracker: Any,
) -> FinalizerExecutionContext:
    """Bind an execution context carrying the shared journal and tracker."""
    context = _bind_execution_context(artifacts_dir, plan, publication)
    try:
        return _replace_context(context, journal=journal, tracker=tracker)
    except Exception:
        return context


def _ensure_declaration_with_events(
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
        result = _ensure_current_declaration(
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


def _sync_instance_events(
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
    mode: str = "normal",
) -> Any:
    """Drive selected finalizers to a bounded fixed point.

    The built-in commit instance consumes the accepted final declaration and
    dispatches repository mutations through ``sase stitch create``. Later
    mutating executors can reactivate commit; declaration recovery and
    conflict repair keep separate one-shot budgets.
    """

    no_model = mode == "no_model"
    if not no_model and _should_skip_finalizers(artifacts_dir):
        _journal_handoff_skip(artifacts_dir)
        return invoke_result

    journal = ProgressJournal(artifacts_dir)
    tracker = FinalizerStatusTracker(artifacts_dir)
    attempts_seen: dict[str, set[int]] = {}
    started_instances: set[str] = set()
    published: dict[str, Any] = {"status": "failed", "cycles": 0}

    def _publish_aggregate(
        results: list[FinalizerInstanceResultWire],
        status: str,
        *,
        cycles: int,
        extra_diagnostics: tuple[FinalizerConfigDiagnostic, ...] = (),
    ) -> None:
        _write_aggregate_result(
            artifacts_dir,
            results,
            status,
            cycles=cycles,
            extra_diagnostics=_drift_diagnostic_wires(drift_by_key),
        )
        published["status"] = status
        published["cycles"] = cycles

    drift_by_key: dict[tuple[str, str], FinalizerConfigDiagnostic] = {}
    try:
        authenticated = authenticate_resolved_finalizer_plan_full(artifacts_dir)
    except FinalizerPlanIntegrityError as exc:
        journal.record("phase_finished", status="failed", cycles=0)
        tracker.mark_settled(status="failed", reason=exc.code)
        raise FinalizerControllerError(str(exc), code=exc.code) from exc
    plan = authenticated.plan
    _remember_drift(drift_by_key, authenticated.drift)
    run_id = uuid.uuid4().hex
    runner = _runner_fact()
    journal.record(
        "phase_started",
        run_id=run_id,
        plan_digest=plan.plan_digest,
        mode=mode,
        runner=runner,
    )
    tracker.mark_declaring(run_id=run_id, plan_digest=plan.plan_digest, runner=runner)
    entries = _entries_from_plan(plan)
    if not entries:
        _publish_aggregate([], "success", cycles=0)
        journal.record("phase_finished", status="success", cycles=0)
        tracker.mark_settled(status="success")
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
        if no_model:
            _reject_no_model_ineligible_plan(entries, artifacts_dir)
        else:
            current_result = _ensure_declaration_with_events(
                journal,
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
            journal.record("cycle_started", cycle=cycle)
            authenticated = authenticate_resolved_finalizer_plan_full(artifacts_dir)
            plan = authenticated.plan
            _remember_drift(drift_by_key, authenticated.drift)
            entries = _entries_from_plan(plan)
            publication = publish_final_context(artifacts_dir=artifacts_dir)
            context = _bind_observed_context(
                artifacts_dir, plan, publication, journal, tracker
            )
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
                context = _bind_observed_context(
                    artifacts_dir, plan, publication, journal, tracker
                )
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
                    if not no_model:
                        current_result = _ensure_declaration_with_events(
                            journal,
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
                        journal=journal,
                        provider=provider,
                        invoke_result=current_result,
                        model_tier=model_tier,
                        suppress_output=suppress_output,
                        model_override=model_override,
                        options=options,
                        artifacts_dir=artifacts_dir,
                        original_prompt=original_prompt,
                        no_model=no_model,
                    )
                    current_result = execution.invoke_result
                    _remember_result(results_by_id, execution.result)
                    _sync_instance_events(
                        journal,
                        tracker,
                        instance_id,
                        execution.result,
                        attempts_seen,
                        started_instances,
                        max_attempts=ledger.max_attempts,
                    )
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
                        _publish_aggregate(
                            list(results_by_id.values()),
                            execution.result.status,
                            cycles=cycles,
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
                _sync_instance_events(
                    journal,
                    tracker,
                    instance_id,
                    result,
                    attempts_seen,
                    started_instances,
                    max_attempts=ledger.max_attempts,
                )
                _record_instance_metrics(
                    provider_ref,
                    instance_id,
                    result.status,
                    len(result.attempts),
                    time.monotonic() - started,
                )
                if result.status != "success":
                    _publish_aggregate(
                        list(results_by_id.values()),
                        "failed",
                        cycles=cycles,
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
            context = _bind_observed_context(
                artifacts_dir, plan, publication, journal, tracker
            )
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
        _publish_aggregate(
            list(results_by_id.values()),
            "success",
            cycles=cycles,
        )
    except FinalizerPlanIntegrityError as exc:
        raise FinalizerControllerError(str(exc), code=exc.code) from exc
    except BuiltinCommitFinalizerError as exc:
        if exc.invoke_result is not None:
            current_result = exc.invoke_result
        _remember_result(results_by_id, exc.result)
        if active_instance_id is not None:
            _sync_instance_events(
                journal,
                tracker,
                active_instance_id,
                exc.result,
                attempts_seen,
                started_instances,
            )
        if active_provider_ref is not None and active_instance_id is not None:
            _record_instance_metrics(
                active_provider_ref,
                active_instance_id,
                exc.result.status,
                len(exc.result.attempts),
                time.monotonic() - (active_started or time.monotonic()),
            )
        _publish_aggregate(
            list(results_by_id.values()),
            exc.result.status
            if exc.result.status in {"failed", "refused"}
            else "failed",
            cycles=cycles,
        )
        raise
    except FinalizerControllerError as exc:
        if exc.code == "plan_integrity_failed":
            raise
        instance_id = active_instance_id or (
            entries[0]["instance_id"] if entries else "controller"
        )
        failed = _failed_result(instance_id, exc.code, str(exc))
        _remember_result(results_by_id, failed)
        _sync_instance_events(
            journal, tracker, instance_id, failed, attempts_seen, started_instances
        )
        _publish_aggregate(
            list(results_by_id.values()),
            "failed",
            cycles=cycles,
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
            failed = _failed_result(
                instance_id,
                "controller_exception",
                f"{type(exc).__name__}: {exc}",
            )
            _remember_result(results_by_id, failed)
            _sync_instance_events(
                journal,
                tracker,
                instance_id,
                failed,
                attempts_seen,
                started_instances,
            )
        _publish_aggregate(
            list(results_by_id.values()),
            "failed",
            cycles=cycles,
        )
        raise
    finally:
        if artifacts_dir and drift_by_key:
            _project_drift_to_agent_meta(artifacts_dir, drift_by_key)
        journal.record(
            "phase_finished", status=published["status"], cycles=published["cycles"]
        )
        tracker.mark_settled(status=published["status"])

    return current_result


def _reject_no_model_ineligible_plan(
    entries: tuple[dict[str, Any], ...],
    artifacts_dir: str | None,
) -> None:
    from sase.finalizers.declaration import (
        final_submission_is_current,
        publish_final_context,
    )

    publication = publish_final_context(artifacts_dir=artifacts_dir)
    if publication.submission_required and not final_submission_is_current(
        artifacts_dir=artifacts_dir
    ):
        raise FinalizerControllerError(
            "no-model host completion requires an accepted declaration",
            code="no_model_declaration_missing",
        )
    for entry in entries:
        if entry["provider_ref"] not in BUILTIN_PROVIDER_REFS:
            raise FinalizerControllerError(
                f"finalizer {entry['instance_id']!r} ({entry['provider_ref']}) "
                "does not support no-model host completion",
                code="no_model_unsupported_executor",
            )


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
                and not no_model
                and not _declaration_recovery_spent(artifacts_dir)
                and ledger.consumed == consumed_before
            ):
                if journal is not None:
                    current_result = _ensure_declaration_with_events(
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
                _result_failure_message(merged),
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
