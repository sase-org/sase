"""Subprocess runtime for isolated third-party dispatch providers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import os
import sys
from typing import Any

from sase.finalizers.bounded_subprocess import (
    HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS,
    STDOUT_CAP_BYTES,
    run_bounded_subprocess,
)
from sase.plugins.qualified_id import (
    PluginQualifiedIdError,
    canonical_plugin_qualified_id,
)

from .models import MachineRecord
from .provider_protocol import DISPATCH_PROVIDER_PROTOCOL_VERSION

PROVIDER_OPERATION_TIMEOUT_SECONDS = 30.0
BASE_PROVIDER_ENV_KEYS = (
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
PROVIDER_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "operation",
        "provider_ref",
        "status",
        "diagnostics",
        "specs",
        "candidates",
        "plan",
    }
)


@dataclass(frozen=True)
class DispatchProviderRecord:
    """Metadata-only dispatch provider record."""

    provider_ref: str
    provider_id: str
    package: str
    version: str
    entry_point: str | None
    builtin: bool
    disabled_by: tuple[str, ...] = ()


class DispatchProviderExecutionError(RuntimeError):
    """Raised when an isolated dispatch provider operation fails."""


DispatchProviderOperationRunner = Callable[
    [DispatchProviderRecord, str, Mapping[str, Any], float],
    Mapping[str, Any],
]


def run_dispatch_provider_operation(
    provider: DispatchProviderRecord,
    operation: str,
    request: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    """Run one external dispatch provider operation in a bounded subprocess."""

    argv = [
        sys.executable,
        "-m",
        "sase.dispatch.worker_entry",
        "--provider-ref",
        provider.provider_ref,
        "--operation",
        operation,
    ]
    try:
        payload = json.dumps(dict(request), sort_keys=True).encode("utf-8")
    except Exception as exc:
        raise DispatchProviderExecutionError(
            f"dispatch provider request is not JSON-serializable: {exc}"
        ) from exc
    if len(payload) > STDOUT_CAP_BYTES:
        raise DispatchProviderExecutionError("dispatch provider request exceeded cap")
    timeout = min(
        timeout_seconds,
        PROVIDER_OPERATION_TIMEOUT_SECONDS,
        HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS,
    )
    try:
        completed = run_bounded_subprocess(
            argv,
            cwd=os.getcwd(),
            env=_sanitized_provider_env(request.get("config")),
            input_bytes=payload,
            timeout=timeout,
        )
    except Exception as exc:
        raise DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} could not start: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if completed.timed_out:
        raise DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} timed out after {timeout:g}s"
        )
    if completed.stdout_truncated or completed.stderr_truncated:
        raise DispatchProviderExecutionError(
            "dispatch provider operation exceeded output cap"
        )
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except Exception as exc:
        raise DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} emitted malformed JSON: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(result, Mapping):
        raise DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} must return a JSON object"
        )
    if completed.returncode != 0 and result.get("status") != "failed":
        raise DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} exited with "
            f"{completed.returncode}"
        )
    return result


def validate_provider_result(
    provider: DispatchProviderRecord,
    operation: str,
    result: Mapping[str, Any],
) -> None:
    unknown = sorted(set(result) - PROVIDER_RESULT_KEYS)
    if unknown:
        raise DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} returned unknown field(s): "
            + ", ".join(unknown)
        )
    if result.get("schema_version") != DISPATCH_PROVIDER_PROTOCOL_VERSION:
        raise DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} returned unsupported schema "
            f"{result.get('schema_version')!r}"
        )
    if result.get("operation") != operation:
        raise DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} returned operation "
            f"{result.get('operation')!r}"
        )
    result_provider_ref = result.get("provider_ref")
    if not isinstance(result_provider_ref, str) or provider_ref_key(
        result_provider_ref
    ) != provider_ref_key(provider.provider_ref):
        raise DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} returned provider "
            f"{result.get('provider_ref')!r}"
        )
    status = result.get("status")
    if status not in {"ok", "failed"}:
        raise DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} returned status {status!r}"
        )


def provider_error_message(result: Mapping[str, Any], fallback: str) -> str:
    raw = result.get("diagnostics")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return fallback
    messages = [
        str(item.get("message"))
        for item in raw
        if isinstance(item, Mapping) and isinstance(item.get("message"), str)
    ]
    return messages[0] if messages else fallback


def machine_payload(machine: MachineRecord) -> dict[str, object]:
    return {
        "alias": machine.alias,
        "provider_ref": machine.provider_ref,
        "endpoint": machine.endpoint,
        "credential_ref": machine.credential_ref,
        "pinned_installation_id": machine.pinned_installation_id,
        "connection_kind": machine.connection_kind,
        "tls": machine.tls.to_plan(),
        "quarantined": machine.quarantined,
        "quarantine_reason": machine.quarantine_reason,
    }


def _sanitized_provider_env(config: object) -> dict[str, str]:
    allowed = set(BASE_PROVIDER_ENV_KEYS)
    if isinstance(config, Mapping):
        env_names = config.get("env")
        if isinstance(env_names, Sequence) and not isinstance(
            env_names, (str, bytes, bytearray)
        ):
            allowed.update(item for item in env_names if isinstance(item, str))
    env = {key: os.environ[key] for key in sorted(allowed) if key in os.environ}
    env["SASE_DISPATCH_PROVIDER_SUBPROCESS"] = "1"
    return env


def provider_ref_key(value: str) -> str:
    """Return a canonical lookup key for syntactically valid provider refs."""

    try:
        return canonical_plugin_qualified_id(value)
    except PluginQualifiedIdError:
        return value


__all__ = [
    "DispatchProviderExecutionError",
    "DispatchProviderOperationRunner",
    "DispatchProviderRecord",
    "machine_payload",
    "provider_error_message",
    "provider_ref_key",
    "run_dispatch_provider_operation",
    "validate_provider_result",
]
