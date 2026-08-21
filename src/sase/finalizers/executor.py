"""Bounded execution for selected finalizer instances."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerAttemptWire,
    FinalizerContextWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
    FinalizerOutcomeEvidenceWire,
    finalizer_wire_to_json_dict,
)
from sase.finalizers.artifacts import (
    instance_artifact_dir,
    write_json_atomic,
    write_text_artifact,
)
from sase.finalizers.bounded_subprocess import (
    HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS,
    STDOUT_CAP_BYTES,
    BoundedCompletedProcess,
    clamp_timeout_seconds,
    run_bounded_subprocess,
)
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    load_finalizer_config,
)
from sase.finalizers.ledger import InstanceLedger, run_budgeted_attempts
from sase.finalizers.providers import (
    BUILTIN_COMMAND_PROVIDER_REF,
    BUILTIN_COMMIT_PROVIDER_REF,
    CommandFinalizerConfig,
    FinalizerProviderRecord,
    collect_finalizer_providers,
    fatal_provider_diagnostics,
    parse_command_finalizer_config,
    provider_records_by_ref,
    provider_ref_key,
)
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir


PROVIDER_OPERATION_TIMEOUT_SECONDS = 30.0

_BASE_ENV_KEYS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TERM",
    "TMPDIR",
    "USER",
)
_PROVIDER_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "operation",
        "provider_ref",
        "instance_id",
        "status",
        "message",
        "diagnostics",
        "evidence",
        "provider_version",
        "capabilities",
        "payload",
    }
)
_NON_EXECUTE_SUCCESS_STATUSES = frozenset({"ok", "success"})
_EXECUTE_STATUSES = frozenset({"success", "failed"})


class FinalizerExecutionError(RuntimeError):
    """Raised when a selected finalizer instance cannot complete."""


@dataclass(frozen=True)
class FinalizerExecutionContext:
    """Immutable context shared by finalizer executors."""

    artifacts_dir: str | None
    plan_digest: str | None
    run_id: str | None = None
    agent_id: str | None = None
    turn_nonce: str | None = None
    context_digest: str | None = None
    selected: tuple[str, ...] = ()
    accepted_payloads: Mapping[str, Any] = field(default_factory=dict)
    obligations: tuple[Mapping[str, Any], ...] = ()
    attempt: int | None = None


ProviderOperationRunner = Callable[
    [
        ConfiguredFinalizerInstance,
        FinalizerProviderRecord,
        str,
        Mapping[str, Any],
        FinalizerExecutionContext,
    ],
    Mapping[str, Any],
]


def execute_non_commit_finalizer(
    instance: ConfiguredFinalizerInstance,
    config: FinalizerConfig,
    context: FinalizerExecutionContext,
    *,
    operation_runner: ProviderOperationRunner | None = None,
    ledger: InstanceLedger | None = None,
) -> FinalizerInstanceResultWire:
    """Execute a selected non-commit finalizer instance."""

    if instance.provider_ref == BUILTIN_COMMIT_PROVIDER_REF:
        raise FinalizerExecutionError("commit is handled by the commit finalizer")
    if instance.provider_ref == BUILTIN_COMMAND_PROVIDER_REF:
        return execute_command_finalizer(instance, context, ledger=ledger)
    return execute_plugin_finalizer(
        instance,
        config,
        context,
        operation_runner=operation_runner or run_provider_operation,
        ledger=ledger,
    )


def execute_command_finalizer(
    instance: ConfiguredFinalizerInstance,
    context: FinalizerExecutionContext,
    *,
    ledger: InstanceLedger | None = None,
) -> FinalizerInstanceResultWire:
    """Run a constrained ``builtin@command`` finalizer."""

    command_config, diagnostics = parse_command_finalizer_config(instance)
    fatal = fatal_provider_diagnostics(diagnostics)
    if command_config is None or fatal:
        return _failed_result(
            instance.instance_id,
            "invalid_command_config",
            fatal[0].message if fatal else "invalid builtin@command config",
        )

    owned = ledger or InstanceLedger(
        instance.instance_id, max(1, instance.max_attempts)
    )

    def run_once() -> FinalizerInstanceResultWire:
        return _execute_command_once(instance, command_config, context, owned)

    if ledger is None:
        return run_budgeted_attempts(owned, run_once)
    return run_once()


def execute_plugin_finalizer(
    instance: ConfiguredFinalizerInstance,
    config: FinalizerConfig,
    context: FinalizerExecutionContext,
    *,
    operation_runner: ProviderOperationRunner,
    ledger: InstanceLedger | None = None,
) -> FinalizerInstanceResultWire:
    """Execute an external finalizer through the isolated worker protocol."""

    providers = collect_finalizer_providers()
    provider = provider_records_by_ref(providers).get(
        provider_ref_key(instance.provider_ref)
    )
    if provider is None:
        return _failed_result(
            instance.instance_id,
            "missing_provider",
            f"finalizer provider {instance.provider_ref!r} is not installed",
        )
    if provider.disabled_by:
        joined = ", ".join(provider.disabled_by)
        return _failed_result(
            instance.instance_id,
            "provider_disabled",
            f"finalizer provider {instance.provider_ref!r} is disabled by {joined}",
        )

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


def validate_external_declaration_payload(
    instance_id: str,
    provider_ref: str,
    context: FinalizerContextWire,
    payload: Any,
    *,
    selected: Sequence[str] | None = None,
) -> None:
    """Run the selected provider's validate operation for one declaration payload."""

    if not isinstance(payload, Mapping):
        raise FinalizerExecutionError(
            f"finalizer payload for {instance_id} must be an object"
        )
    config = load_finalizer_config()
    instance = config.instances.get(instance_id)
    if instance is None or provider_ref_key(instance.provider_ref) != provider_ref_key(
        provider_ref
    ):
        raise FinalizerExecutionError(f"unknown finalizer instance {instance_id!r}")
    exec_context = FinalizerExecutionContext(
        artifacts_dir=os.environ.get("SASE_ARTIFACTS_DIR"),
        plan_digest=context.plan_digest,
        run_id=context.run_id,
        agent_id=context.agent_id,
        turn_nonce=context.turn_nonce,
        context_digest=context.context_digest,
        selected=tuple(selected) if selected is not None else (instance_id,),
        accepted_payloads={instance_id: dict(payload)},
        obligations=tuple(
            finalizer_wire_to_json_dict(item) for item in context.obligations
        ),
    )
    providers = collect_finalizer_providers()
    provider = provider_records_by_ref(providers).get(provider_ref_key(provider_ref))
    if provider is None:
        raise FinalizerExecutionError(
            f"finalizer provider {provider_ref!r} is not installed"
        )
    if provider.disabled_by:
        joined = ", ".join(provider.disabled_by)
        raise FinalizerExecutionError(
            f"finalizer provider {provider_ref!r} is disabled by {joined}"
        )
    request = _provider_request(instance, config, exec_context, "validate")
    request["payload"] = dict(payload)
    request["obligations"] = finalizer_wire_to_json_dict(list(context.obligations))
    result = run_provider_operation(
        instance, provider, "validate", request, exec_context
    )
    _validate_provider_result(instance, "validate", result)


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
    completed = _run_subprocess(
        argv,
        cwd=resolve_finalizer_project_dir(),
        env=_sanitized_env(_allowed_env_names(instance.config)),
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


def result_to_json(result: FinalizerInstanceResultWire) -> dict[str, Any]:
    """Project an instance result wire object to JSON."""

    return finalizer_wire_to_json_dict(result)


def _execute_command_once(
    instance: ConfiguredFinalizerInstance,
    command_config: CommandFinalizerConfig,
    context: FinalizerExecutionContext,
    ledger: InstanceLedger,
) -> FinalizerInstanceResultWire:
    attempt = ledger.consume_before_execute()
    result = _run_command_attempt(instance, command_config, context, attempt)
    if result["returncode"] == 0:
        return FinalizerInstanceResultWire(
            instance_id=instance.instance_id,
            status="success",
            attempts=[
                FinalizerAttemptWire(attempt=attempt, status="success"),
            ],
            evidence=result["evidence"],
        )
    code = str(result["diagnostic_code"])
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
        evidence=result["evidence"],
        diagnostics=[
            FinalizerDiagnosticWire(
                code=code,
                severity="error",
                message=(
                    f"builtin@command {instance.instance_id!r} failed on "
                    f"attempt {attempt}"
                ),
                instance_id=instance.instance_id,
                attempt=attempt,
            )
        ],
    )


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
        request = _provider_request(instance, config, bound_context, operation)
        try:
            result = operation_runner(
                instance, provider, operation, request, bound_context
            )
            if operation == "execute" and str(result.get("status")) == "skipped":
                raise FinalizerExecutionError(
                    "provider-authored skipped is not allowed; only the host "
                    "may skip an untriggered instance"
                )
            _validate_provider_result(instance, operation, result)
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
            evidence.extend(_provider_evidence(result))
            if status != "success":
                execute_diagnostics = _provider_diagnostics(
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
            diagnostics.extend(_provider_diagnostics(instance, result, attempt=attempt))
        else:
            diagnostics.extend(_provider_diagnostics(instance, result, attempt=attempt))
    assert attempt is not None
    return FinalizerInstanceResultWire(
        instance_id=instance.instance_id,
        status="success",
        attempts=[
            FinalizerAttemptWire(attempt=attempt, status="success"),
        ],
        evidence=evidence,
        diagnostics=diagnostics,
    )


def _run_command_attempt(
    instance: ConfiguredFinalizerInstance,
    command_config: CommandFinalizerConfig,
    context: FinalizerExecutionContext,
    attempt: int,
) -> dict[str, Any]:
    started = time.monotonic()
    completed = _run_subprocess(
        list(command_config.command),
        cwd=_resolve_cwd(command_config),
        env=_sanitized_env(command_config.env),
        input_bytes=None,
        timeout=clamp_timeout_seconds(command_config.timeout_seconds),
    )
    duration = completed.duration_seconds or (time.monotonic() - started)
    _write_command_attempt_artifacts(instance, attempt, context, completed)
    evidence = [
        FinalizerOutcomeEvidenceWire(kind="exit_code", value=str(completed.returncode)),
        FinalizerOutcomeEvidenceWire(kind="duration_seconds", value=f"{duration:.3f}"),
    ]
    if completed.timed_out:
        return {
            "returncode": 124,
            "diagnostic_code": "command_timeout",
            "evidence": evidence,
        }
    if completed.stdout_truncated or completed.stderr_truncated:
        return {
            "returncode": 125,
            "diagnostic_code": "command_output_cap",
            "evidence": evidence,
        }
    return {
        "returncode": completed.returncode,
        "diagnostic_code": "command_failed",
        "evidence": evidence,
    }


def _run_subprocess(
    argv: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    input_bytes: bytes | None,
    timeout: float,
) -> BoundedCompletedProcess:
    return run_bounded_subprocess(
        argv,
        cwd=cwd,
        env=env,
        input_bytes=input_bytes,
        timeout=clamp_timeout_seconds(timeout),
    )


def _write_command_attempt_artifacts(
    instance: ConfiguredFinalizerInstance,
    attempt: int,
    context: FinalizerExecutionContext,
    completed: BoundedCompletedProcess,
) -> None:
    artifact_dir = instance_artifact_dir(context.artifacts_dir, instance.instance_id)
    if artifact_dir is None:
        return
    _write_exclusive_text(
        artifact_dir / f"attempt-{attempt}.stdout",
        completed.stdout.decode("utf-8", errors="replace"),
    )
    _write_exclusive_text(
        artifact_dir / f"attempt-{attempt}.stderr",
        completed.stderr.decode("utf-8", errors="replace"),
    )
    payload = {
        "attempt": attempt,
        "returncode": completed.returncode,
        "timed_out": completed.timed_out,
        "stdout_truncated": completed.stdout_truncated,
        "stderr_truncated": completed.stderr_truncated,
    }
    try:
        write_json_atomic(
            artifact_dir / f"attempt-{attempt}.diagnostics.json",
            payload,
            exclusive=True,
        )
    except FileExistsError as exc:
        raise FinalizerExecutionError(str(exc)) from exc


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


def _write_exclusive_text(path: Path, text: str) -> None:
    try:
        write_text_artifact(path, text, exclusive=True)
    except FileExistsError as exc:
        raise FinalizerExecutionError(str(exc)) from exc


def _provider_request(
    instance: ConfiguredFinalizerInstance,
    config: FinalizerConfig,
    context: FinalizerExecutionContext,
    operation: str,
) -> dict[str, Any]:
    del config
    if context.selected:
        payloads = dict(context.accepted_payloads)
        obligations = [dict(item) for item in context.obligations]
        selected = list(context.selected)
    else:
        payloads = dict(context.accepted_payloads) or _load_accepted_payloads(
            context.artifacts_dir
        )
        obligations = [dict(item) for item in context.obligations] or (
            _load_host_obligations(context.artifacts_dir)
        )
        selected = list(context.selected)
    request: dict[str, Any] = {
        "schema_version": FINALIZER_WIRE_SCHEMA_VERSION,
        "operation": operation,
        "provider_ref": instance.provider_ref,
        "instance_id": instance.instance_id,
        "plan_digest": context.plan_digest,
        "run_id": context.run_id,
        "agent_id": context.agent_id,
        "turn_nonce": context.turn_nonce,
        "context_digest": context.context_digest,
        "config": dict(instance.config),
        "selected": selected,
    }
    if instance.instance_id in payloads:
        request["payload"] = payloads[instance.instance_id]
    if obligations:
        request["obligations"] = obligations
    return request


def _load_accepted_payloads(artifacts_dir: str | None) -> dict[str, Any]:
    if not artifacts_dir:
        return {}
    from sase.finalizers.declaration import FINAL_SUBMISSION_FILENAME

    try:
        payload = json.loads(
            (Path(artifacts_dir) / FINAL_SUBMISSION_FILENAME).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    submission = payload.get("submission")
    if not isinstance(submission, Mapping):
        return {}
    raw_payloads = submission.get("payloads")
    if not isinstance(raw_payloads, list):
        return {}
    accepted: dict[str, Any] = {}
    for item in raw_payloads:
        if not isinstance(item, Mapping):
            continue
        instance_id = item.get("instance_id")
        if isinstance(instance_id, str) and "payload" in item:
            accepted[instance_id] = item.get("payload")
    return accepted


def _load_host_obligations(artifacts_dir: str | None) -> list[dict[str, Any]]:
    if not artifacts_dir:
        return []
    from sase.finalizers.declaration import FINAL_CONTEXT_FILENAME

    try:
        payload = json.loads(
            (Path(artifacts_dir) / FINAL_CONTEXT_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, Mapping):
        return []
    context = payload.get("context")
    if not isinstance(context, Mapping):
        return []
    obligations = context.get("obligations")
    if not isinstance(obligations, list):
        return []
    loaded: list[dict[str, Any]] = []
    for item in obligations:
        if isinstance(item, dict):
            loaded.append(item)
    return loaded


def _validate_provider_result(
    instance: ConfiguredFinalizerInstance,
    operation: str,
    result: Mapping[str, Any],
) -> None:
    unknown = sorted(set(result) - _PROVIDER_RESULT_KEYS)
    if unknown:
        raise FinalizerExecutionError(
            f"provider operation {operation!r} returned unknown field(s): "
            + ", ".join(unknown)
        )
    if result.get("schema_version") != FINALIZER_WIRE_SCHEMA_VERSION:
        raise FinalizerExecutionError(
            f"provider operation {operation!r} returned unsupported schema "
            f"{result.get('schema_version')!r}"
        )
    if result.get("operation") != operation:
        raise FinalizerExecutionError(
            f"provider operation {operation!r} returned operation "
            f"{result.get('operation')!r}"
        )
    result_provider_ref = result.get("provider_ref")
    if not isinstance(result_provider_ref, str) or provider_ref_key(
        result_provider_ref
    ) != provider_ref_key(instance.provider_ref):
        raise FinalizerExecutionError(
            f"provider operation {operation!r} returned provider "
            f"{result.get('provider_ref')!r}"
        )
    if result.get("instance_id") != instance.instance_id:
        raise FinalizerExecutionError(
            f"provider operation {operation!r} returned instance "
            f"{result.get('instance_id')!r}"
        )
    status = result.get("status")
    allowed = (
        _EXECUTE_STATUSES if operation == "execute" else _NON_EXECUTE_SUCCESS_STATUSES
    )
    if status not in allowed:
        raise FinalizerExecutionError(
            f"provider operation {operation!r} returned status {status!r}"
        )


def _provider_evidence(
    result: Mapping[str, Any],
) -> list[FinalizerOutcomeEvidenceWire]:
    raw = result.get("evidence")
    if not isinstance(raw, list):
        return []
    evidence: list[FinalizerOutcomeEvidenceWire] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("kind")
        value = item.get("value")
        if isinstance(kind, str) and isinstance(value, str):
            evidence.append(FinalizerOutcomeEvidenceWire(kind=kind, value=value))
    return evidence


def _provider_diagnostics(
    instance: ConfiguredFinalizerInstance,
    result: Mapping[str, Any],
    *,
    attempt: int | None = None,
) -> list[FinalizerDiagnosticWire]:
    raw = result.get("diagnostics")
    if not isinstance(raw, list):
        return []
    diagnostics: list[FinalizerDiagnosticWire] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        code = item.get("code")
        severity = item.get("severity")
        message = item.get("message")
        if (
            isinstance(code, str)
            and isinstance(severity, str)
            and isinstance(message, str)
        ):
            diagnostics.append(
                FinalizerDiagnosticWire(
                    code=code,
                    severity=severity,
                    message=message,
                    instance_id=instance.instance_id,
                    attempt=attempt,
                )
            )
    return diagnostics


def _failed_result(
    instance_id: str,
    code: str,
    message: str,
    *,
    attempt: int = 1,
) -> FinalizerInstanceResultWire:
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="failed",
        attempts=[
            FinalizerAttemptWire(
                attempt=attempt,
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
                attempt=attempt,
            )
        ],
    )


def _sanitized_env(allowlist: Sequence[str]) -> dict[str, str]:
    allowed = set(_BASE_ENV_KEYS)
    allowed.update(allowlist)
    env = {key: os.environ[key] for key in sorted(allowed) if key in os.environ}
    env["SASE_FINALIZER_SUBPROCESS"] = "1"
    return env


def _allowed_env_names(config: Mapping[str, Any]) -> tuple[str, ...]:
    value = config.get("env")
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _resolve_cwd(command_config: CommandFinalizerConfig) -> str:
    if command_config.cwd == "primary":
        return resolve_finalizer_project_dir()
    raise FinalizerExecutionError(f"unsupported cwd policy {command_config.cwd!r}")


__all__ = [
    "FinalizerExecutionContext",
    "FinalizerExecutionError",
    "execute_command_finalizer",
    "execute_non_commit_finalizer",
    "execute_plugin_finalizer",
    "result_to_json",
    "run_provider_operation",
    "validate_external_declaration_payload",
]
