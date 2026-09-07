"""Dispatch provider discovery hooks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import importlib.metadata
from typing import Any

import pluggy

from .config import load_dispatch_config, provider_config
from .models import (
    DispatchConfig,
    DispatchProviderSpec,
    DiscoveryCandidate,
    MachineDiagnostic,
)

DISPATCH_ENTRY_POINT_GROUP = "sase_dispatch"

hookspec = pluggy.HookspecMarker("sase_dispatch")
hookimpl = pluggy.HookimplMarker("sase_dispatch")


class _DispatchProviderHookSpec:
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
        *,
        provider_ref: str,
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Iterable[Mapping[str, Any]] | Mapping[str, Any] | None:
        """Return explicit remote machine discovery candidates."""
        ...


class _BuiltinDispatchProviders:
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
        *,
        provider_ref: str,
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> tuple[Mapping[str, Any], ...]:
        del config, timeout_seconds
        if provider_ref == "builtin@tailnet":
            return ()
        return ()


@dataclass(frozen=True)
class _DispatchProviderInventory:
    """Provider specs and non-fatal discovery diagnostics."""

    specs: tuple[DispatchProviderSpec, ...]
    diagnostics: tuple[MachineDiagnostic, ...] = ()

    def by_ref(self) -> dict[str, DispatchProviderSpec]:
        return {spec.ref: spec for spec in self.specs}


def collect_dispatch_providers(
    *,
    entry_points_fn: Any = importlib.metadata.entry_points,
) -> _DispatchProviderInventory:
    """Collect builtin and plugin dispatch providers without network IO."""
    specs: list[DispatchProviderSpec] = []
    diagnostics: list[MachineDiagnostic] = []

    _collect_plugin_specs(
        _BuiltinDispatchProviders(),
        package="sase",
        version=_distribution_version("sase"),
        specs=specs,
        diagnostics=diagnostics,
    )

    for ep in _entry_points(entry_points_fn):
        package = _entry_point_package(ep)
        version = _entry_point_version(ep)
        try:
            loaded = ep.load()
            plugin = loaded() if isinstance(loaded, type) else loaded
        except Exception as exc:  # noqa: BLE001 - provider diagnostics only.
            diagnostics.append(
                MachineDiagnostic(
                    code="dispatch_provider_load_failed",
                    severity="error",
                    message=(
                        "dispatch provider entry point "
                        f"{getattr(ep, 'name', '<unknown>')} could not be loaded: "
                        f"{type(exc).__name__}"
                    ),
                )
            )
            continue
        _collect_plugin_specs(
            plugin,
            package=package,
            version=version,
            specs=specs,
            diagnostics=diagnostics,
        )

    deduped: dict[str, DispatchProviderSpec] = {}
    for spec in specs:
        if spec.ref not in deduped:
            deduped[spec.ref] = spec
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
) -> tuple[DiscoveryCandidate, ...]:
    """Run explicit provider discovery for enabled providers only."""
    resolved_config = load_dispatch_config() if config is None else config
    selected_refs = (
        tuple(provider_refs) or resolved_config.discovery_enabled_provider_refs
    )
    if not selected_refs:
        return ()

    candidates: list[DiscoveryCandidate] = []
    for plugin, provider_ref in _iter_plugins_for_refs(
        selected_refs,
        entry_points_fn=entry_points_fn,
    ):
        if not resolved_config.provider_enabled(provider_ref):
            continue
        payloads = _safe_discover(
            plugin,
            provider_ref=provider_ref,
            config=provider_config(resolved_config, provider_ref),
            timeout_seconds=timeout_seconds or resolved_config.request_timeout_seconds,
        )
        for payload in payloads:
            candidate = _candidate_from_payload(provider_ref, payload)
            if candidate is not None:
                candidates.append(candidate)
    return tuple(sorted(_dedupe_candidates(candidates), key=lambda item: item.key))


def _collect_plugin_specs(
    plugin: object,
    *,
    package: str,
    version: str,
    specs: list[DispatchProviderSpec],
    diagnostics: list[MachineDiagnostic],
) -> None:
    pm = pluggy.PluginManager("sase_dispatch")
    pm.add_hookspecs(_DispatchProviderHookSpec)
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
        for payload in _iter_mapping_specs(raw):
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


def _iter_plugins_for_refs(
    provider_refs: Sequence[str],
    *,
    entry_points_fn: Any,
) -> Iterable[tuple[object, str]]:
    refs = set(provider_refs)
    builtin = _BuiltinDispatchProviders()
    for ref in refs & {"builtin@https", "builtin@tailnet"}:
        yield builtin, ref
    for ep in _entry_points(entry_points_fn):
        try:
            loaded = ep.load()
            plugin = loaded() if isinstance(loaded, type) else loaded
        except Exception:
            continue
        for spec in _plugin_specs(plugin):
            if spec.ref in refs:
                yield plugin, spec.ref


def _plugin_specs(plugin: object) -> tuple[DispatchProviderSpec, ...]:
    specs: list[DispatchProviderSpec] = []
    _collect_plugin_specs(
        plugin,
        package="",
        version="",
        specs=specs,
        diagnostics=[],
    )
    return tuple(specs)


def _safe_discover(
    plugin: object,
    *,
    provider_ref: str,
    config: Mapping[str, Any],
    timeout_seconds: float,
) -> tuple[Mapping[str, Any], ...]:
    pm = pluggy.PluginManager("sase_dispatch")
    pm.add_hookspecs(_DispatchProviderHookSpec)
    try:
        pm.register(plugin)
        results = pm.hook.dispatch_discover(
            provider_ref=provider_ref,
            config=config,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        return ()
    payloads: list[Mapping[str, Any]] = []
    for result in results:
        payloads.extend(_iter_mapping_specs(result))
    return tuple(payloads)


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


def _iter_mapping_specs(value: object) -> tuple[Mapping[str, Any], ...]:
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


def _entry_point_package(ep: Any) -> str:
    dist = getattr(ep, "dist", None)
    metadata = getattr(dist, "metadata", None)
    name = metadata.get("Name") if metadata is not None else None
    return str(name) if name else ""


def _entry_point_version(ep: Any) -> str:
    dist = getattr(ep, "dist", None)
    version = getattr(dist, "version", None)
    return str(version) if version else ""


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""


__all__ = [
    "DISPATCH_ENTRY_POINT_GROUP",
    "collect_dispatch_providers",
    "discover_dispatch_candidates",
    "hookimpl",
    "hookspec",
]
