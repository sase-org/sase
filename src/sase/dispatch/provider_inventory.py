"""Collect builtin and plugin dispatch provider specs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import importlib.metadata
import os
from typing import Any

import pluggy

from sase.plugins.qualified_id import (
    PluginQualifiedIdError,
    canonical_plugin_prefix,
    canonical_plugin_qualified_id,
)
from sase.version._utils import metadata_value

from .models import (
    DispatchProviderSpec,
    DiscoveryCandidate,
    DiscoveryResult,
    MachineDiagnostic,
)
from .provider_hooks import (
    DISPATCH_ENTRY_POINT_GROUP,
    DispatchProviderHookSpec,
    hookimpl,
    iter_mapping_specs,
)
from .provider_runtime import DispatchProviderRecord, provider_ref_key
from .tailnet_discovery import discover_tailnet

BUILTIN_PROVIDER_REFS = frozenset({"builtin@https", "builtin@tailnet"})


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


def iter_providers_for_refs(
    provider_refs: Sequence[str],
    *,
    entry_points_fn: Any,
) -> Iterable[tuple[DispatchProviderRecord, str]]:
    refs = tuple(dict.fromkeys(provider_refs))
    builtin_records = {
        ref: DispatchProviderRecord(
            provider_ref=ref,
            provider_id=ref.partition("@")[2],
            package="sase",
            version=_distribution_version("sase"),
            entry_point=None,
            builtin=True,
        )
        for ref in BUILTIN_PROVIDER_REFS
    }
    for ref in refs:
        if ref in builtin_records:
            yield builtin_records[ref], ref
    if _disabled_env_for_group():
        return
    records = _third_party_records(entry_points_fn)
    by_ref = {provider_ref_key(record.provider_ref): record for record in records}
    for ref in refs:
        if ref in BUILTIN_PROVIDER_REFS:
            continue
        record = by_ref.get(provider_ref_key(ref))
        if record is not None:
            yield record, ref


def provider_record_by_ref(
    provider_ref: str,
    *,
    entry_points_fn: Any,
) -> DispatchProviderRecord | None:
    key = provider_ref_key(provider_ref)
    for record in _third_party_records(entry_points_fn):
        if provider_ref_key(record.provider_ref) == key:
            return record
    return None


def _third_party_records(entry_points_fn: Any) -> tuple[DispatchProviderRecord, ...]:
    records: list[DispatchProviderRecord] = []
    for ep in _entry_points(entry_points_fn):
        if _is_builtin_entry_point(ep):
            continue
        record = _record_from_entry_point(ep, disabled_by=())
        if record is not None:
            records.append(record)
    return tuple(records)


def _record_from_entry_point(
    ep: Any,
    *,
    disabled_by: tuple[str, ...],
) -> DispatchProviderRecord | None:
    package = _entry_point_package(ep)
    provider_id = str(getattr(ep, "name", "") or "")
    try:
        provider_ref = _canonical_provider_ref_for_entry(
            package=package,
            name=provider_id,
        )
    except PluginQualifiedIdError:
        return None
    return DispatchProviderRecord(
        provider_ref=provider_ref,
        provider_id=provider_id,
        package=package,
        version=_entry_point_version(ep),
        entry_point=_entry_point_value(ep),
        builtin=False,
        disabled_by=disabled_by,
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
    "BUILTIN_PROVIDER_REFS",
    "BuiltinDispatchProviders",
    "collect_dispatch_providers",
    "iter_providers_for_refs",
    "provider_record_by_ref",
]
