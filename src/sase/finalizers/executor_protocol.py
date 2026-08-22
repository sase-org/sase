"""Request and result translation for external finalizer providers."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerDiagnosticWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.config import ConfiguredFinalizerInstance, FinalizerConfig
from sase.finalizers.executor_support import (
    FinalizerExecutionContext,
    FinalizerExecutionError,
)
from sase.finalizers.providers import provider_ref_key


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


def provider_request(
    instance: ConfiguredFinalizerInstance,
    config: FinalizerConfig,
    context: FinalizerExecutionContext,
    operation: str,
) -> dict[str, Any]:
    """Build a provider request from sealed or persisted host context."""

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


def validate_provider_result(
    instance: ConfiguredFinalizerInstance,
    operation: str,
    result: Mapping[str, Any],
) -> None:
    """Validate the host-owned envelope returned by a provider operation."""

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


def provider_evidence(
    result: Mapping[str, Any],
) -> list[FinalizerOutcomeEvidenceWire]:
    """Translate valid provider evidence into host wire objects."""

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


def provider_diagnostics(
    instance: ConfiguredFinalizerInstance,
    result: Mapping[str, Any],
    *,
    attempt: int | None = None,
) -> list[FinalizerDiagnosticWire]:
    """Translate valid provider diagnostics into host wire objects."""

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
