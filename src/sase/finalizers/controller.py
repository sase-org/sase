"""Host-owned finalizer controller entry point."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
import os
from pathlib import Path
import time
from typing import Any

from sase.agent.pending_handoff import has_pending_handoff
from sase.core.finalizer_facade import aggregate_finalizer_outcomes
from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
    FinalizerPlanWire,
    finalizer_wire_to_json_dict,
)
from sase.finalizers.artifacts import write_finalizer_result
from sase.finalizers.commit import (
    BuiltinCommitExecution,
    BuiltinCommitFinalizerError,
    execute_commit_finalizer,
)
from sase.finalizers.config import load_finalizer_config
from sase.finalizers.declaration import (
    FINAL_CONTEXT_FILENAME,
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    FinalContextPublication,
    FinalizerDeclarationError,
    ensure_final_declaration_or_recover,
    final_submission_is_current,
    load_latest_finalizer_submission,
    publish_final_context,
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
    authenticate_resolved_finalizer_plan,
)
from sase.finalizers.providers import BUILTIN_COMMIT_PROVIDER_REF
from sase.llm_provider.types import ModelTier
from sase.telemetry.metrics import FINALIZER_ATTEMPTS, FINALIZER_DURATION


MAX_CONTROLLER_CYCLES = 8


class FinalizerControllerError(RuntimeError):
    """Raised when the generic controller cannot reach a safe fixed point."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


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

    try:
        plan = authenticate_resolved_finalizer_plan(artifacts_dir)
    except FinalizerPlanIntegrityError as exc:
        raise FinalizerControllerError(str(exc), code=exc.code) from exc
    entries = _entries_from_plan(plan)
    if not entries:
        _write_aggregate_result(artifacts_dir, [], "success", cycles=0)
        return invoke_result

    context = FinalizerExecutionContext(
        artifacts_dir=artifacts_dir,
        plan_digest=plan.plan_digest,
        selected=tuple(entry.instance_id for entry in plan.entries),
    )
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
        )
        for cycle in range(1, MAX_CONTROLLER_CYCLES + 1):
            cycles = cycle
            plan = authenticate_resolved_finalizer_plan(artifacts_dir)
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
                plan = authenticate_resolved_finalizer_plan(artifacts_dir)
                entries = _entries_from_plan(plan)
                config = load_finalizer_config()
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
                    if execution.result.status != "success":
                        _write_aggregate_result(
                            artifacts_dir,
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
                    )
                    raise RuntimeError(_result_failure_message(result))
                progressed = True

            if not progressed:
                raise FinalizerControllerError(
                    "finalizer controller made no progress; no executor ran",
                    code="controller_no_progress",
                )
            plan = authenticate_resolved_finalizer_plan(artifacts_dir)
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
        )
        raise

    _write_aggregate_result(
        artifacts_dir,
        list(results_by_id.values()),
        "success",
        cycles=cycles,
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
) -> BuiltinCommitExecution:
    current_result = invoke_result
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
                )
                return BuiltinCommitExecution(
                    invoke_result=execution.invoke_result,
                    result=ledger.record(execution.result),
                )
            merged = ledger.record(exc.result)
            if is_retryable_result(merged) and ledger.remaining() > 0:
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


def _should_skip_finalizers(artifacts_dir: str | None) -> bool:
    if not artifacts_dir:
        return True
    if not os.environ.get("SASE_AGENT_TIMESTAMP"):
        return True
    return has_pending_handoff(artifacts_dir)


def _entries_from_plan(plan: FinalizerPlanWire) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "instance_id": entry.instance_id,
            "provider_ref": entry.provider_ref,
            "resolved_index": entry.resolved_index,
        }
        for entry in plan.entries
    )


def _bind_execution_context(
    artifacts_dir: str | None,
    plan: FinalizerPlanWire,
    publication: FinalContextPublication,
) -> FinalizerExecutionContext:
    payloads: dict[str, Any] = {}
    if artifacts_dir:
        try:
            submission = load_latest_finalizer_submission(Path(artifacts_dir))
        except FinalizerDeclarationError:
            submission = None
        raw = submission.get("submission") if isinstance(submission, Mapping) else None
        items = raw.get("payloads") if isinstance(raw, Mapping) else None
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                instance_id = item.get("instance_id")
                if isinstance(instance_id, str) and "payload" in item:
                    payloads[instance_id] = item.get("payload")
    return FinalizerExecutionContext(
        artifacts_dir=artifacts_dir,
        plan_digest=plan.plan_digest,
        run_id=publication.context.run_id,
        agent_id=publication.context.agent_id,
        turn_nonce=publication.context.turn_nonce,
        context_digest=publication.context.context_digest,
        selected=tuple(entry.instance_id for entry in plan.entries),
        accepted_payloads=payloads,
        obligations=tuple(
            finalizer_wire_to_json_dict(item)
            for item in publication.context.obligations
        ),
    )


def _ensure_current_declaration(
    *,
    provider: Any,
    invoke_result: Any,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None,
    options: Any,
) -> Any:
    publication = publish_final_context(artifacts_dir=artifacts_dir)
    if not publication.submission_required or final_submission_is_current(
        artifacts_dir=artifacts_dir
    ):
        return invoke_result
    if _declaration_recovery_spent(artifacts_dir):
        raise FinalizerControllerError(
            "required finalizer declaration is missing or stale and the "
            "declaration-recovery budget is exhausted",
            code="stale_declaration",
        )
    recovered = ensure_final_declaration_or_recover(
        provider=provider,
        invoke_result=invoke_result,
        model_tier=model_tier,
        suppress_output=suppress_output,
        model_override=model_override,
        artifacts_dir=artifacts_dir,
        options=options,
    )
    _rebind_turn_nonce_to_accepted_context(artifacts_dir)
    return recovered


def _rebind_turn_nonce_to_accepted_context(artifacts_dir: str | None) -> None:
    if not artifacts_dir:
        return
    try:
        payload = json.loads(
            (Path(artifacts_dir) / FINAL_CONTEXT_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, Mapping):
        return
    context = payload.get("context")
    if not isinstance(context, Mapping):
        return
    nonce = context.get("turn_nonce")
    if isinstance(nonce, str) and nonce:
        os.environ[SASE_FINAL_TURN_NONCE_ENV] = nonce


def _declaration_recovery_spent(artifacts_dir: str | None) -> bool:
    if not artifacts_dir:
        return False
    return (Path(artifacts_dir) / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).is_file()


def _pending_instance_ids(
    entries: tuple[dict[str, Any], ...],
    payload: Mapping[str, Any],
    results_by_id: Mapping[str, FinalizerInstanceResultWire],
    ran_non_commit: set[str],
) -> tuple[str, ...]:
    selected = payload.get("selected_instances")
    requirements: dict[str, Mapping[str, Any]] = {}
    if isinstance(selected, list):
        for item in selected:
            if isinstance(item, Mapping) and isinstance(item.get("instance_id"), str):
                requirements[str(item["instance_id"])] = item
    pending: list[str] = []
    for entry in entries:
        instance_id = entry["instance_id"]
        provider_ref = entry["provider_ref"]
        if provider_ref == BUILTIN_COMMIT_PROVIDER_REF:
            requirement = requirements.get(instance_id, {})
            triggered = bool(
                requirement.get("submission_required")
                or requirement.get("trigger") == "dirty_repository"
            )
            previous = results_by_id.get(instance_id)
            if previous is None or previous.status != "success" or triggered:
                pending.append(instance_id)
            continue
        if instance_id not in ran_non_commit:
            pending.append(instance_id)
    return tuple(pending)


def _cycle_fingerprint(context_digest: str | None, pending: tuple[str, ...]) -> str:
    digest = context_digest or ""
    return f"{digest}:{','.join(pending)}"


def _remember_result(
    results_by_id: dict[str, FinalizerInstanceResultWire],
    result: FinalizerInstanceResultWire,
) -> None:
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


def _failed_result(
    instance_id: str,
    code: str,
    message: str,
) -> FinalizerInstanceResultWire:
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


_STATUS_RANK = {"success": 0, "pending": 1, "refused": 2, "failed": 3}


def _fail_closed_status(requested: str, aggregated: str) -> str:
    if _STATUS_RANK.get(requested, 0) >= _STATUS_RANK.get(aggregated, 0):
        return requested
    return aggregated


def _write_aggregate_result(
    artifacts_dir: str | None,
    instance_results: list[FinalizerInstanceResultWire],
    status: str,
    *,
    cycles: int,
) -> None:
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
            finalizer_wire_to_json_dict(diagnostic) for diagnostic in diagnostics
        ],
    }
    write_finalizer_result(artifacts_dir, payload)


def _record_instance_metrics(
    provider_ref: str,
    instance_id: str,
    status: str,
    attempts: int,
    duration_seconds: float,
) -> None:
    labels = {
        "provider": provider_ref,
        "instance": instance_id,
        "result": status,
    }
    FINALIZER_DURATION.labels(**labels).observe(duration_seconds)
    for _ in range(max(1, attempts)):
        FINALIZER_ATTEMPTS.labels(**labels).inc()


def _result_failure_message(result: FinalizerInstanceResultWire) -> str:
    if result.diagnostics:
        return result.diagnostics[0].message
    return f"finalizer {result.instance_id!r} failed"


__all__ = [
    "FinalizerControllerError",
    "run_finalizers",
]
