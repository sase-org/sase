"""Artifact provider discovery, validation, and registry assembly."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import importlib.metadata
import os
from types import MappingProxyType
from typing import Any, Literal

import pluggy

from sase.config.core import current_config_token
from sase.core.rust import require_rust_binding

from ._builtin import BuiltinArtifactProviders
from ._hookspec import ArtifactProviderHookSpec

ARTIFACT_REF_ENTRY_POINT_GROUP = "sase_artifact_refs"
FILE_HOOK_ENTRY_POINT_GROUP = "sase_file_hooks"
ARTIFACT_PROVIDER_ENTRY_POINT_GROUPS = (
    ARTIFACT_REF_ENTRY_POINT_GROUP,
    FILE_HOOK_ENTRY_POINT_GROUP,
)
FILE_HOOK_PROVIDER_SPEC_SCHEMA_VERSION = 1

DiagnosticSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class ArtifactProviderProvenance:
    """Origin metadata for one discovered artifact provider."""

    group: str
    name: str
    package: str
    version: str
    value: str = ""
    builtin: bool = False

    @property
    def label(self) -> str:
        if self.builtin:
            return "builtin:sase"
        return f"{self.group}:{self.name}"


@dataclass(frozen=True)
class ArtifactProviderDiagnostic:
    """Structured diagnostic emitted while assembling artifact providers."""

    code: str
    message: str
    severity: DiagnosticSeverity = "warning"
    provider: str | None = None
    kind: str | None = None
    group: str | None = None
    source: str | None = None
    package: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class ArtifactRefProviderRecord:
    """One validated document artifact-reference provider."""

    provider_id: str
    kind: str
    digest: str
    spec: Mapping[str, Any]
    provenance: ArtifactProviderProvenance


@dataclass(frozen=True)
class FileHookProviderRecord:
    """One validated file-hook provider template."""

    provider_id: str
    template: Mapping[str, Any]
    required_fields: tuple[str, ...]
    provenance: ArtifactProviderProvenance


@dataclass(frozen=True)
class ArtifactProviderRegistry:
    """Effective artifact provider registry plus assembly diagnostics."""

    ref_providers: tuple[ArtifactRefProviderRecord, ...]
    file_hook_providers: tuple[FileHookProviderRecord, ...]
    entry_kinds: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[ArtifactProviderDiagnostic, ...]
    disabled_env: tuple[str, ...] = ()

    @property
    def ref_providers_by_id(self) -> dict[str, ArtifactRefProviderRecord]:
        return {provider.provider_id: provider for provider in self.ref_providers}

    @property
    def ref_providers_by_kind(self) -> dict[str, ArtifactRefProviderRecord]:
        return {provider.kind: provider for provider in self.ref_providers}

    @property
    def file_hook_providers_by_id(self) -> dict[str, FileHookProviderRecord]:
        return {provider.provider_id: provider for provider in self.file_hook_providers}


_registry_cache_token: tuple[Any, ...] | None = None
_registry_cache_value: ArtifactProviderRegistry | None = None


def get_artifact_provider_registry() -> ArtifactProviderRegistry:
    """Return the memoized artifact provider registry for the current config."""

    global _registry_cache_token, _registry_cache_value
    token = _provider_registry_token()
    if _registry_cache_value is not None and _registry_cache_token == token:
        return _registry_cache_value
    registry = assemble_artifact_provider_registry()
    _registry_cache_token = token
    _registry_cache_value = registry
    return registry


def reset_artifact_provider_registry_cache() -> None:
    """Clear the process-local artifact provider registry cache."""

    global _registry_cache_token, _registry_cache_value
    _registry_cache_token = None
    _registry_cache_value = None


def assemble_artifact_provider_registry(
    *,
    entry_points_fn: Any = importlib.metadata.entry_points,
) -> ArtifactProviderRegistry:
    """Discover and validate artifact providers."""

    diagnostics: list[ArtifactProviderDiagnostic] = []
    disabled_env: set[str] = set()
    ref_candidates: list[tuple[Mapping[str, Any], ArtifactProviderProvenance]] = []
    file_hook_candidates: list[
        tuple[Mapping[str, Any], ArtifactProviderProvenance]
    ] = []

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
                            f"Failed to load artifact provider entry point "
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

    ref_providers = _validate_ref_providers(ref_candidates, diagnostics)
    file_hook_providers = _validate_file_hook_providers(
        file_hook_candidates,
        diagnostics,
    )
    entry_kinds = _load_entry_kind_descriptors(diagnostics)
    return ArtifactProviderRegistry(
        ref_providers=ref_providers,
        file_hook_providers=file_hook_providers,
        entry_kinds=entry_kinds,
        diagnostics=tuple(diagnostics),
        disabled_env=tuple(sorted(disabled_env)),
    )


def validate_ref_provider_spec(spec: Mapping[str, Any]) -> str:
    """Validate *spec* through Rust and return its stable digest."""

    require_rust_binding("artifact_ref_provider_spec_validate")(dict(spec))
    return str(require_rust_binding("artifact_ref_provider_spec_digest")(dict(spec)))


def _collect_plugin_specs(
    plugin: object,
    provenance: ArtifactProviderProvenance,
    *,
    ref_candidates: list[tuple[Mapping[str, Any], ArtifactProviderProvenance]],
    file_hook_candidates: list[tuple[Mapping[str, Any], ArtifactProviderProvenance]],
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


def _validate_ref_providers(
    candidates: list[tuple[Mapping[str, Any], ArtifactProviderProvenance]],
    diagnostics: list[ArtifactProviderDiagnostic],
) -> tuple[ArtifactRefProviderRecord, ...]:
    providers: list[ArtifactRefProviderRecord] = []
    seen_ids: dict[str, ArtifactRefProviderRecord] = {}
    seen_kinds: dict[str, ArtifactRefProviderRecord] = {}

    for raw_spec, provenance in candidates:
        spec = _plain_mapping(raw_spec)
        provider_id = _spec_text(spec, "provider")
        ref = spec.get("ref")
        kind = _spec_text(ref, "kind") if isinstance(ref, Mapping) else ""
        if not provider_id:
            diagnostics.append(
                _invalid_ref_provider_diagnostic(
                    provenance,
                    provider_id=None,
                    kind=kind or None,
                    reason="'provider' is required and must be a nonempty string",
                )
            )
            continue
        if not kind:
            diagnostics.append(
                _invalid_ref_provider_diagnostic(
                    provenance,
                    provider_id=provider_id,
                    kind=None,
                    reason="'ref.kind' is required and must be a nonempty string",
                )
            )
            continue
        if provider_id in seen_ids:
            diagnostics.append(
                _invalid_ref_provider_diagnostic(
                    provenance,
                    provider_id=provider_id,
                    kind=kind,
                    reason=(
                        f"provider id duplicates {seen_ids[provider_id].provenance.label}"
                    ),
                    code="duplicate_ref_provider",
                )
            )
            continue
        if kind in seen_kinds:
            diagnostics.append(
                _invalid_ref_provider_diagnostic(
                    provenance,
                    provider_id=provider_id,
                    kind=kind,
                    reason=(f"ref kind duplicates {seen_kinds[kind].provenance.label}"),
                    code="duplicate_ref_kind",
                )
            )
            continue
        try:
            digest = validate_ref_provider_spec(spec)
        except Exception as exc:
            diagnostics.append(
                _invalid_ref_provider_diagnostic(
                    provenance,
                    provider_id=provider_id,
                    kind=kind,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        record = ArtifactRefProviderRecord(
            provider_id=provider_id,
            kind=kind,
            digest=digest,
            spec=MappingProxyType(spec),
            provenance=provenance,
        )
        providers.append(record)
        seen_ids[provider_id] = record
        seen_kinds[kind] = record

    return tuple(sorted(providers, key=lambda item: (item.kind, item.provider_id)))


def _validate_file_hook_providers(
    candidates: list[tuple[Mapping[str, Any], ArtifactProviderProvenance]],
    diagnostics: list[ArtifactProviderDiagnostic],
) -> tuple[FileHookProviderRecord, ...]:
    providers: list[FileHookProviderRecord] = []
    seen_ids: dict[str, FileHookProviderRecord] = {}
    for raw_spec, provenance in candidates:
        spec = _plain_mapping(raw_spec)
        provider_id = _spec_text(spec, "provider")
        if not provider_id:
            diagnostics.append(
                _invalid_file_hook_provider_diagnostic(
                    provenance,
                    provider_id=None,
                    reason="'provider' is required and must be a nonempty string",
                )
            )
            continue
        if provider_id in seen_ids:
            diagnostics.append(
                _invalid_file_hook_provider_diagnostic(
                    provenance,
                    provider_id=provider_id,
                    reason=(
                        f"provider id duplicates {seen_ids[provider_id].provenance.label}"
                    ),
                    code="duplicate_file_hook_provider",
                )
            )
            continue
        schema_version = spec.get("schema_version")
        if schema_version != FILE_HOOK_PROVIDER_SPEC_SCHEMA_VERSION:
            diagnostics.append(
                _invalid_file_hook_provider_diagnostic(
                    provenance,
                    provider_id=provider_id,
                    reason=(
                        "unsupported file-hook provider schema_version "
                        f"{schema_version!r}; expected "
                        f"{FILE_HOOK_PROVIDER_SPEC_SCHEMA_VERSION}"
                    ),
                )
            )
            continue
        template = spec.get("file_hook")
        if not isinstance(template, Mapping):
            diagnostics.append(
                _invalid_file_hook_provider_diagnostic(
                    provenance,
                    provider_id=provider_id,
                    reason="'file_hook' is required and must be a mapping",
                )
            )
            continue
        required = spec.get("required", ())
        if required is None:
            required_fields: tuple[str, ...] = ()
        elif isinstance(required, list) and all(
            isinstance(item, str) and item for item in required
        ):
            required_fields = tuple(dict.fromkeys(required))
        else:
            diagnostics.append(
                _invalid_file_hook_provider_diagnostic(
                    provenance,
                    provider_id=provider_id,
                    reason="'required' must be a list of nonempty field names",
                )
            )
            continue
        record = FileHookProviderRecord(
            provider_id=provider_id,
            template=MappingProxyType(_plain_mapping(template)),
            required_fields=required_fields,
            provenance=provenance,
        )
        providers.append(record)
        seen_ids[provider_id] = record
    return tuple(sorted(providers, key=lambda item: item.provider_id))


def _invalid_ref_provider_diagnostic(
    provenance: ArtifactProviderProvenance,
    *,
    provider_id: str | None,
    kind: str | None,
    reason: str,
    code: str = "invalid_ref_provider",
) -> ArtifactProviderDiagnostic:
    return ArtifactProviderDiagnostic(
        code=code,
        message=(
            f"Skipping artifact ref provider {provider_id or '<unknown>'} from "
            f"{provenance.label}: {reason}"
        ),
        severity="error",
        provider=provider_id,
        kind=kind,
        group=provenance.group,
        source=provenance.label,
        package=provenance.package,
        version=provenance.version,
    )


def _invalid_file_hook_provider_diagnostic(
    provenance: ArtifactProviderProvenance,
    *,
    provider_id: str | None,
    reason: str,
    code: str = "invalid_file_hook_provider",
) -> ArtifactProviderDiagnostic:
    return ArtifactProviderDiagnostic(
        code=code,
        message=(
            f"Skipping file-hook provider {provider_id or '<unknown>'} from "
            f"{provenance.label}: {reason}"
        ),
        severity="error",
        provider=provider_id,
        group=provenance.group,
        source=provenance.label,
        package=provenance.package,
        version=provenance.version,
    )


def _load_entry_kind_descriptors(
    diagnostics: list[ArtifactProviderDiagnostic],
) -> tuple[Mapping[str, Any], ...]:
    try:
        raw = require_rust_binding("artifact_ref_kind_catalog")()
    except Exception as exc:
        diagnostics.append(
            ArtifactProviderDiagnostic(
                code="entry_kind_catalog_failed",
                message=(
                    "Failed to load builtin artifact entry-kind descriptors: "
                    f"{type(exc).__name__}: {exc}"
                ),
                severity="error",
            )
        )
        return ()
    if not isinstance(raw, list):
        return ()
    descriptors = tuple(
        MappingProxyType(_plain_mapping(item))
        for item in raw
        if isinstance(item, Mapping)
    )
    return tuple(sorted(descriptors, key=lambda item: str(item.get("kind", ""))))


def _provider_registry_token() -> tuple[Any, ...]:
    return (
        current_config_token(),
        os.environ.get("SASE_DISABLE_PLUGINS"),
        os.environ.get("SASE_DISABLE_PLUGIN_ARTIFACT_REFS"),
        os.environ.get("SASE_DISABLE_PLUGIN_FILE_HOOKS"),
    )


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


def _spec_text(value: object, key: str) -> str:
    if not isinstance(value, Mapping):
        return ""
    raw = value.get(key)
    return raw.strip() if isinstance(raw, str) else ""


def _plain_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        text_key = str(key)
        if isinstance(item, Mapping):
            result[text_key] = _plain_mapping(item)
        elif isinstance(item, list):
            result[text_key] = [
                _plain_mapping(element) if isinstance(element, Mapping) else element
                for element in item
            ]
        else:
            result[text_key] = item
    return result


__all__ = [
    "ARTIFACT_PROVIDER_ENTRY_POINT_GROUPS",
    "ARTIFACT_REF_ENTRY_POINT_GROUP",
    "ArtifactProviderDiagnostic",
    "ArtifactProviderProvenance",
    "ArtifactProviderRegistry",
    "ArtifactRefProviderRecord",
    "FILE_HOOK_ENTRY_POINT_GROUP",
    "FILE_HOOK_PROVIDER_SPEC_SCHEMA_VERSION",
    "FileHookProviderRecord",
    "assemble_artifact_provider_registry",
    "get_artifact_provider_registry",
    "reset_artifact_provider_registry_cache",
    "validate_ref_provider_spec",
]
