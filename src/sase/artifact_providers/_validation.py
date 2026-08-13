"""Validation and normalization for discovered artifact-provider specs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sidecar_ref_config import DEFAULT_DOCUMENT_TAB_ICON

from ._models import (
    ArtifactProviderDiagnostic,
    ArtifactProviderProvenance,
    ArtifactRefProviderRecord,
    FileHookProviderRecord,
)

FILE_HOOK_PROVIDER_SPEC_SCHEMA_VERSION = 1

ProviderCandidate = tuple[Mapping[str, Any], ArtifactProviderProvenance]


def validate_ref_provider_spec(spec: Mapping[str, Any]) -> str:
    """Validate *spec* through Rust and return its stable digest."""

    require_rust_binding("artifact_ref_provider_spec_validate")(dict(spec))
    return str(require_rust_binding("artifact_ref_provider_spec_digest")(dict(spec)))


def validate_ref_providers(
    candidates: Sequence[ProviderCandidate],
    diagnostics: list[ArtifactProviderDiagnostic],
) -> tuple[ArtifactRefProviderRecord, ...]:
    """Validate and deduplicate artifact-reference provider candidates."""

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
                    reason=f"ref kind duplicates {seen_kinds[kind].provenance.label}",
                    code="duplicate_ref_kind",
                )
            )
            continue
        _ensure_compat_ref_provider_icon(
            spec,
            provenance,
            diagnostics,
            provider_id=provider_id,
            kind=kind,
        )
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


def _ensure_compat_ref_provider_icon(
    spec: dict[str, Any],
    provenance: ArtifactProviderProvenance,
    diagnostics: list[ArtifactProviderDiagnostic],
    *,
    provider_id: str,
    kind: str,
) -> None:
    ref = spec.get("ref")
    if not isinstance(ref, dict):
        return
    raw_icon = ref.get("icon")
    if isinstance(raw_icon, str) and raw_icon:
        return

    # Compatibility shim for providers released before ref.icon became
    # required. Remove once no supported plugins rely on icon-less specs.
    ref["icon"] = DEFAULT_DOCUMENT_TAB_ICON
    diagnostics.append(
        ArtifactProviderDiagnostic(
            code="missing_ref_provider_icon",
            message=(
                f"Artifact ref provider {provider_id!r} from {provenance.label} "
                "omits ref.icon; using generic Artifacts tab icon "
                f"{DEFAULT_DOCUMENT_TAB_ICON!r} during the compatibility window"
            ),
            severity="warning",
            provider=provider_id,
            kind=kind,
            group=provenance.group,
            source=provenance.label,
            package=provenance.package,
            version=provenance.version,
        )
    )


def validate_file_hook_providers(
    candidates: Sequence[ProviderCandidate],
    diagnostics: list[ArtifactProviderDiagnostic],
) -> tuple[FileHookProviderRecord, ...]:
    """Validate and deduplicate file-hook provider candidates."""

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


def load_entry_kind_descriptors(
    diagnostics: list[ArtifactProviderDiagnostic],
) -> tuple[Mapping[str, Any], ...]:
    """Load builtin artifact entry-kind descriptors from the Rust core."""

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
    "FILE_HOOK_PROVIDER_SPEC_SCHEMA_VERSION",
    "load_entry_kind_descriptors",
    "validate_file_hook_providers",
    "validate_ref_provider_spec",
    "validate_ref_providers",
]
