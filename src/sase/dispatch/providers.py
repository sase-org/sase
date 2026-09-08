"""Dispatch provider discovery hooks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import importlib.metadata
import os
import queue
import threading
from typing import Any

import pluggy

from sase.plugins.qualified_id import (
    PluginQualifiedIdError,
    canonical_plugin_prefix,
    canonical_plugin_qualified_id,
)
from sase.version._utils import metadata_value

from .config import load_dispatch_config, provider_config
from .models import (
    DiagnosticSeverity,
    DispatchConfig,
    DispatchProviderSpec,
    DiscoveryCandidate,
    DiscoveryResult,
    MachineDiagnostic,
    MachineRecord,
)
from .provider_protocol import DISPATCH_PROVIDER_PROTOCOL_VERSION
from .provider_runtime import (
    DispatchProviderExecutionError as _DispatchProviderExecutionError,
    DispatchProviderOperationRunner as _DispatchProviderOperationRunner,
    DispatchProviderRecord as _DispatchProviderRecord,
    machine_payload as _machine_payload,
    provider_error_message as _provider_error_message,
    provider_ref_key,
    run_dispatch_provider_operation as _run_dispatch_provider_operation,
    validate_provider_result as _validate_provider_result,
)
from .tailnet_discovery import discover_tailnet

DISPATCH_ENTRY_POINT_GROUP = "sase_dispatch"
_BUILTIN_PROVIDER_REFS = frozenset({"builtin@https", "builtin@tailnet"})
_DISCOVERY_MIN_TIMEOUT_SECONDS = 0.001

hookspec = pluggy.HookspecMarker("sase_dispatch")
hookimpl = pluggy.HookimplMarker("sase_dispatch")


class DispatchProviderHookSpec:
    """Hook specifications for remote dispatch providers."""

    @hookspec
    def dispatch_provider_specs(
        self,
    ) -> Iterable[Mapping[str, Any]] | Mapping[str, Any] | None:
        """Return remote dispatch provider specs."""
        ...

    @hookspec
    def dispatch_discover(
        self,
        # Hook argument names and kinds are a cross-repo compatibility
        # boundary: pluggy invokes hookimpls positionally, so these must stay
        # positional-or-keyword without defaults.
        provider_ref: str,
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Iterable[Mapping[str, Any]] | Mapping[str, Any] | None:
        """Return explicit remote machine discovery candidates."""
        ...

    @hookspec
    def dispatch_connection_plan(
        self,
        # Hook argument names and kinds are a cross-repo compatibility
        # boundary: pluggy invokes hookimpls positionally, so these must stay
        # positional-or-keyword without defaults.
        provider_ref: str,
        machine: Mapping[str, Any],
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any] | None:
        """Return a serializable fleet connection plan for one machine."""
        ...


# symvision: pyproject.toml
class BuiltinDispatchProviders:
    """Built-in providers that require explicit configuration to do work."""

    @hookimpl
    def dispatch_provider_specs(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "ref": "builtin@https",
                "display_name": "HTTPS Fleet Gateway",
                "supports_discovery": False,
                "builtin": True,
            },
            {
                "ref": "builtin@tailnet",
                "display_name": "Tailnet Fleet Gateway",
                "supports_discovery": True,
                "builtin": True,
            },
        )

    @hookimpl
    def dispatch_discover(
        self,
        provider_ref: str,
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> tuple[Mapping[str, Any], ...]:
        if provider_ref == "builtin@tailnet":
            result = discover_tailnet(config, timeout_seconds)
            return (_discovery_result_payload(result),)
        return ()


@dataclass(frozen=True)
class _DispatchProviderInventory:
    """Provider specs and non-fatal discovery diagnostics."""

    specs: tuple[DispatchProviderSpec, ...]
    diagnostics: tuple[MachineDiagnostic, ...] = ()

    def by_ref(self) -> dict[str, DispatchProviderSpec]:
        return {spec.ref: spec for spec in self.specs}


@dataclass(frozen=True)
class _RawDiscoveryResult:
    """Raw provider payloads plus normalized diagnostics."""

    payloads: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[MachineDiagnostic, ...] = ()


def collect_dispatch_providers(
    *,
    entry_points_fn: Any = importlib.metadata.entry_points,
) -> _DispatchProviderInventory:
    """Collect builtin and plugin dispatch providers without network IO."""
    specs: list[DispatchProviderSpec] = []
    diagnostics: list[MachineDiagnostic] = []

    _collect_plugin_specs(
        BuiltinDispatchProviders(),
        package="sase",
        version=_distribution_version("sase"),
        specs=specs,
        diagnostics=diagnostics,
    )

    disabled_by = _disabled_env_for_group()
    if disabled_by:
        diagnostics.append(
            MachineDiagnostic(
                code="dispatch_plugins_disabled",
                severity="info",
                message=(
                    "third-party dispatch providers disabled by "
                    + ", ".join(disabled_by)
                ),
            )
        )
    for ep in _entry_points(entry_points_fn):
        if _is_builtin_entry_point(ep) or disabled_by:
            continue
        record = _record_from_entry_point(ep, disabled_by=())
        if record is None:
            diagnostics.append(
                MachineDiagnostic(
                    code="dispatch_provider_ref_invalid",
                    severity="error",
                    message=(
                        "dispatch provider entry point "
                        f"{getattr(ep, 'name', '<unknown>')} has an invalid "
                        "<plugin>@<id> reference"
                    ),
                )
            )
            continue
        specs.append(
            DispatchProviderSpec(
                ref=record.provider_ref,
                display_name=record.provider_id,
                supports_discovery=True,
                package=record.package,
                version=record.version,
                builtin=False,
            )
        )

    deduped: dict[str, DispatchProviderSpec] = {}
    for spec in specs:
        key = provider_ref_key(spec.ref)
        if key not in deduped:
            deduped[key] = spec
        else:
            diagnostics.append(
                MachineDiagnostic(
                    code="dispatch_provider_duplicate",
                    severity="warning",
                    message=f"duplicate dispatch provider ref ignored: {spec.ref}",
                )
            )
    return _DispatchProviderInventory(
        specs=tuple(deduped[key] for key in sorted(deduped)),
        diagnostics=tuple(diagnostics),
    )


def discover_dispatch_candidates(
    *,
    config: DispatchConfig | None = None,
    provider_refs: Sequence[str] = (),
    timeout_seconds: float | None = None,
    entry_points_fn: Any = importlib.metadata.entry_points,
    operation_runner: _DispatchProviderOperationRunner | None = None,
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
    operation_runner: _DispatchProviderOperationRunner | None = None,
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

    for provider, provider_ref in _iter_providers_for_refs(
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
                operation_runner=operation_runner or _run_dispatch_provider_operation,
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
    operation_runner: _DispatchProviderOperationRunner | None = None,
) -> Mapping[str, Any]:
    """Return the provider-authored connection plan for *machine*.

    Builtin gateway-style providers derive their plan from the machine record.
    Third-party providers are imported only inside the isolated helper
    subprocess, and only for the selected machine's provider.
    """

    if machine.provider_ref in _BUILTIN_PROVIDER_REFS:
        return machine.to_connection_plan()

    resolved_config = load_dispatch_config() if config is None else config
    provider = _provider_record_by_ref(
        machine.provider_ref,
        entry_points_fn=entry_points_fn,
    )
    if provider is None:
        raise _DispatchProviderExecutionError(
            f"dispatch provider {machine.provider_ref!r} is not installed"
        )
    provider_timeout = timeout_seconds or resolved_config.request_timeout_seconds
    request = {
        "schema_version": DISPATCH_PROVIDER_PROTOCOL_VERSION,
        "operation": "connection_plan",
        "provider_ref": provider.provider_ref,
        "machine": _machine_payload(machine),
        "config": dict(provider_config(resolved_config, machine.provider_ref)),
        "timeout_seconds": provider_timeout,
    }
    result = (operation_runner or _run_dispatch_provider_operation)(
        provider,
        "connection_plan",
        request,
        provider_timeout,
    )
    _validate_provider_result(provider, "connection_plan", result)
    if result.get("status") != "ok":
        raise _DispatchProviderExecutionError(
            _provider_error_message(result, "connection plan failed")
        )
    plan = result.get("plan")
    if isinstance(plan, Mapping):
        return dict(plan)
    return machine.to_connection_plan()


def _collect_plugin_specs(
    plugin: object,
    *,
    package: str,
    version: str,
    specs: list[DispatchProviderSpec],
    diagnostics: list[MachineDiagnostic],
) -> None:
    pm = pluggy.PluginManager("sase_dispatch")
    pm.add_hookspecs(DispatchProviderHookSpec)
    try:
        pm.register(plugin)
    except Exception as exc:  # noqa: BLE001 - provider diagnostics only.
        diagnostics.append(
            MachineDiagnostic(
                code="dispatch_provider_registration_failed",
                severity="error",
                message=f"dispatch provider registration failed: {type(exc).__name__}",
            )
        )
        return

    try:
        raw_specs = pm.hook.dispatch_provider_specs()
    except Exception as exc:  # noqa: BLE001 - provider diagnostics only.
        diagnostics.append(
            MachineDiagnostic(
                code="dispatch_provider_specs_failed",
                severity="error",
                message=f"dispatch provider spec hook failed: {type(exc).__name__}",
            )
        )
        return
    for raw in raw_specs:
        for payload in iter_mapping_specs(raw):
            spec = _spec_from_payload(payload, package=package, version=version)
            if spec is None:
                diagnostics.append(
                    MachineDiagnostic(
                        code="dispatch_provider_spec_invalid",
                        severity="error",
                        message="dispatch provider spec was missing a ref",
                    )
                )
                continue
            specs.append(spec)


def _iter_providers_for_refs(
    provider_refs: Sequence[str],
    *,
    entry_points_fn: Any,
) -> Iterable[tuple[_DispatchProviderRecord, str]]:
    refs = tuple(dict.fromkeys(provider_refs))
    builtin_records = {
        ref: _DispatchProviderRecord(
            provider_ref=ref,
            provider_id=ref.partition("@")[2],
            package="sase",
            version=_distribution_version("sase"),
            entry_point=None,
            builtin=True,
        )
        for ref in _BUILTIN_PROVIDER_REFS
    }
    for ref in refs:
        if ref in builtin_records:
            yield builtin_records[ref], ref
    if _disabled_env_for_group():
        return
    records = _third_party_records(entry_points_fn)
    by_ref = {provider_ref_key(record.provider_ref): record for record in records}
    for ref in refs:
        if ref in _BUILTIN_PROVIDER_REFS:
            continue
        record = by_ref.get(provider_ref_key(ref))
        if record is not None:
            yield record, ref


def _provider_record_by_ref(
    provider_ref: str,
    *,
    entry_points_fn: Any,
) -> _DispatchProviderRecord | None:
    key = provider_ref_key(provider_ref)
    for record in _third_party_records(entry_points_fn):
        if provider_ref_key(record.provider_ref) == key:
            return record
    return None


def _third_party_records(entry_points_fn: Any) -> tuple[_DispatchProviderRecord, ...]:
    records: list[_DispatchProviderRecord] = []
    for ep in _entry_points(entry_points_fn):
        if _is_builtin_entry_point(ep):
            continue
        record = _record_from_entry_point(ep, disabled_by=())
        if record is not None:
            records.append(record)
    return tuple(records)


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


def _discovery_result_payload(result: DiscoveryResult) -> dict[str, object]:
    return {
        "candidates": [
            _candidate_payload(candidate) for candidate in result.candidates
        ],
        "diagnostics": [
            _diagnostic_payload(diagnostic) for diagnostic in result.diagnostics
        ],
    }


def _candidate_payload(candidate: DiscoveryCandidate) -> dict[str, object]:
    return {
        "endpoint": candidate.endpoint,
        "display_name": candidate.display_name,
        "machine_selector": candidate.machine_selector,
        "installation_pin": candidate.installation_pin,
        "detail": candidate.detail,
    }


def _diagnostic_payload(diagnostic: MachineDiagnostic) -> dict[str, object]:
    return {
        "code": diagnostic.code,
        "severity": diagnostic.severity,
        "message": diagnostic.message,
        "alias": diagnostic.alias,
    }


def _unique_refs(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    refs: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        refs.append(value)
    return tuple(refs)


def _positive_timeout(value: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = _DISCOVERY_MIN_TIMEOUT_SECONDS
    return max(_DISCOVERY_MIN_TIMEOUT_SECONDS, timeout)


def _safe_discover_external(
    provider: _DispatchProviderRecord,
    *,
    config: Mapping[str, Any],
    timeout_seconds: float,
    operation_runner: _DispatchProviderOperationRunner,
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
        _validate_provider_result(provider, "discover", result)
    except _DispatchProviderExecutionError as exc:
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
                        f"{_provider_error_message(result, 'provider returned failed status')}"
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


def _record_from_entry_point(
    ep: Any,
    *,
    disabled_by: tuple[str, ...],
) -> _DispatchProviderRecord | None:
    package = _entry_point_package(ep)
    provider_id = str(getattr(ep, "name", "") or "")
    try:
        provider_ref = _canonical_provider_ref_for_entry(
            package=package,
            name=provider_id,
        )
    except PluginQualifiedIdError:
        return None
    return _DispatchProviderRecord(
        provider_ref=provider_ref,
        provider_id=provider_id,
        package=package,
        version=_entry_point_version(ep),
        entry_point=_entry_point_value(ep),
        builtin=False,
        disabled_by=disabled_by,
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


def _spec_from_payload(
    payload: Mapping[str, Any],
    *,
    package: str,
    version: str,
) -> DispatchProviderSpec | None:
    ref = payload.get("ref")
    if not isinstance(ref, str) or not ref:
        return None
    display_name = payload.get("display_name")
    return DispatchProviderSpec(
        ref=ref,
        display_name=display_name if isinstance(display_name, str) else ref,
        supports_discovery=bool(payload.get("supports_discovery", False)),
        package=package,
        version=version,
        builtin=bool(payload.get("builtin", False)),
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


def iter_mapping_specs(value: object) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _entry_points(entry_points_fn: Any) -> tuple[Any, ...]:
    eps = entry_points_fn(group=DISPATCH_ENTRY_POINT_GROUP)
    return tuple(eps)


def _disabled_env_for_group() -> tuple[str, ...]:
    disabled: list[str] = []
    if os.environ.get("SASE_DISABLE_PLUGINS"):
        disabled.append("SASE_DISABLE_PLUGINS")
    suffix = DISPATCH_ENTRY_POINT_GROUP.removeprefix("sase_").upper()
    env_key = f"SASE_DISABLE_PLUGIN_{suffix}"
    if os.environ.get(env_key):
        disabled.append(env_key)
    return tuple(disabled)


def _is_builtin_entry_point(ep: Any) -> bool:
    # The sase package registers its builtin providers both in code (above)
    # and as an entry point for plugin-inventory visibility; skip the entry
    # point so the providers are not collected twice.
    return (
        _entry_point_package(ep).lower() == "sase"
        and str(getattr(ep, "name", "")) == "builtin"
    )


def _entry_point_package(ep: Any) -> str:
    dist = getattr(ep, "dist", None)
    metadata = getattr(dist, "metadata", None)
    name = metadata_value(metadata, "Name")
    if name:
        return name
    direct_name = getattr(dist, "name", None)
    if isinstance(direct_name, str) and direct_name:
        return direct_name
    return ""


def _entry_point_version(ep: Any) -> str:
    dist = getattr(ep, "dist", None)
    version = getattr(dist, "version", None)
    return str(version) if version else ""


def _entry_point_value(ep: Any) -> str | None:
    value = getattr(ep, "value", None)
    return value if isinstance(value, str) and value else None


def _canonical_provider_ref_for_entry(*, package: str, name: str) -> str:
    return canonical_plugin_qualified_id(f"{canonical_plugin_prefix(package)}@{name}")


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""


__all__ = [
    "DISPATCH_ENTRY_POINT_GROUP",
    "DispatchProviderHookSpec",
    "collect_dispatch_providers",
    "connection_plan_for_machine",
    "discover_dispatch_candidates",
    "discover_dispatch_result",
    "hookimpl",
    "hookspec",
    "iter_mapping_specs",
    "provider_ref_key",
]
