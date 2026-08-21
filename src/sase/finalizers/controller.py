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
    finalizer_wire_to_json_dict,
)
from sase.finalizers.artifacts import write_finalizer_result
from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    execute_commit_finalizer,
)
from sase.finalizers.config import load_finalizer_config
from sase.finalizers.declaration import (
    FINAL_CONTEXT_FILENAME,
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    ensure_final_declaration_or_recover,
    final_submission_is_current,
    publish_final_context,
)
from sase.finalizers.executor import (
    FinalizerExecutionContext,
    execute_non_commit_finalizer,
)
from sase.finalizers.plan import load_persisted_finalizer_plan
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

    entries, plan_digest = _selected_entries(artifacts_dir)
    if not entries:
        _write_aggregate_result(artifacts_dir, [], "success", cycles=0)
        return invoke_result

    config = load_finalizer_config()
    context = FinalizerExecutionContext(
        artifacts_dir=artifacts_dir,
        plan_digest=plan_digest,
    )
    current_result = invoke_result
    results_by_id: dict[str, FinalizerInstanceResultWire] = {}
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
            publication = publish_final_context(artifacts_dir=artifacts_dir)
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
                        )
                    except BuiltinCommitFinalizerError as exc:
                        if (
                            exc.code == "stale_commit_declaration"
                            and not _declaration_recovery_spent(artifacts_dir)
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
                            )
                        else:
                            raise
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

                result = execute_non_commit_finalizer(instance, config, context)
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
            publication = publish_final_context(artifacts_dir=artifacts_dir)
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
            "failed",
            cycles=cycles,
        )
        raise
    except FinalizerControllerError as exc:
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


def _should_skip_finalizers(artifacts_dir: str | None) -> bool:
    if not artifacts_dir:
        return True
    if not os.environ.get("SASE_AGENT_TIMESTAMP"):
        return True
    return has_pending_handoff(artifacts_dir)


def _selected_entries(
    artifacts_dir: str | None,
) -> tuple[tuple[dict[str, Any], ...], str | None]:
    payload = load_persisted_finalizer_plan(artifacts_dir)
    if not payload:
        return (), None
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return (), None
    entries = plan.get("entries")
    if not isinstance(entries, list):
        return (), None
    selected: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        instance_id = entry.get("instance_id")
        provider_ref = entry.get("provider_ref")
        if (
            isinstance(instance_id, str)
            and instance_id
            and isinstance(provider_ref, str)
            and provider_ref
        ):
            selected.append(
                {
                    "instance_id": instance_id,
                    "provider_ref": provider_ref,
                    "resolved_index": int(entry.get("resolved_index", len(selected))),
                }
            )
    selected.sort(key=lambda item: int(item["resolved_index"]))
    plan_digest = plan.get("plan_digest")
    return tuple(selected), plan_digest if isinstance(plan_digest, str) else None


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
    if previous is None or not previous.attempts:
        results_by_id[result.instance_id] = result
        return
    offset = len(previous.attempts)
    merged_attempts = [
        *previous.attempts,
        *[
            replace(attempt, attempt=offset + index)
            for index, attempt in enumerate(result.attempts, start=1)
        ],
    ]
    results_by_id[result.instance_id] = replace(result, attempts=merged_attempts)


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
            )
        ],
    )


def _write_aggregate_result(
    artifacts_dir: str | None,
    instance_results: list[FinalizerInstanceResultWire],
    status: str,
    *,
    cycles: int,
) -> None:
    diagnostics: list[Any]
    if instance_results:
        try:
            aggregate = aggregate_finalizer_outcomes(instance_results)
            status = aggregate.status
            diagnostics = list(aggregate.diagnostics)
        except Exception:
            diagnostics = [
                diagnostic
                for result in instance_results
                for diagnostic in result.diagnostics
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
