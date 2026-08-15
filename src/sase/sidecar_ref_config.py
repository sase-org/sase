"""Effective sidecar document-ref provider policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from sase._linked_repo_config import (
    _SIDECAR_ROLE_KEY,
    merged_sidecar_entries_from_config,
)
from sase.sdd._store_types import (
    AGENTS_SIDECAR_ROLE,
    BEADS_SIDECAR_ROLE,
    PLANS_SIDECAR_ROLE,
    document_sidecar_roles,
)

REF_CONFIG_KEY = "ref"
REF_USE_CONFIG_KEY = "use"
REF_ICON_CONFIG_KEY = "icon"
REF_KIND_CONFIG_KEY = "kind"
REF_EXPANSION_FORMAT_CONFIG_KEY = "expansion_format"
REF_PROPERTIES_CONFIG_KEY = "properties"
REF_DETAIL_CONFIG_KEY = "detail"
REF_IDENTITY_CONFIG_KEY = "identity"
REF_INVENTORY_CONFIG_KEY = "inventory"
REF_PUBLICATION_CONFIG_KEY = "publication"
REF_CAPABILITIES_CONFIG_KEY = "capabilities"
REF_XPROMPT_CONFIG_KEY = "xprompt"
REF_FILTERS_CONFIG_KEY = "filters"
REF_PATH_GLOBS_CONFIG_KEY = "path_globs"
REF_INVENTORY_GLOBS_CONFIG_KEY = "globs"

DEFAULT_DOCUMENT_REF_PATH_GLOBS: tuple[str, ...] = ("**/*.md",)
SIDECAR_REF_CONFIG_SOURCE_PREFIX = "sidecar_ref_config:"
DOCUMENT_REF_PROVIDER_SPEC_SCHEMA_VERSION = 1
DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT = "@{checkout_path}"
DEFAULT_DOCUMENT_TAB_ICON = "◆"

# A subset of the Rust expansion vocabulary (sase-core's
# artifact_ref/expansion.rs); the excluded names (project, repository,
# captured_revision, captured_digest, logical_path) have no document-ref
# binding and must be rejected rather than rendered empty.
DOCUMENT_REF_EXPANSION_PLACEHOLDERS = frozenset(
    {
        "kind",
        "argument",
        "canonical_argument",
        "display_label",
        "repo_relative_path",
        "sidecar_role",
        "checkout_path",
    }
)
DOCUMENT_REF_PATH_PLACEHOLDERS = frozenset({"checkout_path"})

_BUILTIN_SIDECAR_REF_KIND = {
    PLANS_SIDECAR_ROLE: "plan",
    BEADS_SIDECAR_ROLE: "bead",
    AGENTS_SIDECAR_ROLE: "agent",
}
_KNOWN_REF_CONFIG_KEYS = frozenset(
    {
        REF_USE_CONFIG_KEY,
        REF_ICON_CONFIG_KEY,
        REF_KIND_CONFIG_KEY,
        REF_EXPANSION_FORMAT_CONFIG_KEY,
        REF_PROPERTIES_CONFIG_KEY,
        REF_DETAIL_CONFIG_KEY,
        REF_IDENTITY_CONFIG_KEY,
        REF_INVENTORY_CONFIG_KEY,
        REF_PUBLICATION_CONFIG_KEY,
        REF_CAPABILITIES_CONFIG_KEY,
        REF_FILTERS_CONFIG_KEY,
        REF_XPROMPT_CONFIG_KEY,
    }
)

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _SidecarRefPolicyDiagnostic:
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
class _SidecarRefPolicyReport:
    """Effective sidecar ref policies plus normalization diagnostics."""

    policies: dict[str, SidecarRefPolicy]
    diagnostics: tuple[_SidecarRefPolicyDiagnostic, ...] = ()


def sidecar_role_ref_kind(role: str) -> str:
    """Return the contextual ref kind for one sidecar role."""
    return _BUILTIN_SIDECAR_REF_KIND.get(role, role)


def sidecar_ref_policy_report(
    config: Mapping[str, Any],
    *,
    primary_workspace_dir: str | Path,
    roles: Iterable[str] = (),
    source_path: str | Path | None = None,
) -> _SidecarRefPolicyReport:
    """Return sidecar ref policies together with fail-soft diagnostics."""

    return _sidecar_ref_policy_report(
        config,
        primary_workspace_dir=primary_workspace_dir,
        roles=roles,
        source_path=source_path,
    )


def effective_sidecar_ref_policies(
    config: Mapping[str, Any],
    *,
    primary_workspace_dir: str | Path,
    roles: Iterable[str] = (),
    source_path: str | Path | None = None,
) -> dict[str, SidecarRefPolicy]:
    """Return enabled role-keyed sidecar ref policies.

    Configured roles are normalized through the same sidecar-entry merger used
    by repository resolution.  Extra *roles* cover implicit/materialized store
    roles such as plans when the sidecar has no explicit config entry.
    """
    report = sidecar_ref_policy_report(
        config,
        primary_workspace_dir=primary_workspace_dir,
        roles=roles,
        source_path=source_path,
    )
    for diagnostic in report.diagnostics:
        log.warning("%s", diagnostic.message)
    return report.policies


def _sidecar_ref_policy_report(
    config: Mapping[str, Any],
    *,
    primary_workspace_dir: str | Path,
    roles: Iterable[str] = (),
    source_path: str | Path | None = None,
) -> _SidecarRefPolicyReport:
    """Return sidecar ref policies and fail-soft diagnostics."""

    from sase.artifact_providers import get_artifact_provider_registry

    primary = str(Path(primary_workspace_dir).expanduser().resolve(strict=False))
    configured = merged_sidecar_entries_from_config(
        config,
        primary_workspace_dir=primary,
    )
    disabled_roles: set[str] = set()
    raw_by_role: dict[str, Mapping[str, Any]] = {}
    ordered_roles: list[str] = []
    for entry in configured:
        role = _entry_role(entry)
        if role is None:
            continue
        if entry.get("disabled") is True:
            disabled_roles.add(role)
            continue
        raw_by_role[role] = entry
        ordered_roles.append(role)

    for role in roles:
        clean = role.strip() if isinstance(role, str) else ""
        if not clean or clean in disabled_roles:
            continue
        ordered_roles.append(clean)

    unique_roles = tuple(dict.fromkeys(ordered_roles))
    document_roles = set(document_sidecar_roles(unique_roles, include_plans=True))
    location = None if source_path is None else str(source_path)
    registry = get_artifact_provider_registry()
    diagnostics: list[_SidecarRefPolicyDiagnostic] = []
    policies: dict[str, SidecarRefPolicy] = {}
    for role in unique_roles:
        policy = _policy_for_role(
            role,
            raw_by_role.get(role, {}),
            is_document=role in document_roles,
            source_path=location,
            registry=registry,
            diagnostics=diagnostics,
        )
        if policy is not None:
            policies[role] = policy
    return _SidecarRefPolicyReport(policies, tuple(diagnostics))


def _policy_for_role(
    role: str,
    entry: Mapping[str, Any],
    *,
    is_document: bool,
    source_path: str | None,
    registry: Any,
    diagnostics: list[_SidecarRefPolicyDiagnostic],
) -> SidecarRefPolicy | None:
    ref_kind = sidecar_role_ref_kind(role)
    if not is_document:
        _non_document_ref_diagnostics(role, entry, diagnostics)
        return SidecarRefPolicy(
            role=role,
            ref_kind=ref_kind,
            is_document=False,
            source_path=source_path,
        )

    ref_config = entry.get(REF_CONFIG_KEY)
    normalized = _normalize_document_ref_spec(
        role,
        ref_config,
        registry=registry,
        diagnostics=diagnostics,
    )
    if normalized is None:
        return None
    spec, digest, path_globs_configured = normalized
    ref_mapping = spec["ref"]
    kind = ref_mapping[REF_KIND_CONFIG_KEY]
    provider_id = str(spec["provider"])
    path_globs = _path_globs(
        (ref_mapping.get(REF_INVENTORY_CONFIG_KEY) or {}).get(
            REF_INVENTORY_GLOBS_CONFIG_KEY
        )
        if isinstance(ref_mapping.get(REF_INVENTORY_CONFIG_KEY), Mapping)
        else None
    )
    return SidecarRefPolicy(
        role=role,
        ref_kind=str(kind),
        is_document=True,
        provider_id=provider_id,
        spec=spec,
        digest=digest,
        path_globs=path_globs,
        path_globs_configured=path_globs_configured,
        source_path=source_path,
    )


def _normalize_document_ref_spec(
    role: str,
    ref_config: object,
    *,
    registry: Any,
    diagnostics: list[_SidecarRefPolicyDiagnostic],
) -> tuple[dict[str, Any], str, bool] | None:
    from sase.artifact_providers import validate_ref_provider_spec

    if ref_config is None:
        spec = _default_document_spec(role, registry)
        path_globs_configured = False
    elif not isinstance(ref_config, Mapping):
        diagnostics.append(
            _diagnostic(
                role,
                "ref",
                "sidecar ref config must be a mapping",
            )
        )
        return None
    else:
        raw_use = ref_config.get(REF_USE_CONFIG_KEY)
        if raw_use is not None:
            if not isinstance(raw_use, str) or not raw_use.strip():
                diagnostics.append(
                    _diagnostic(
                        role,
                        "ref.use",
                        "sidecar ref provider use value must be a nonempty string",
                    )
                )
                return None
            provider_id = raw_use.strip()
            provider = registry.ref_providers_by_id.get(provider_id)
            if provider is None:
                diagnostics.append(
                    _diagnostic(
                        role,
                        "ref.use",
                        (
                            f"artifact ref provider '{provider_id}' is not installed; "
                            "a cloned sidecar repo does not install a provider plugin. "
                            "Install a plugin exposing the sase_artifact_refs entry "
                            "point group or replace this with an inline ref spec"
                        ),
                        code="missing_ref_provider",
                        provider=provider_id,
                    )
                )
                return None
            base = _plain_mapping(provider.spec)
        else:
            base = _default_document_spec(role, registry, prefer_registry=False)
        override_result = _ref_override(
            role,
            ref_config,
            diagnostics,
        )
        if override_result is None:
            return None
        override, path_globs_configured = override_result
        spec = _deep_merge(base, {"ref": override})
    try:
        digest = validate_ref_provider_spec(spec)
    except Exception as exc:
        diagnostics.append(
            _diagnostic(
                role,
                "ref",
                f"invalid artifact ref provider spec: {type(exc).__name__}: {exc}",
                provider=_entry_text(spec, "provider") or None,
            )
        )
        return None
    expansion_format = str(spec["ref"][REF_EXPANSION_FORMAT_CONFIG_KEY])
    from sase.artifact_ref_operations import artifact_ref_expansion_validate

    try:
        used_placeholders = set(artifact_ref_expansion_validate(expansion_format))
    except Exception as exc:
        diagnostics.append(
            _diagnostic(
                role,
                "ref.expansion_format",
                f"invalid expansion format: {type(exc).__name__}: {exc}",
            )
        )
        return None
    unsupported = sorted(used_placeholders - DOCUMENT_REF_EXPANSION_PLACEHOLDERS)
    if unsupported:
        diagnostics.append(
            _diagnostic(
                role,
                "ref.expansion_format",
                f"unsupported expansion placeholder(s): {', '.join(unsupported)}",
            )
        )
        return None
    return spec, digest, path_globs_configured


def _default_document_spec(
    role: str,
    registry: Any,
    *,
    prefer_registry: bool = True,
) -> dict[str, Any]:
    kind = sidecar_role_ref_kind(role)
    if prefer_registry:
        provider = registry.ref_providers_by_id.get(
            kind
        ) or registry.ref_providers_by_kind.get(kind)
        if provider is not None:
            return _plain_mapping(provider.spec)
    return {
        "schema_version": DOCUMENT_REF_PROVIDER_SPEC_SCHEMA_VERSION,
        "provider": _provider_id_for_role(kind),
        "ref": {
            "kind": kind,
            "icon": DEFAULT_DOCUMENT_TAB_ICON,
            "expansion_format": DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT,
            "properties": {},
            "detail": {},
            "identity": {},
            "inventory": {"globs": list(DEFAULT_DOCUMENT_REF_PATH_GLOBS)},
            "publication": {
                "link": "vcs_permalink",
                "referenced_by": "markdown_table",
            },
        },
    }


def _ref_override(
    role: str,
    ref_config: Mapping[Any, Any],
    diagnostics: list[_SidecarRefPolicyDiagnostic],
) -> tuple[dict[str, Any], bool] | None:
    unknown = sorted(
        str(key) for key in ref_config if str(key) not in _KNOWN_REF_CONFIG_KEYS
    )
    if unknown:
        diagnostics.append(
            _diagnostic(
                role,
                "ref",
                f"unknown sidecar ref field(s): {', '.join(unknown)}",
            )
        )
        return None
    if REF_XPROMPT_CONFIG_KEY in ref_config:
        diagnostics.append(
            _diagnostic(
                role,
                f"ref.{REF_XPROMPT_CONFIG_KEY}",
                "ref.xprompt was retired; use provider-backed or inline ref specs",
                code="retired_ref_xprompt",
            )
        )
        return None

    override = {
        str(key): _plain_value(value)
        for key, value in ref_config.items()
        if key not in {REF_USE_CONFIG_KEY, REF_FILTERS_CONFIG_KEY}
    }
    path_globs_configured = False
    filters = ref_config.get(REF_FILTERS_CONFIG_KEY)
    if filters is not None:
        if not isinstance(filters, Mapping):
            diagnostics.append(
                _diagnostic(role, "ref.filters", "ref.filters must be a mapping")
            )
            return None
        filter_unknown = sorted(
            str(key) for key in filters if str(key) != REF_PATH_GLOBS_CONFIG_KEY
        )
        if filter_unknown:
            diagnostics.append(
                _diagnostic(
                    role,
                    "ref.filters",
                    f"unknown ref.filters field(s): {', '.join(filter_unknown)}",
                )
            )
            return None
        if REF_PATH_GLOBS_CONFIG_KEY in filters:
            path_globs_configured = True
            inventory = override.get(REF_INVENTORY_CONFIG_KEY)
            if not isinstance(inventory, dict):
                inventory = {}
                override[REF_INVENTORY_CONFIG_KEY] = inventory
            inventory.setdefault(
                REF_INVENTORY_GLOBS_CONFIG_KEY,
                _plain_value(filters[REF_PATH_GLOBS_CONFIG_KEY]),
            )
            diagnostics.append(
                _diagnostic(
                    role,
                    "ref.filters.path_globs",
                    ("ref.filters.path_globs is deprecated; use ref.inventory.globs"),
                    code="deprecated_ref_path_globs",
                )
            )

    inventory = override.get(REF_INVENTORY_CONFIG_KEY)
    if isinstance(inventory, Mapping) and REF_INVENTORY_GLOBS_CONFIG_KEY in inventory:
        path_globs_configured = True
    return override, path_globs_configured


def _non_document_ref_diagnostics(
    role: str,
    entry: Mapping[str, Any],
    diagnostics: list[_SidecarRefPolicyDiagnostic],
) -> None:
    if REF_CONFIG_KEY not in entry:
        return
    raw_ref = entry.get(REF_CONFIG_KEY)
    if not isinstance(raw_ref, Mapping):
        diagnostics.append(
            _diagnostic(role, "ref", "sidecar ref config must be a mapping")
        )
        return
    if REF_FILTERS_CONFIG_KEY in raw_ref or REF_INVENTORY_CONFIG_KEY in raw_ref:
        diagnostics.append(
            _diagnostic(
                role,
                "ref",
                (
                    f"document ref filters are not supported for {role!r}; "
                    "bead and agent refs are entity-backed"
                ),
            )
        )


def _entry_role(entry: Mapping[str, Any]) -> str | None:
    value = entry.get(_SIDECAR_ROLE_KEY) or entry.get("name")
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _path_globs(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = _plain_mapping(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = _plain_value(value)
    return result


def _plain_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(key): _plain_value(item) for key, item in value.items()}


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _plain_mapping(value)
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    return value


def _provider_id_for_role(role: str) -> str:
    cleaned = "".join(
        char if char.islower() or char.isdigit() or char in {"_", "-"} else "-"
        for char in role.lower()
    ).strip("-_")
    if cleaned and cleaned[0].islower():
        return cleaned
    return f"sidecar-{cleaned or 'document'}"


def _diagnostic(
    role: str,
    suffix: str,
    message: str,
    *,
    code: str = "invalid_sidecar_ref",
    provider: str | None = None,
) -> _SidecarRefPolicyDiagnostic:
    return _SidecarRefPolicyDiagnostic(
        key=f"repos.sidecar.<bucket>.{role}.{suffix}",
        message=message,
        code=code,
        role=role,
        provider=provider,
    )


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "DEFAULT_DOCUMENT_REF_PATH_GLOBS",
    "DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT",
    "DEFAULT_DOCUMENT_TAB_ICON",
    "DOCUMENT_REF_EXPANSION_PLACEHOLDERS",
    "DOCUMENT_REF_PATH_PLACEHOLDERS",
    "DOCUMENT_REF_PROVIDER_SPEC_SCHEMA_VERSION",
    "REF_DETAIL_CONFIG_KEY",
    "REF_EXPANSION_FORMAT_CONFIG_KEY",
    "REF_CONFIG_KEY",
    "REF_FILTERS_CONFIG_KEY",
    "REF_ICON_CONFIG_KEY",
    "REF_IDENTITY_CONFIG_KEY",
    "REF_INVENTORY_CONFIG_KEY",
    "REF_INVENTORY_GLOBS_CONFIG_KEY",
    "REF_KIND_CONFIG_KEY",
    "REF_PATH_GLOBS_CONFIG_KEY",
    "REF_PROPERTIES_CONFIG_KEY",
    "REF_PUBLICATION_CONFIG_KEY",
    "REF_USE_CONFIG_KEY",
    "REF_XPROMPT_CONFIG_KEY",
    "SIDECAR_REF_CONFIG_SOURCE_PREFIX",
    "SidecarRefPolicy",
    "effective_sidecar_ref_policies",
    "sidecar_ref_policy_report",
    "sidecar_role_ref_kind",
]
