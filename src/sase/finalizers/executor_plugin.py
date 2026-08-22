"""Execution of external finalizers through the isolated worker protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
import sys
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.artifacts import instance_artifact_dir, write_text_artifact
from sase.finalizers.bounded_subprocess import (
    HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS,
    STDOUT_CAP_BYTES,
    BoundedCompletedProcess,
)
from sase.finalizers.config import ConfiguredFinalizerInstance, FinalizerConfig
from sase.finalizers.executor_protocol import (
    provider_diagnostics,
    provider_evidence,
    provider_request,
    validate_provider_result,
)
from sase.finalizers.executor_support import (
    FinalizerExecutionContext,
    FinalizerExecutionError,
    ProviderOperationRunner,
    allowed_env_names,
    run_subprocess,
    sanitized_env,
)
from sase.finalizers.ledger import InstanceLedger, run_budgeted_attempts
from sase.finalizers.providers import FinalizerProviderRecord
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir


PROVIDER_OPERATION_TIMEOUT_SECONDS = 30.0


def execute_plugin_finalizer(
    instance: ConfiguredFinalizerInstance,
    config: FinalizerConfig,
    context: FinalizerExecutionContext,
    provider: FinalizerProviderRecord,
    *,
    operation_runner: ProviderOperationRunner,
    ledger: InstanceLedger | None = None,
) -> FinalizerInstanceResultWire:
    """Execute an already-resolved external finalizer provider."""

    owned = ledger or InstanceLedger(
        instance.instance_id, max(1, instance.max_attempts)
    )

    def run_once() -> FinalizerInstanceResultWire:
        return _execute_plugin_once(
            instance, config, context, provider, operation_runner, owned
        )

    if ledger is None:
        return run_budgeted_attempts(owned, run_once)
    return run_once()


def run_provider_operation(
    instance: ConfiguredFinalizerInstance,
    provider: FinalizerProviderRecord,
    operation: str,
    request: Mapping[str, Any],
    context: FinalizerExecutionContext,
) -> Mapping[str, Any]:
    """Run one external provider operation in a sanitized Python subprocess."""

    argv = [
        sys.executable,
        "-m",
        "sase.finalizers.worker_entry",
        "--provider-ref",
        provider.provider_ref,
        "--operation",
        operation,
    ]
    payload = json.dumps(dict(request), sort_keys=True).encode("utf-8")
    if len(payload) > STDOUT_CAP_BYTES:
        raise FinalizerExecutionError("provider request exceeded size cap")
    completed = run_subprocess(
        argv,
        cwd=resolve_finalizer_project_dir(),
        env=sanitized_env(allowed_env_names(instance.config)),
        input_bytes=payload,
        timeout=min(
            PROVIDER_OPERATION_TIMEOUT_SECONDS, HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS
        ),
    )
    _write_provider_attempt_artifacts(instance, operation, context, completed)
    if completed.timed_out:
        raise FinalizerExecutionError(
            f"provider operation {operation!r} timed out after "
            f"{PROVIDER_OPERATION_TIMEOUT_SECONDS:g}s"
        )
    if completed.stdout_truncated or completed.stderr_truncated:
        raise FinalizerExecutionError("provider operation exceeded output cap")
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except Exception as exc:
        raise FinalizerExecutionError(
            f"provider operation {operation!r} emitted malformed JSON: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(result, Mapping):
        raise FinalizerExecutionError(
            f"provider operation {operation!r} must return a JSON object"
        )
    if completed.returncode != 0 and result.get("status") not in {"failed", "ok"}:
        raise FinalizerExecutionError(
            f"provider operation {operation!r} exited with {completed.returncode}"
        )
    return result


def _execute_plugin_once(
    instance: ConfiguredFinalizerInstance,
    config: FinalizerConfig,
    context: FinalizerExecutionContext,
    provider: FinalizerProviderRecord,
    operation_runner: ProviderOperationRunner,
    ledger: InstanceLedger,
) -> FinalizerInstanceResultWire:
    evidence: list[FinalizerOutcomeEvidenceWire] = []
    diagnostics: list[FinalizerDiagnosticWire] = []
    attempt: int | None = None
    for operation in ("describe", "validate", "execute", "verify"):
        if operation == "execute":
            attempt = ledger.consume_before_execute()
        bound_context = (
            context if attempt is None else replace(context, attempt=attempt)
        )
        request = provider_request(instance, config, bound_context, operation)
        try:
            result = operation_runner(
                instance, provider, operation, request, bound_context
            )
            if operation == "execute" and str(result.get("status")) == "skipped":
                raise FinalizerExecutionError(
                    "provider-authored skipped is not allowed; only the host "
                    "may skip an untriggered instance"
                )
            validate_provider_result(instance, operation, result)
        except FinalizerExecutionError as exc:
            if attempt is None:
                attempt = ledger.allocate_attempt()
            code = (
                "provider_skipped_forbidden"
                if "provider-authored skipped" in str(exc)
                else f"provider_{operation}_failed"
            )
            return FinalizerInstanceResultWire(
                instance_id=instance.instance_id,
                status="failed",
                attempts=[
                    FinalizerAttemptWire(
                        attempt=attempt,
                        status="failed",
                        diagnostic_code=code,
                    )
                ],
                evidence=evidence,
                diagnostics=[
                    FinalizerDiagnosticWire(
                        code=code,
                        severity="error",
                        message=str(exc),
                        instance_id=instance.instance_id,
                        attempt=attempt,
                    )
                ],
            )
        status = str(result.get("status"))
        if operation == "execute":
            assert attempt is not None
            evidence.extend(provider_evidence(result))
            if status != "success":
                execute_diagnostics = provider_diagnostics(
                    instance, result, attempt=attempt
                )
                return FinalizerInstanceResultWire(
                    instance_id=instance.instance_id,
                    status="failed",
                    attempts=[
                        FinalizerAttemptWire(
                            attempt=attempt,
                            status="failed",
                            diagnostic_code="execute_failed",
                        )
                    ],
                    evidence=evidence,
                    diagnostics=execute_diagnostics
                    or [
                        FinalizerDiagnosticWire(
                            code="execute_failed",
                            severity="error",
                            message=(
                                f"provider execute for {instance.instance_id!r} failed"
                            ),
                            instance_id=instance.instance_id,
                            attempt=attempt,
                        )
                    ],
                )
            diagnostics.extend(provider_diagnostics(instance, result, attempt=attempt))
        else:
            diagnostics.extend(provider_diagnostics(instance, result, attempt=attempt))
    assert attempt is not None
    return FinalizerInstanceResultWire(
        instance_id=instance.instance_id,
        status="success",
        attempts=[FinalizerAttemptWire(attempt=attempt, status="success")],
        evidence=evidence,
        diagnostics=diagnostics,
    )


def _write_provider_attempt_artifacts(
    instance: ConfiguredFinalizerInstance,
    operation: str,
    context: FinalizerExecutionContext,
    completed: BoundedCompletedProcess,
) -> None:
    artifact_dir = instance_artifact_dir(context.artifacts_dir, instance.instance_id)
    if artifact_dir is None:
        return
    if context.attempt is not None:
        prefix = f"attempt-{context.attempt}.{operation}"
        exclusive = True
    else:
        prefix = operation
        exclusive = False
    try:
        write_text_artifact(
            artifact_dir / f"{prefix}.stdout",
            completed.stdout.decode("utf-8", errors="replace"),
            exclusive=exclusive,
        )
        write_text_artifact(
            artifact_dir / f"{prefix}.stderr",
            completed.stderr.decode("utf-8", errors="replace"),
            exclusive=exclusive,
        )
    except FileExistsError as exc:
        raise FinalizerExecutionError(str(exc)) from exc
