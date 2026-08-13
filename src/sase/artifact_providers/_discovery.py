"""Entry-point discovery for artifact-provider plugins."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import importlib.metadata
import os
from typing import Any

import pluggy

from ._builtin import BuiltinArtifactProviders
from ._hookspec import ArtifactProviderHookSpec
from ._models import ArtifactProviderDiagnostic, ArtifactProviderProvenance

ARTIFACT_REF_ENTRY_POINT_GROUP = "sase_artifact_refs"
FILE_HOOK_ENTRY_POINT_GROUP = "sase_file_hooks"
ARTIFACT_PROVIDER_ENTRY_POINT_GROUPS = (
    ARTIFACT_REF_ENTRY_POINT_GROUP,
    FILE_HOOK_ENTRY_POINT_GROUP,
)

ProviderCandidate = tuple[Mapping[str, Any], ArtifactProviderProvenance]


@dataclass(frozen=True)
class _ArtifactProviderDiscovery:
    """Unvalidated provider specs and diagnostics collected from plugins."""

    ref_candidates: tuple[ProviderCandidate, ...]
    file_hook_candidates: tuple[ProviderCandidate, ...]
    diagnostics: tuple[ArtifactProviderDiagnostic, ...]
    disabled_env: tuple[str, ...]


def discover_artifact_provider_specs(
    *,
    entry_points_fn: Any,
) -> _ArtifactProviderDiscovery:
    """Collect builtin and installed artifact-provider specs."""

    diagnostics: list[ArtifactProviderDiagnostic] = []
    disabled_env: set[str] = set()
    ref_candidates: list[ProviderCandidate] = []
    file_hook_candidates: list[ProviderCandidate] = []

    builtin = ArtifactProviderProvenance(
        group="builtin",
        name="sase",
        package="sase",
        version=_distribution_version("sase"),
        builtin=True,
    )
    _collect_plugin_specs(
        BuiltinArtifactProviders(),
        builtin,
        ref_candidates=ref_candidates,
        file_hook_candidates=file_hook_candidates,
        diagnostics=diagnostics,
    )

    for group in ARTIFACT_PROVIDER_ENTRY_POINT_GROUPS:
        disabled_by = _disabled_env_for_group(group)
        disabled_env.update(disabled_by)
        if disabled_by:
            continue
        for ep in _entry_points_for_group(group, entry_points_fn=entry_points_fn):
            provenance = ArtifactProviderProvenance(
                group=group,
                name=_safe_str(getattr(ep, "name", None), "<unknown>"),
                value=_safe_str(getattr(ep, "value", None), ""),
                package=_entry_point_package(ep),
                version=_entry_point_version(ep),
            )
            if _is_builtin_entry_point(provenance):
                continue
            try:
                loaded = ep.load()
                plugin = loaded() if isinstance(loaded, type) else loaded
            except Exception as exc:
                diagnostics.append(
                    ArtifactProviderDiagnostic(
                        code="entry_point_load_failed",
                        message=(
                            "Failed to load artifact provider entry point "
                            f"{provenance.label}: {type(exc).__name__}: {exc}"
                        ),
                        severity="error",
                        group=group,
                        source=provenance.label,
                        package=provenance.package,
                        version=provenance.version,
                    )
                )
                continue
            _collect_plugin_specs(
                plugin,
                provenance,
                ref_candidates=ref_candidates,
                file_hook_candidates=file_hook_candidates,
                diagnostics=diagnostics,
            )

    return _ArtifactProviderDiscovery(
        ref_candidates=tuple(ref_candidates),
        file_hook_candidates=tuple(file_hook_candidates),
        diagnostics=tuple(diagnostics),
        disabled_env=tuple(sorted(disabled_env)),
    )


def _collect_plugin_specs(
    plugin: object,
    provenance: ArtifactProviderProvenance,
    *,
    ref_candidates: list[ProviderCandidate],
    file_hook_candidates: list[ProviderCandidate],
    diagnostics: list[ArtifactProviderDiagnostic],
) -> None:
    pm = pluggy.PluginManager("sase_artifact")
    pm.add_hookspecs(ArtifactProviderHookSpec)
    try:
        pm.register(plugin, name=provenance.label)
    except Exception as exc:
        diagnostics.append(
            ArtifactProviderDiagnostic(
                code="plugin_registration_failed",
                message=(
                    f"Failed to register artifact provider {provenance.label}: "
                    f"{type(exc).__name__}: {exc}"
                ),
                severity="error",
                group=provenance.group,
                source=provenance.label,
                package=provenance.package,
                version=provenance.version,
            )
        )
        return

    try:
        ref_results = pm.hook.artifact_ref_provider_specs()
    except Exception as exc:
        diagnostics.append(
            _plugin_call_diagnostic("ref_provider_hook_failed", provenance, exc)
        )
        ref_results = ()
    try:
        file_hook_results = pm.hook.artifact_file_hook_provider_specs()
    except Exception as exc:
        diagnostics.append(
            _plugin_call_diagnostic("file_hook_provider_hook_failed", provenance, exc)
        )
        file_hook_results = ()

    for result in ref_results:
        for spec in _iter_mapping_specs(result):
            ref_candidates.append((spec, provenance))
    for result in file_hook_results:
        for spec in _iter_mapping_specs(result):
            file_hook_candidates.append((spec, provenance))


def _plugin_call_diagnostic(
    code: str,
    provenance: ArtifactProviderProvenance,
    exc: Exception,
) -> ArtifactProviderDiagnostic:
    return ArtifactProviderDiagnostic(
        code=code,
        message=(
            f"Artifact provider {provenance.label} failed while returning specs: "
            f"{type(exc).__name__}: {exc}"
        ),
        severity="error",
        group=provenance.group,
        source=provenance.label,
        package=provenance.package,
        version=provenance.version,
    )


def _iter_mapping_specs(result: object) -> Iterable[Mapping[str, Any]]:
    if result is None:
        return ()
    if isinstance(result, Mapping):
        return (result,)
    if isinstance(result, Iterable) and not isinstance(result, (str, bytes)):
        return tuple(item for item in result if isinstance(item, Mapping))
    return ()


def _entry_points_for_group(
    group: str,
    *,
    entry_points_fn: Any,
) -> list[importlib.metadata.EntryPoint]:
    eps = entry_points_fn(group=group)
    return sorted(eps, key=lambda ep: getattr(ep, "name", ""))


def _disabled_env_for_group(group: str) -> tuple[str, ...]:
    disabled: list[str] = []
    if os.environ.get("SASE_DISABLE_PLUGINS"):
        disabled.append("SASE_DISABLE_PLUGINS")
    suffix = group.removeprefix("sase_").upper()
    env_key = f"SASE_DISABLE_PLUGIN_{suffix}"
    if os.environ.get(env_key):
        disabled.append(env_key)
    return tuple(disabled)


def _entry_point_package(ep: importlib.metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    metadata = getattr(dist, "metadata", None)
    name = _metadata_value(metadata, "Name")
    if name:
        return name
    direct_name = getattr(dist, "name", None)
    if isinstance(direct_name, str) and direct_name:
        return direct_name
    return "<unknown>"


def _entry_point_version(ep: importlib.metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    version = getattr(dist, "version", None)
    if isinstance(version, str) and version:
        return version
    metadata = getattr(dist, "metadata", None)
    return _metadata_value(metadata, "Version") or "<unknown>"


def _distribution_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "<unknown>"


def _metadata_value(metadata: object, key: str) -> str | None:
    getter = getattr(metadata, "get", None)
    if not callable(getter):
        return None
    value = getter(key)
    return value if isinstance(value, str) and value else None


def _safe_str(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _is_builtin_entry_point(provenance: ArtifactProviderProvenance) -> bool:
    return (
        provenance.package.lower() == "sase"
        and provenance.group == ARTIFACT_REF_ENTRY_POINT_GROUP
        and provenance.name == "builtin"
    )


__all__ = [
    "ARTIFACT_PROVIDER_ENTRY_POINT_GROUPS",
    "ARTIFACT_REF_ENTRY_POINT_GROUP",
    "FILE_HOOK_ENTRY_POINT_GROUP",
    "discover_artifact_provider_specs",
]
