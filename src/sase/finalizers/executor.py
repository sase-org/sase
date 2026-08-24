"""Public facade for bounded finalizer execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerContextWire,
    FinalizerInstanceResultWire,
    finalizer_wire_to_json_dict,
)
from sase.finalizers.config import ConfiguredFinalizerInstance, FinalizerConfig
from sase.finalizers.executor_command import (
    execute_command_finalizer as _execute_command_finalizer,
)
from sase.finalizers.executor_plugin import (
    execute_plugin_finalizer as _execute_plugin_finalizer,
)
from sase.finalizers.executor_plugin import (
    run_provider_operation as _run_provider_operation,
)
from sase.finalizers.executor_protocol import (
    provider_request as _provider_request,
    validate_provider_result as _validate_provider_result,
)
from sase.finalizers.executor_support import (
    FinalizerExecutionContext,
    FinalizerExecutionError,
    ProviderOperationRunner,
    failed_result as _failed_result,
)
from sase.finalizers.ledger import InstanceLedger
from sase.finalizers.plan import authenticate_resolved_finalizer_plan_full
from sase.finalizers.providers import (
    BUILTIN_COMMAND_PROVIDER_REF,
    BUILTIN_COMMIT_PROVIDER_REF,
    FinalizerProviderRecord,
    collect_finalizer_providers,
    provider_records_by_ref,
    provider_ref_key,
)


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

    return _execute_command_finalizer(instance, context, ledger=ledger)


def execute_plugin_finalizer(
    instance: ConfiguredFinalizerInstance,
    config: FinalizerConfig,
    context: FinalizerExecutionContext,
    *,
    operation_runner: ProviderOperationRunner,
    ledger: InstanceLedger | None = None,
) -> FinalizerInstanceResultWire:
    """Execute an external finalizer through the isolated worker protocol."""

    provider = _resolve_provider(instance.provider_ref)
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
    return _execute_plugin_finalizer(
        instance,
        config,
        context,
        provider,
        operation_runner=operation_runner,
        ledger=ledger,
    )


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
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    config = authenticate_resolved_finalizer_plan_full(artifacts_dir).config
    instance = config.instances.get(instance_id)
    if instance is None or provider_ref_key(instance.provider_ref) != provider_ref_key(
        provider_ref
    ):
        raise FinalizerExecutionError(f"unknown finalizer instance {instance_id!r}")
    exec_context = FinalizerExecutionContext(
        artifacts_dir=artifacts_dir,
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
    provider = _resolve_provider(provider_ref)
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

    return _run_provider_operation(instance, provider, operation, request, context)


def result_to_json(result: FinalizerInstanceResultWire) -> dict[str, Any]:
    """Project an instance result wire object to JSON."""

    return finalizer_wire_to_json_dict(result)


def _resolve_provider(provider_ref: str) -> FinalizerProviderRecord | None:
    providers = collect_finalizer_providers()
    return provider_records_by_ref(providers).get(provider_ref_key(provider_ref))


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
