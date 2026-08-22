"""Data models and role naming for sidecar ref policies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase._sidecar_ref_constants import (
    BUILTIN_SIDECAR_REF_KIND,
    DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT,
    DOCUMENT_REF_PATH_PLACEHOLDERS,
    REF_EXPANSION_FORMAT_CONFIG_KEY,
    SIDECAR_REF_CONFIG_SOURCE_PREFIX,
)


@dataclass(frozen=True, slots=True)
class SidecarRefPolicyDiagnostic:
    """One diagnostic produced while normalizing sidecar ref config."""

    key: str
    message: str
    code: str = "invalid_sidecar_ref"
    role: str | None = None
    provider: str | None = None


@dataclass(frozen=True, slots=True)
class SidecarRefPolicy:
    """One enabled sidecar role's effective document-ref policy."""

    role: str
    ref_kind: str
    is_document: bool
    provider_id: str | None = None
    spec: Mapping[str, Any] | None = None
    digest: str | None = None
    path_globs: tuple[str, ...] | None = None
    path_globs_configured: bool = False
    source_path: str | None = None
    xprompt: str | None = None

    @property
    def source_id(self) -> str:
        return f"{SIDECAR_REF_CONFIG_SOURCE_PREFIX}{self.role}"

    @property
    def expansion_format(self) -> str:
        ref = self.spec.get("ref") if self.spec is not None else None
        if isinstance(ref, Mapping):
            value = ref.get(REF_EXPANSION_FORMAT_CONFIG_KEY)
            if isinstance(value, str) and value:
                return value
        return DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT

    @property
    def is_pointer_expansion(self) -> bool:
        from sase.artifact_ref_operations import artifact_ref_expansion_validate

        try:
            placeholders = set(artifact_ref_expansion_validate(self.expansion_format))
        except Exception:
            return False
        return not (placeholders & DOCUMENT_REF_PATH_PLACEHOLDERS)


@dataclass(frozen=True, slots=True)
class SidecarRefPolicyReport:
    """Effective sidecar ref policies plus normalization diagnostics."""

    policies: dict[str, SidecarRefPolicy]
    diagnostics: tuple[SidecarRefPolicyDiagnostic, ...] = ()


def sidecar_role_ref_kind(role: str) -> str:
    """Return the contextual ref kind for one sidecar role."""
    return BUILTIN_SIDECAR_REF_KIND.get(role, role)


def sidecar_role_for_ref_kind(kind: str) -> str:
    """Return the sidecar role that exposes *kind*, or *kind* itself."""

    for role, ref_kind in BUILTIN_SIDECAR_REF_KIND.items():
        if ref_kind == kind:
            return role
    return kind
