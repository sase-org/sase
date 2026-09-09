"""Explicit dispatch provider discovery and connection-plan resolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import importlib.metadata
import queue
import threading
from typing import Any

import pluggy

from .config import load_dispatch_config, provider_config
from .models import (
    DiagnosticSeverity,
    DispatchConfig,
    DiscoveryCandidate,
    DiscoveryResult,
    MachineDiagnostic,
    MachineRecord,
)
from .provider_hooks import DispatchProviderHookSpec, iter_mapping_specs
from .provider_inventory import (
    BUILTIN_PROVIDER_REFS,
    BuiltinDispatchProviders,
    collect_dispatch_providers,
    iter_providers_for_refs,
    provider_record_by_ref,
)
from .provider_protocol import DISPATCH_PROVIDER_PROTOCOL_VERSION
from .provider_runtime import (
    DispatchProviderExecutionError,
    DispatchProviderOperationRunner,
    DispatchProviderRecord,
    machine_payload,
    provider_error_message,
    provider_ref_key,
    run_dispatch_provider_operation,
    validate_provider_result,
)

_DISCOVERY_MIN_TIMEOUT_SECONDS = 0.001


@dataclass(frozen=True)
class _RawDiscoveryResult:
    """Raw provider payloads plus normalized diagnostics."""

    payloads: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[MachineDiagnostic, ...] = ()


def discover_dispatch_candidates(
    *,
    config: DispatchConfig | None = None,
    provider_refs: Sequence[str] = (),
    timeout_seconds: float | None = None,
    entry_points_fn: Any = importlib.metadata.entry_points,
    operation_runner: DispatchProviderOperationRunner | None = None,
) -> tuple[DiscoveryCandidate, ...]:
    """Run explicit provider discovery and return candidates only."""
    return discover_dispatch_result(
        config=config,
        provider_refs=provider_refs,
        timeout_seconds=timeout_seconds,
        entry_points_fn=entry_points_fn,
        operation_runner=operation_runner,
    ).candidates


def discover_dispatch_result(
    *,
    config: DispatchConfig | None = None,
    provider_refs: Sequence[str] = (),
    timeout_seconds: float | None = None,
    entry_points_fn: Any = importlib.metadata.entry_points,
    operation_runner: DispatchProviderOperationRunner | None = None,
) -> DiscoveryResult:
    """Run explicit provider discovery for enabled providers."""
    resolved_config = load_dispatch_config() if config is None else config
    selected_refs = _unique_refs(
        tuple(provider_refs) or resolved_config.discovery_enabled_provider_refs
    )
    if not selected_refs:
        return DiscoveryResult()

    diagnostics: list[MachineDiagnostic] = []
    candidates: list[DiscoveryCandidate] = []
    enabled_refs: list[str] = []
    for provider_ref in selected_refs:
        if resolved_config.provider_enabled(provider_ref):
            enabled_refs.append(provider_ref)
            continue
        diagnostics.append(
            MachineDiagnostic(
                code="dispatch_provider_disabled",
                severity="warning",
                message=(
                    f"dispatch provider {provider_ref} is selected for discovery "
                    "but disabled"
                ),
            )
        )

    if not enabled_refs:
        return DiscoveryResult(diagnostics=tuple(diagnostics))

    inventory = collect_dispatch_providers(entry_points_fn=entry_points_fn)
    diagnostics.extend(inventory.diagnostics)
    installed = {
        provider_ref_key(provider_ref): spec
        for provider_ref, spec in inventory.by_ref().items()
    }
    discoverable_refs: list[str] = []
    for provider_ref in enabled_refs:
        spec = installed.get(provider_ref_key(provider_ref))
        if spec is None:
            diagnostics.append(
                MachineDiagnostic(
                    code="dispatch_provider_not_installed",
                    severity="error",
                    message=(
                        f"dispatch provider {provider_ref} is selected for discovery "
                        "but is not installed"
                    ),
                )
            )
        elif not spec.supports_discovery:
            diagnostics.append(
                MachineDiagnostic(
                    code="dispatch_provider_discovery_unsupported",
                    severity="warning",
                    message=(
                        f"dispatch provider {provider_ref} does not support discovery"
                    ),
                )
            )
        else:
            discoverable_refs.append(spec.ref)

    for provider, provider_ref in iter_providers_for_refs(
        discoverable_refs,
        entry_points_fn=entry_points_fn,
    ):
        provider_timeout = timeout_seconds or resolved_config.request_timeout_seconds
        provider_settings = provider_config(resolved_config, provider_ref)
        if provider.builtin:
            result = _safe_discover(
                BuiltinDispatchProviders(),
                provider_ref=provider_ref,
                config=provider_settings,
                timeout_seconds=provider_timeout,
            )
        else:
            result = _safe_discover_external(
                provider,
                config=provider_settings,
                timeout_seconds=provider_timeout,
                operation_runner=operation_runner or run_dispatch_provider_operation,
            )
        diagnostics.extend(result.diagnostics)
        for payload in result.payloads:
            candidate = _candidate_from_payload(provider_ref, payload)
            if candidate is not None:
                candidates.append(candidate)
    return DiscoveryResult(
        candidates=tuple(
            sorted(_dedupe_candidates(candidates), key=lambda item: item.key)
        ),
        diagnostics=tuple(diagnostics),
    )


def connection_plan_for_machine(
    machine: MachineRecord,
    *,
    config: DispatchConfig | None = None,
    timeout_seconds: float | None = None,
    entry_points_fn: Any = importlib.metadata.entry_points,
    operation_runner: DispatchProviderOperationRunner | None = None,
) -> Mapping[str, Any]:
    """Return the provider-authored connection plan for *machine*.

    Builtin gateway-style providers derive their plan from the machine record.
    Third-party providers are imported only inside the isolated helper
    subprocess, and only for the selected machine's provider.
    """

    if machine.provider_ref in BUILTIN_PROVIDER_REFS:
        return machine.to_connection_plan()

    resolved_config = load_dispatch_config() if config is None else config
    provider = provider_record_by_ref(
        machine.provider_ref,
        entry_points_fn=entry_points_fn,
    )
    if provider is None:
        raise DispatchProviderExecutionError(
            f"dispatch provider {machine.provider_ref!r} is not installed"
        )
    provider_timeout = timeout_seconds or resolved_config.request_timeout_seconds
    request = {
        "schema_version": DISPATCH_PROVIDER_PROTOCOL_VERSION,
        "operation": "connection_plan",
        "provider_ref": provider.provider_ref,
        "machine": machine_payload(machine),
        "config": dict(provider_config(resolved_config, machine.provider_ref)),
        "timeout_seconds": provider_timeout,
    }
    result = (operation_runner or run_dispatch_provider_operation)(
        provider,
        "connection_plan",
        request,
        provider_timeout,
    )
    validate_provider_result(provider, "connection_plan", result)
    if result.get("status") != "ok":
        raise DispatchProviderExecutionError(
            provider_error_message(result, "connection plan failed")
        )
    plan = result.get("plan")
    if isinstance(plan, Mapping):
        return dict(plan)
    return machine.to_connection_plan()


def _safe_discover(
    plugin: object,
    *,
    provider_ref: str,
    config: Mapping[str, Any],
    timeout_seconds: float,
) -> _RawDiscoveryResult:
    timeout = _positive_timeout(timeout_seconds)
    outcomes: queue.Queue[_RawDiscoveryResult | Exception] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            outcomes.put(
                _run_discovery_hook(
                    plugin,
                    provider_ref=provider_ref,
                    config=config,
                    timeout_seconds=timeout,
                )
            )
        except Exception as exc:  # noqa: BLE001 - discovery diagnostics only.
            outcomes.put(exc)

    thread = threading.Thread(
        target=worker,
        name=f"sase-dispatch-discover-{provider_ref}",
        daemon=True,
    )
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return _RawDiscoveryResult(
            diagnostics=(
                MachineDiagnostic(
                    code="dispatch_provider_discovery_timeout",
                    severity="error",
                    message=(
                        f"dispatch provider {provider_ref} discovery exceeded "
                        f"{timeout:g}s"
                    ),
                ),
            )
        )

    try:
        outcome = outcomes.get_nowait()
    except queue.Empty:  # pragma: no cover - defensive thread invariant.
        return _RawDiscoveryResult(
            diagnostics=(
                MachineDiagnostic(
                    code="dispatch_provider_discovery_failed",
                    severity="error",
                    message=f"dispatch provider {provider_ref} discovery produced no result",
                ),
            )
        )
    if isinstance(outcome, Exception):
        return _RawDiscoveryResult(
            diagnostics=(
                MachineDiagnostic(
                    code="dispatch_provider_discovery_failed",
                    severity="error",
                    message=(
                        f"dispatch provider {provider_ref} discovery failed: "
                        f"{type(outcome).__name__}"
                    ),
                ),
            )
        )
    return outcome


def _run_discovery_hook(
    plugin: object,
    *,
    provider_ref: str,
    config: Mapping[str, Any],
    timeout_seconds: float,
) -> _RawDiscoveryResult:
    pm = pluggy.PluginManager("sase_dispatch")
    pm.add_hookspecs(DispatchProviderHookSpec)
    pm.register(plugin)
    results = pm.hook.dispatch_discover(
        provider_ref=provider_ref,
        config=config,
        timeout_seconds=timeout_seconds,
    )
    payloads: list[Mapping[str, Any]] = []
    diagnostics: list[MachineDiagnostic] = []
    for result in results:
        _collect_discovery_hook_result(result, payloads, diagnostics)
    return _RawDiscoveryResult(payloads=tuple(payloads), diagnostics=tuple(diagnostics))


def _collect_discovery_hook_result(
    value: object,
    payloads: list[Mapping[str, Any]],
    diagnostics: list[MachineDiagnostic],
) -> None:
    if value is None:
        return
    if isinstance(value, Mapping):
        candidates = value.get("candidates")
        if candidates is not None:
            payloads.extend(iter_mapping_specs(candidates))
        raw_diagnostics = value.get("diagnostics")
        if raw_diagnostics is not None:
            diagnostics.extend(
                diagnostic
                for diagnostic in (
                    _diagnostic_from_payload(item)
                    for item in iter_mapping_specs(raw_diagnostics)
                )
                if diagnostic is not None
            )
        if "endpoint" in value or (candidates is None and raw_diagnostics is None):
            payloads.append(value)
        return
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _collect_discovery_hook_result(item, payloads, diagnostics)


def _diagnostic_from_payload(payload: Mapping[str, Any]) -> MachineDiagnostic | None:
    code = payload.get("code")
    message = payload.get("message")
    if not isinstance(code, str) or not code:
        return None
    if not isinstance(message, str) or not message:
        return None
    severity = payload.get("severity")
    alias = payload.get("alias")
    severity_value: DiagnosticSeverity
    if severity == "info":
        severity_value = "info"
    elif severity == "error":
        severity_value = "error"
    else:
        severity_value = "warning"
    return MachineDiagnostic(
        code=code,
        message=message,
        severity=severity_value,
        alias=alias if isinstance(alias, str) else "",
    )


def _unique_refs(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _positive_timeout(value: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = _DISCOVERY_MIN_TIMEOUT_SECONDS
    return max(_DISCOVERY_MIN_TIMEOUT_SECONDS, timeout)


def _safe_discover_external(
    provider: DispatchProviderRecord,
    *,
    config: Mapping[str, Any],
    timeout_seconds: float,
    operation_runner: DispatchProviderOperationRunner,
) -> _RawDiscoveryResult:
    request = {
        "schema_version": DISPATCH_PROVIDER_PROTOCOL_VERSION,
        "operation": "discover",
        "provider_ref": provider.provider_ref,
        "config": dict(config),
        "timeout_seconds": timeout_seconds,
    }
    try:
        result = operation_runner(provider, "discover", request, timeout_seconds)
        validate_provider_result(provider, "discover", result)
    except DispatchProviderExecutionError as exc:
        return _RawDiscoveryResult(
            diagnostics=(
                MachineDiagnostic(
                    code="dispatch_provider_discovery_failed",
                    severity="error",
                    message=(
                        f"dispatch provider {provider.provider_ref} discovery failed: "
                        f"{exc}"
                    ),
                ),
            )
        )
    if result.get("status") != "ok":
        return _RawDiscoveryResult(
            diagnostics=(
                MachineDiagnostic(
                    code="dispatch_provider_discovery_failed",
                    severity="error",
                    message=(
                        f"dispatch provider {provider.provider_ref} discovery failed: "
                        f"{provider_error_message(result, 'provider returned failed status')}"
                    ),
                ),
            )
        )
    diagnostics = list(_provider_result_diagnostics(result))
    raw_candidates = result.get("candidates")
    if not isinstance(raw_candidates, Sequence) or isinstance(
        raw_candidates, (str, bytes, bytearray)
    ):
        return _RawDiscoveryResult(diagnostics=tuple(diagnostics))
    payloads: list[Mapping[str, Any]] = []
    for item in raw_candidates:
        _collect_discovery_hook_result(item, payloads, diagnostics)
    return _RawDiscoveryResult(
        payloads=tuple(payloads),
        diagnostics=tuple(diagnostics),
    )


def _provider_result_diagnostics(
    result: Mapping[str, Any],
) -> tuple[MachineDiagnostic, ...]:
    raw = result.get("diagnostics")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return ()
    return tuple(
        diagnostic
        for diagnostic in (
            _diagnostic_from_payload(item) for item in iter_mapping_specs(raw)
        )
        if diagnostic is not None
    )


def _candidate_from_payload(
    provider_ref: str,
    payload: Mapping[str, Any],
) -> DiscoveryCandidate | None:
    endpoint = payload.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        return None
    display_name = payload.get("display_name")
    machine_selector = payload.get("machine_selector")
    installation_pin = payload.get("installation_pin")
    detail = payload.get("detail")
    return DiscoveryCandidate(
        provider_ref=provider_ref,
        endpoint=endpoint,
        display_name=display_name if isinstance(display_name, str) else "",
        machine_selector=machine_selector if isinstance(machine_selector, str) else "",
        installation_pin=installation_pin if isinstance(installation_pin, str) else "",
        detail=detail if isinstance(detail, str) else "",
    )


def _dedupe_candidates(
    candidates: Sequence[DiscoveryCandidate],
) -> tuple[DiscoveryCandidate, ...]:
    seen: dict[str, DiscoveryCandidate] = {}
    for candidate in candidates:
        seen.setdefault(candidate.key, candidate)
    return tuple(seen.values())


__all__ = [
    "connection_plan_for_machine",
    "discover_dispatch_candidates",
    "discover_dispatch_result",
]
