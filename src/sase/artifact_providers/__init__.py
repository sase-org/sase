"""Declarative artifact provider discovery and registries."""

from ._builtin import builtin_plan_ref_provider_spec
from ._hookspec import ArtifactProviderHookSpec, hookimpl, hookspec
from .registry import (
    ARTIFACT_PROVIDER_ENTRY_POINT_GROUPS,
    ARTIFACT_REF_ENTRY_POINT_GROUP,
    FILE_HOOK_ENTRY_POINT_GROUP,
    ArtifactProviderDiagnostic,
    ArtifactProviderProvenance,
    ArtifactProviderRegistry,
    ArtifactRefProviderRecord,
    FileHookProviderRecord,
    assemble_artifact_provider_registry,
    get_artifact_provider_registry,
    reset_artifact_provider_registry_cache,
    validate_ref_provider_spec,
)

__all__ = [
    "ARTIFACT_PROVIDER_ENTRY_POINT_GROUPS",
    "ARTIFACT_REF_ENTRY_POINT_GROUP",
    "ArtifactProviderDiagnostic",
    "ArtifactProviderHookSpec",
    "ArtifactProviderProvenance",
    "ArtifactProviderRegistry",
    "ArtifactRefProviderRecord",
    "FILE_HOOK_ENTRY_POINT_GROUP",
    "FileHookProviderRecord",
    "assemble_artifact_provider_registry",
    "builtin_plan_ref_provider_spec",
    "get_artifact_provider_registry",
    "hookimpl",
    "hookspec",
    "reset_artifact_provider_registry_cache",
    "validate_ref_provider_spec",
]
