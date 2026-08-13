"""Data models shared by artifact-provider registry components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from collections.abc import Mapping

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


__all__ = [
    "ArtifactProviderDiagnostic",
    "ArtifactProviderProvenance",
    "ArtifactProviderRegistry",
    "ArtifactRefProviderRecord",
    "DiagnosticSeverity",
    "FileHookProviderRecord",
]
