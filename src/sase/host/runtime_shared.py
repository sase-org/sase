"""Shared primitives for the provider host runtime."""

from __future__ import annotations

import contextlib
import io
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sase.host.manifest import effective_timeout_ms
from sase.host.wire import (
    HostLogRecordWire,
    HostRequestEnvelopeWire,
    HostSideEffectIntentWire,
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
class RuntimeLogBuffer:
    max_bytes: int
    records: list[HostLogRecordWire]
    used_bytes: int = 0
    truncated: bool = False

    @classmethod
    def create(cls, max_bytes: int) -> RuntimeLogBuffer:
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
class OperationContext:
    request: HostRequestEnvelopeWire
    logs: RuntimeLogBuffer
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


@dataclass(frozen=True)
class OperationResult:
    result: Mapping[str, Any]
    side_effects: tuple[HostSideEffectIntentWire, ...] = ()
    spawned_processes: int = 0
    network_requests: int = 0


OperationHandler = Callable[[OperationContext], Mapping[str, Any] | OperationResult]


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


def require_capability(context: OperationContext, capability: str) -> None:
    if capability in context.request.declared_capabilities:
        return
    raise ProviderHostRuntimeError(
        "capability_denied",
        f"host operation requires declared capability {capability}",
        target="declared_capabilities",
    )


def payload_str(
    payload: Mapping[str, Any],
    key: str,
    *,
    field_name: str | None = None,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        target = field_name or key
        raise ProviderHostRuntimeError(
            "host_protocol_error",
            f"{target} must be a non-empty string",
            target=f"payload.{target}",
        )
    return value


def optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ProviderHostRuntimeError(
            "host_protocol_error",
            f"payload.{key} must be a non-empty string",
            target=f"payload.{key}",
        )
    return value


def optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


@contextlib.contextmanager
def temporary_environ(values: Mapping[str, str]) -> Any:
    if not values:
        yield
        return
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


@contextlib.contextmanager
def temporary_cwd(cwd: str | None) -> Any:
    if not cwd:
        yield
        return
    previous = os.getcwd()
    os.chdir(cwd)
    try:
        yield
    finally:
        os.chdir(previous)


def append_captured_process_logs(
    context: OperationContext,
    stdout_buffer: io.StringIO,
    stderr_buffer: io.StringIO,
) -> None:
    stdout = stdout_buffer.getvalue()
    if stdout:
        context.logs.append("info", stdout, target="sase.host.process", stream="stdout")
    stderr = stderr_buffer.getvalue()
    if stderr:
        context.logs.append("warn", stderr, target="sase.host.process", stream="stderr")
