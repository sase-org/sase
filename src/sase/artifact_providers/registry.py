"""Artifact provider registry assembly and public API."""

from __future__ import annotations

import importlib.metadata
import os
from typing import Any

from sase.config.core import current_config_token

from ._discovery import (
    ARTIFACT_PROVIDER_ENTRY_POINT_GROUPS,
    ARTIFACT_REF_ENTRY_POINT_GROUP,
    FILE_HOOK_ENTRY_POINT_GROUP,
    discover_artifact_provider_specs,
)
from ._models import (
    ArtifactProviderDiagnostic,
    ArtifactProviderProvenance,
    ArtifactProviderRegistry,
    ArtifactRefProviderRecord,
    FileHookProviderRecord,
)
from ._validation import (
    FILE_HOOK_PROVIDER_SPEC_SCHEMA_VERSION,
    load_entry_kind_descriptors,
    validate_file_hook_providers,
    validate_ref_provider_spec,
    validate_ref_providers,
)

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

    discovery = discover_artifact_provider_specs(entry_points_fn=entry_points_fn)
    diagnostics = list(discovery.diagnostics)
    ref_providers = validate_ref_providers(
        discovery.ref_candidates,
        diagnostics,
    )
    file_hook_providers = validate_file_hook_providers(
        discovery.file_hook_candidates,
        diagnostics,
    )
    entry_kinds = load_entry_kind_descriptors(diagnostics)
    return ArtifactProviderRegistry(
        ref_providers=ref_providers,
        file_hook_providers=file_hook_providers,
        entry_kinds=entry_kinds,
        diagnostics=tuple(diagnostics),
        disabled_env=discovery.disabled_env,
    )


def _provider_registry_token() -> tuple[Any, ...]:
    return (
        current_config_token(),
        os.environ.get("SASE_DISABLE_PLUGINS"),
        os.environ.get("SASE_DISABLE_PLUGIN_ARTIFACT_REFS"),
        os.environ.get("SASE_DISABLE_PLUGIN_FILE_HOOKS"),
    )


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
