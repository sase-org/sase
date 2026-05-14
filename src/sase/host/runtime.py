"""Subprocess runtime for provider/plugin host IPC.

This module intentionally exposes only fake/no-op operations plus host
manifest/resource diagnostics. Real provider routing lands in later phases.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import json
import logging
import os
import re
import signal
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TextIO

from sase.host.manifest import (
    HostPolicyError,
    discover_host_manifests,
    effective_timeout_ms,
    resource_policy_diagnostics,
    validate_manifest_for_request,
)
from sase.host.wire import (
    HOST_ERROR_CODES,
    HOST_OPERATION_FAMILIES,
    PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
    HostErrorWire,
    HostFallbackWire,
    HostLogRecordWire,
    HostRequestEnvelopeWire,
    HostResourceUsageWire,
    HostResponseEnvelopeWire,
    host_request_from_dict,
    host_wire_to_json_dict,
)

DEFAULT_HOST_TIMEOUT_MS = 30_000
MAX_HOST_LOG_BYTES = 64 * 1024
MAX_FRAME_BYTES = 1024 * 1024
_REDACTED = "[REDACTED]"
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)=([^\s&]+)"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
)


class ProviderHostRuntimeError(Exception):
    """Base class for typed host runtime failures."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        target: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.target = target
        self.details = details


@dataclass(frozen=True)
class ProviderHostRuntimeConfig:
    max_log_bytes: int = MAX_HOST_LOG_BYTES
    default_timeout_ms: int = DEFAULT_HOST_TIMEOUT_MS


@dataclass
class _RuntimeLogBuffer:
    max_bytes: int
    records: list[HostLogRecordWire]
    used_bytes: int = 0
    truncated: bool = False

    @classmethod
    def create(cls, max_bytes: int) -> _RuntimeLogBuffer:
        return cls(max_bytes=max_bytes, records=[])

    def append(
        self,
        level: str,
        message: str,
        *,
        target: str | None = None,
        stream: str | None = None,
    ) -> None:
        message = redact_host_log(message)
        encoded_len = len(message.encode("utf-8", errors="replace"))
        if self.used_bytes + encoded_len > self.max_bytes:
            if not self.truncated:
                self.records.append(
                    HostLogRecordWire(
                        level="warn",
                        message="host log capture truncated",
                        target="sase.host.runtime",
                    )
                )
                self.truncated = True
            return
        self.used_bytes += encoded_len
        self.records.append(
            HostLogRecordWire(
                level=level,
                message=message,
                target=target,
                stream=stream,
            )
        )


@dataclass
class _OperationContext:
    request: HostRequestEnvelopeWire
    logs: _RuntimeLogBuffer
    started_monotonic: float
    config: ProviderHostRuntimeConfig

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_monotonic) * 1000)

    def check_deadline(self) -> None:
        timeout_ms = effective_timeout_ms(
            self.request, default_timeout_ms=self.config.default_timeout_ms
        )
        if self.elapsed_ms() > timeout_ms:
            raise ProviderHostRuntimeError(
                "host_timeout",
                f"host operation exceeded timeout of {timeout_ms}ms",
                retryable=True,
                target=self.request.request_id,
            )


OperationHandler = Callable[[_OperationContext], Mapping[str, Any]]


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
    """Dispatch fake Phase 8C operations for one host process."""

    def __init__(self, config: ProviderHostRuntimeConfig) -> None:
        self._config = config
        self._handlers: dict[tuple[str, str], OperationHandler] = {
            ("config", "fake.echo"): self._fake_echo,
            ("config", "fake.log"): self._fake_log,
            ("config", "fake.sleep"): self._fake_sleep,
            ("config", "fake.stderr"): self._fake_stderr,
            ("config", "host.discover_plugins"): self._discover_plugins,
        }

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
        logs = _RuntimeLogBuffer.create(self._config.max_log_bytes)
        context = _OperationContext(request, logs, started, self._config)
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
            result = dict(handler(context))
            context.check_deadline()
            duration_ms = context.elapsed_ms()
            return HostResponseEnvelopeWire(
                schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
                request_id=request.request_id,
                status="ok",
                result=result,
                logs=tuple(logs.records),
                duration_ms=duration_ms,
                resource_usage=HostResourceUsageWire(
                    wall_ms=duration_ms,
                    spawned_processes=0,
                    network_requests=0,
                ),
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
        logs: _RuntimeLogBuffer | None = None,
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

    def _fake_echo(self, context: _OperationContext) -> Mapping[str, Any]:
        context.logs.append(
            "info", "fake echo operation dispatched", target="sase.host"
        )
        return {
            "echo": dict(context.request.payload),
            "operation": context.request.operation.operation,
            "request_id": context.request.request_id,
        }

    def _fake_log(self, context: _OperationContext) -> Mapping[str, Any]:
        message = str(context.request.payload.get("message", "fake log"))
        context.logs.append("info", message, target="sase.host.fake")
        return {"logged": True}

    def _fake_stderr(self, context: _OperationContext) -> Mapping[str, Any]:
        message = str(context.request.payload.get("message", "fake stderr"))
        context.logs.append("warn", message, target="sase.host.fake", stream="stderr")
        print(redact_host_log(message), file=sys.stderr, flush=True)
        return {"stderr": True}

    def _fake_sleep(self, context: _OperationContext) -> Mapping[str, Any]:
        sleep_ms = int(context.request.payload.get("sleep_ms", 0))
        if sleep_ms < 0:
            raise ProviderHostRuntimeError(
                "host_protocol_error",
                "sleep_ms must be non-negative",
                target="payload.sleep_ms",
            )
        context.logs.append(
            "info", f"sleeping for {sleep_ms}ms", target="sase.host.fake"
        )
        deadline_ms = (
            context.request.deadline.timeout_ms or self._config.default_timeout_ms
        )
        if sleep_ms > deadline_ms:
            time.sleep(deadline_ms / 1000)
            raise ProviderHostRuntimeError(
                "host_timeout",
                f"fake sleep exceeded timeout of {deadline_ms}ms",
                retryable=True,
                target=context.request.request_id,
            )
        time.sleep(sleep_ms / 1000)
        return {"slept_ms": sleep_ms}

    def _discover_plugins(self, context: _OperationContext) -> Mapping[str, Any]:
        groups = (
            "sase_llm",
            "sase_vcs",
            "sase_workspace",
            "sase_config",
            "sase_xprompts",
        )
        discovered: dict[str, list[dict[str, str]]] = {}
        entry_points = importlib.metadata.entry_points()
        for group in groups:
            discovered[group] = [
                {"name": ep.name, "value": ep.value}
                for ep in sorted(
                    entry_points.select(group=group), key=lambda item: item.name
                )
            ]
        discovery = discover_host_manifests(
            entry_points={
                group: tuple(item["name"] for item in items)
                for group, items in discovered.items()
            }
        )
        context.logs.append(
            "info",
            "plugin entry points and host manifests discovered",
            target="sase.host",
        )
        return {
            "entry_points": discovered,
            "manifests": [
                {
                    "plugin_id": record.manifest.plugin_id,
                    "operation_families": list(record.manifest.operation_families),
                    "network_mode": record.manifest.network.mode,
                    "compatibility_mode": record.compatibility_mode,
                    "source": record.source,
                    "daemon_authoritative": record.daemon_authoritative,
                }
                for record in discovery.records
            ],
            "manifest_diagnostics": list(discovery.diagnostics),
            "resource_policy": resource_policy_diagnostics(),
        }


def redact_host_log(message: str) -> str:
    redacted = message
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.lower().startswith("(?i)(bearer"):
            redacted = pattern.sub(r"\1" + _REDACTED, redacted)
        else:
            redacted = pattern.sub(r"\1=" + _REDACTED, redacted)
    for key, value in os.environ.items():
        lowered = key.lower()
        if any(part in lowered for part in ("token", "secret", "password", "api_key")):
            if value:
                redacted = redacted.replace(value, _REDACTED)
    return redacted


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
