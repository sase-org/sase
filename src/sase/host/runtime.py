"""Subprocess runtime for provider/plugin host IPC.

This module exposes fake/no-op operations, host manifest/resource diagnostics,
and the first read-only provider metadata/catalog operations routed in Phase 8E.
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
from dataclasses import asdict, dataclass
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
    HOST_CAP_LLM_METADATA,
    HOST_CAP_XPROMPT_CATALOG,
    HOST_OPERATION_FAMILIES,
    PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
    HostErrorWire,
    HostFallbackWire,
    HostLogRecordWire,
    HostRequestEnvelopeWire,
    HostResourceUsageWire,
    HostResponseEnvelopeWire,
    HostSideEffectIntentWire,
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


@dataclass(frozen=True)
class _OperationResult:
    result: Mapping[str, Any]
    side_effects: tuple[HostSideEffectIntentWire, ...] = ()
    spawned_processes: int = 0
    network_requests: int = 0


OperationHandler = Callable[[_OperationContext], Mapping[str, Any] | _OperationResult]


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
            ("llm", "llm.metadata"): self._llm_metadata,
            ("xprompt", "xprompt.catalog"): self._xprompt_catalog,
            ("vcs", "vcs.query"): self._vcs_query,
            ("vcs", "vcs.mutation"): self._vcs_mutation_shadow,
            ("workspace", "workspace.metadata"): self._workspace_metadata,
            ("workspace", "workspace.resolve_ref"): self._workspace_resolve_ref,
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
                if isinstance(raw_result, _OperationResult)
                else _OperationResult(result=dict(raw_result))
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

    def _llm_metadata(self, context: _OperationContext) -> Mapping[str, Any]:
        _require_capability(context, HOST_CAP_LLM_METADATA)
        from sase.llm_provider.registry import direct_llm_metadata_payload

        context.logs.append("info", "LLM metadata collected", target="sase.host.llm")
        return direct_llm_metadata_payload()

    def _xprompt_catalog(self, context: _OperationContext) -> Mapping[str, Any]:
        _require_capability(context, HOST_CAP_XPROMPT_CATALOG)
        payload = context.request.payload
        include_pdf = bool(payload.get("include_pdf", False))
        if include_pdf:
            raise ProviderHostRuntimeError(
                "operation_unsupported",
                "host-routed xprompt.catalog is read-only and does not generate PDFs",
                target="payload.include_pdf",
            )

        from sase.xprompt._catalog_structured import (
            build_structured_xprompts_catalog,
        )

        projection = build_structured_xprompts_catalog(
            project=_optional_str(payload.get("project")),
            source=_optional_str(payload.get("source")),
            tag=_optional_str(payload.get("tag")),
            query=_optional_str(payload.get("query")),
            include_pdf=False,
            limit=_optional_int(payload.get("limit")),
        )
        context.logs.append(
            "info", "xprompt catalog collected", target="sase.host.xprompt"
        )
        return {
            "projection": asdict(projection),
            "cache_invalidation": _xprompt_catalog_cache_policy(),
        }

    def _vcs_query(self, context: _OperationContext) -> _OperationResult:
        from sase.vcs_provider import (
            detect_vcs_direct,
            detect_vcs_family_direct,
            get_vcs_provider,
        )

        payload = dict(context.request.payload)
        query = str(payload.get("query", ""))
        cwd = _payload_str(payload, "cwd")
        context.logs.append(
            "info", f"vcs query dispatched: {query}", target="sase.host.vcs"
        )
        if query == "detect_vcs":
            value = detect_vcs_direct(cwd)
        elif query == "detect_vcs_family":
            value = detect_vcs_family_direct(cwd)
        else:
            provider = get_vcs_provider(cwd)
            value = _call_vcs_query(provider, query, payload, cwd)
        return _OperationResult(
            result={"query": query, "value": value},
            spawned_processes=1,
            network_requests=_network_request_count(context.request),
        )

    def _vcs_mutation_shadow(self, context: _OperationContext) -> _OperationResult:
        payload = dict(context.request.payload)
        provider = str(payload.get("provider") or "unknown")
        operation = str(payload.get("operation") or "")
        cwd = _payload_str(payload, "cwd", field_name="workspace_dir")
        if not operation:
            raise ProviderHostRuntimeError(
                "host_protocol_error",
                "vcs mutation payload must include operation",
                target="payload.operation",
            )
        context.logs.append(
            "warn",
            f"vcs mutation shadow-routed only: {provider}.{operation}",
            target="sase.host.vcs",
        )
        return _OperationResult(
            result={"shadow": True, "provider": provider, "operation": operation},
            side_effects=(
                HostSideEffectIntentWire(
                    type="vcs_mutation",
                    data={
                        "provider": provider,
                        "operation": operation,
                        "workspace_dir": cwd,
                    },
                ),
            ),
        )

    def _workspace_metadata(self, context: _OperationContext) -> Mapping[str, Any]:
        from dataclasses import asdict, is_dataclass

        import sase.workspace_provider as workspace_registry

        payload = dict(context.request.payload)
        query = str(payload.get("query", ""))
        context.logs.append(
            "info",
            f"workspace metadata query dispatched: {query}",
            target="sase.host.workspace",
        )
        value: Any
        if query == "workflow_metadata":
            value = [
                asdict(item) if is_dataclass(item) else dict(item)
                for item in workspace_registry.get_all_workflow_metadata()
            ]
        elif query == "workflow_names":
            value = sorted(workspace_registry.get_workflow_names())
        elif query == "detect_workflow_type":
            value = workspace_registry.detect_workflow_type_direct(
                _payload_str(payload, "project_file")
            )
        elif query == "get_change_label":
            value = workspace_registry.get_change_label_direct(
                _payload_str(payload, "project_file")
            )
        elif query == "get_display_name":
            value = workspace_registry.get_display_name(
                _payload_str(payload, "workflow_type")
            )
        elif query == "get_display_name_by_vcs":
            value = workspace_registry.get_display_name_by_vcs(
                _payload_str(payload, "vcs_name")
            )
        elif query == "get_display_name_by_vcs_family":
            value = workspace_registry.get_display_name_by_vcs_family(
                _payload_str(payload, "vcs_family")
            )
        elif query == "get_pre_allocated_env_prefix":
            value = workspace_registry.get_pre_allocated_env_prefix(
                _payload_str(payload, "workflow_type")
            )
        elif query == "get_workspace_directory":
            value = workspace_registry.get_workspace_directory_direct(
                _payload_str(payload, "workflow_type"),
                int(payload.get("workspace_num", 1)),
                _payload_str(payload, "project_name"),
                _payload_str(payload, "primary_workspace_dir"),
            )
        elif query == "get_workspace_name":
            value = workspace_registry.get_workspace_name_direct(
                _payload_str(payload, "cwd")
            )
        else:
            raise ProviderHostRuntimeError(
                "operation_unsupported",
                f"unsupported workspace metadata query: {query}",
                target="payload.query",
            )
        return {"query": query, "value": value}

    def _workspace_resolve_ref(self, context: _OperationContext) -> Mapping[str, Any]:
        from dataclasses import asdict

        from sase.workspace_provider import resolve_ref_direct

        payload = dict(context.request.payload)
        resolved = resolve_ref_direct(
            _payload_str(payload, "ref"),
            _payload_str(payload, "workflow_type"),
        )
        return {"value": asdict(resolved)}


def _payload_str(
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


def _call_vcs_query(
    provider: object,
    query: str,
    payload: Mapping[str, Any],
    cwd: str,
) -> Any:
    if query in {"get_branch_name", "get_workspace_name", "has_local_changes"}:
        return _call_provider_method(provider, query, cwd)
    if query == "resolve_revision":
        return provider.resolve_revision(  # type: ignore[attr-defined]
            _payload_str(payload, "changespec_name"),
            _payload_str(payload, "project_basename"),
            cwd,
        )
    if query == "resolve_current_changespec_head_ref":
        return provider.resolve_current_changespec_head_ref(  # type: ignore[attr-defined]
            _payload_str(payload, "changespec_name"),
            _payload_str(payload, "project_basename"),
            cwd,
        )
    if query in {
        "diff",
        "diff_with_untracked",
        "committed_diff",
        "get_default_parent_revision",
        "get_cl_number",
        "get_bug_number",
        "get_change_url",
        "get_conflicted_files",
        "is_sync_in_progress",
    }:
        return _call_provider_method(provider, query, cwd)
    if query in {"diff_revision", "show_revision", "get_description"}:
        return _call_provider_method(
            provider, query, _payload_str(payload, "revision"), cwd
        )
    if query == "diff_name_status":
        return provider.diff_name_status(  # type: ignore[attr-defined]
            _payload_str(payload, "parent_ref"),
            _payload_str(payload, "head_ref"),
            cwd,
        )
    if query == "diff_line_stats":
        return provider.diff_line_stats(  # type: ignore[attr-defined]
            _payload_str(payload, "parent_ref"),
            _payload_str(payload, "head_ref"),
            cwd,
        )
    if query == "file_at_revision":
        return provider.file_at_revision(  # type: ignore[attr-defined]
            _payload_str(payload, "revision"),
            _payload_str(payload, "file_path"),
            cwd,
        )
    if query == "get_change_body":
        return provider.get_change_body(  # type: ignore[attr-defined]
            _payload_str(payload, "change_ref"),
            cwd,
        )
    raise ProviderHostRuntimeError(
        "operation_unsupported",
        f"unsupported vcs query: {query}",
        target="payload.query",
    )


def _call_provider_method(provider: object, method_name: str, *args: object) -> Any:
    method = getattr(provider, method_name, None)
    if method is None:
        raise ProviderHostRuntimeError(
            "operation_unsupported",
            f"VCS provider has no query method: {method_name}",
            target="payload.query",
        )
    return method(*args)


def _network_request_count(request: HostRequestEnvelopeWire) -> int:
    payload = dict(request.payload)
    network = payload.get("network")
    if isinstance(network, Mapping) and network.get("required") is True:
        return 1
    return int(
        payload.get("network_required") is True
        or payload.get("requires_network") is True
    )


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


def _require_capability(context: _OperationContext, capability: str) -> None:
    if capability in context.request.declared_capabilities:
        return
    raise ProviderHostRuntimeError(
        "capability_denied",
        f"host operation requires declared capability {capability}",
        target="declared_capabilities",
    )


def _xprompt_catalog_cache_policy() -> dict[str, Any]:
    """Return stable cache inputs for xprompt/resource catalog calls."""

    from sase.xprompt.loader_sources import get_xprompt_search_paths

    paths: list[dict[str, Any]] = []
    for path in get_xprompt_search_paths():
        paths.append(_path_fingerprint(path))
    for env_name in ("SASE_DISABLE_PLUGINS", "SASE_DISABLE_PLUGIN_XPROMPTS"):
        value = os.environ.get(env_name)
        paths.append({"env": env_name, "value": value})
    return {
        "version": 1,
        "sources": paths,
        "plugin_entry_points": _entry_point_fingerprint("sase_xprompts"),
    }


def _entry_point_fingerprint(group: str) -> list[dict[str, str]]:
    try:
        entry_points = importlib.metadata.entry_points(group=group)
    except Exception:
        return []
    return [
        {"name": ep.name, "value": ep.value}
        for ep in sorted(entry_points, key=lambda item: item.name)
    ]


def _path_fingerprint(path: Any) -> dict[str, Any]:
    path_str = os.fspath(path)
    try:
        stat = os.stat(path_str)
    except OSError:
        return {"path": path_str, "exists": False}
    return {
        "path": path_str,
        "exists": True,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


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
