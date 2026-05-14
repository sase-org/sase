"""Subprocess runtime for provider/plugin host IPC."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import sys
import time
from typing import TextIO

from sase.host.manifest import HostPolicyError, validate_manifest_for_request
from sase.host.runtime_handlers import runtime_handlers
from sase.host.runtime_shared import (
    DEFAULT_HOST_TIMEOUT_MS,
    MAX_FRAME_BYTES,
    MAX_HOST_LOG_BYTES,
    OperationHandler,
    OperationContext,
    OperationResult,
    ProviderHostRuntimeConfig,
    ProviderHostRuntimeError,
    RuntimeLogBuffer,
    redact_host_log,
)
from sase.host.wire import (
    HOST_ERROR_CODES,
    HOST_OPERATION_FAMILIES,
    PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
    HostErrorWire,
    HostFallbackWire,
    HostRequestEnvelopeWire,
    HostResourceUsageWire,
    HostResponseEnvelopeWire,
    host_request_from_dict,
    host_wire_to_json_dict,
)


def run_provider_host_stdio(
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    config: ProviderHostRuntimeConfig | None = None,
) -> int:
    """Run the framed JSON host loop over newline-delimited stdio."""

    runtime = ProviderHostRuntime(config or ProviderHostRuntimeConfig())
    in_stream = stdin or sys.stdin
    out_stream = stdout or sys.stdout
    err_stream = stderr or sys.stderr
    for raw_line in in_stream:
        if len(raw_line.encode("utf-8", errors="replace")) > MAX_FRAME_BYTES:
            response = runtime.protocol_error(
                "unknown",
                "host request frame exceeds maximum size",
                target="frame",
            )
        else:
            response = runtime.handle_json_frame(raw_line)
        out_stream.write(
            json.dumps(host_wire_to_json_dict(response), separators=(",", ":"))
        )
        out_stream.write("\n")
        out_stream.flush()
        print(
            f"provider host handled request_id={response.request_id} status={response.status}",
            file=err_stream,
            flush=True,
        )
    return 0


class ProviderHostRuntime:
    """Dispatch host operations for one provider host process."""

    def __init__(self, config: ProviderHostRuntimeConfig) -> None:
        self._config = config
        self._handlers: dict[tuple[str, str], OperationHandler] = runtime_handlers()

    def handle_json_frame(self, raw_frame: str) -> HostResponseEnvelopeWire:
        started = time.monotonic()
        request_id = "unknown"
        try:
            raw_payload = json.loads(raw_frame)
            request = host_request_from_dict(dict(raw_payload))
            request_id = request.request_id
            return self.handle_request(request, started=started)
        except ProviderHostRuntimeError as exc:
            return self._error_response(request_id, exc, started)
        except Exception as exc:
            return self.protocol_error(request_id, str(exc), started=started)

    def handle_request(
        self, request: HostRequestEnvelopeWire, *, started: float | None = None
    ) -> HostResponseEnvelopeWire:
        started = started or time.monotonic()
        logs = RuntimeLogBuffer.create(self._config.max_log_bytes)
        context = OperationContext(request, logs, started, self._config)
        try:
            self._validate_request(request)
            handler = self._handlers.get(
                (request.operation.family, request.operation.operation)
            )
            if handler is None:
                raise ProviderHostRuntimeError(
                    "operation_unsupported",
                    (
                        "host operation is not allowlisted in Phase 8C: "
                        f"{request.operation.family}.{request.operation.operation}"
                    ),
                    target="operation",
                )
            old_active = os.environ.get("SASE_PROVIDER_HOST_ACTIVE")
            os.environ["SASE_PROVIDER_HOST_ACTIVE"] = "1"
            try:
                raw_result = handler(context)
            finally:
                if old_active is None:
                    os.environ.pop("SASE_PROVIDER_HOST_ACTIVE", None)
                else:
                    os.environ["SASE_PROVIDER_HOST_ACTIVE"] = old_active
            operation_result = (
                raw_result
                if isinstance(raw_result, OperationResult)
                else OperationResult(result=dict(raw_result))
            )
            context.check_deadline()
            duration_ms = context.elapsed_ms()
            return HostResponseEnvelopeWire(
                schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
                request_id=request.request_id,
                status="ok",
                result=dict(operation_result.result),
                logs=tuple(logs.records),
                duration_ms=duration_ms,
                resource_usage=HostResourceUsageWire(
                    wall_ms=duration_ms,
                    spawned_processes=operation_result.spawned_processes,
                    network_requests=operation_result.network_requests,
                ),
                side_effects=operation_result.side_effects,
            )
        except ProviderHostRuntimeError as exc:
            return self._error_response(request.request_id, exc, started, logs=logs)
        except HostPolicyError as exc:
            return self._error_response(
                request.request_id,
                ProviderHostRuntimeError(
                    exc.code,
                    exc.message,
                    target=exc.target,
                    details=exc.details,
                ),
                started,
                logs=logs,
            )

    def protocol_error(
        self,
        request_id: str,
        message: str,
        *,
        target: str | None = None,
        started: float | None = None,
    ) -> HostResponseEnvelopeWire:
        return self._error_response(
            request_id,
            ProviderHostRuntimeError(
                "host_protocol_error", message, target=target, retryable=False
            ),
            started or time.monotonic(),
        )

    def _validate_request(self, request: HostRequestEnvelopeWire) -> None:
        if request.schema_version != PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION:
            raise ProviderHostRuntimeError(
                "host_protocol_error",
                "host request schema mismatch",
                target="schema_version",
            )
        if request.operation.family not in HOST_OPERATION_FAMILIES:
            raise ProviderHostRuntimeError(
                "operation_unsupported",
                f"unsupported host operation family: {request.operation.family}",
                target="operation.family",
            )
        if not request.request_id.strip():
            raise ProviderHostRuntimeError(
                "host_protocol_error",
                "host request_id must not be empty",
                target="request_id",
            )
        validate_manifest_for_request(request)

    def _error_response(
        self,
        request_id: str,
        error: ProviderHostRuntimeError,
        started: float,
        *,
        logs: RuntimeLogBuffer | None = None,
    ) -> HostResponseEnvelopeWire:
        code = error.code if error.code in HOST_ERROR_CODES else "host_protocol_error"
        duration_ms = int((time.monotonic() - started) * 1000)
        return HostResponseEnvelopeWire(
            schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
            request_id=request_id,
            status="error" if code != "host_cancelled" else "cancelled",
            error=HostErrorWire(
                schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
                code=code,
                message=redact_host_log(error.message),
                retryable=error.retryable,
                target=error.target,
                details=error.details,
                fallback=HostFallbackWire(
                    available=True,
                    reason="direct_python_provider_path",
                    message="real provider routing is disabled for Phase 8C",
                ),
            ),
            logs=tuple(logs.records) if logs is not None else (),
            duration_ms=duration_ms,
            resource_usage=HostResourceUsageWire(
                wall_ms=duration_ms,
                spawned_processes=0,
                network_requests=0,
            ),
        )


def _install_host_signal_handlers() -> None:
    """Turn SIGTERM/SIGINT into ordinary process termination."""

    def _terminate(_signum: int, _frame: object) -> None:
        raise SystemExit(128 + signal.SIGTERM)

    with contextlib.suppress(ValueError):
        signal.signal(signal.SIGTERM, _terminate)
        signal.signal(signal.SIGINT, _terminate)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    _install_host_signal_handlers()
    return run_provider_host_stdio()


__all__ = [
    "DEFAULT_HOST_TIMEOUT_MS",
    "MAX_HOST_LOG_BYTES",
    "ProviderHostRuntime",
    "ProviderHostRuntimeConfig",
    "ProviderHostRuntimeError",
    "main",
    "redact_host_log",
    "run_provider_host_stdio",
]
