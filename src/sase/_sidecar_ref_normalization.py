"""Normalization and validation helpers for sidecar ref policies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase._linked_repo_config import _SIDECAR_ROLE_KEY
from sase._sidecar_ref_constants import (
    DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT,
    DEFAULT_DOCUMENT_REF_PATH_GLOBS,
    DEFAULT_DOCUMENT_TAB_ICON,
    DOCUMENT_REF_EXPANSION_PLACEHOLDERS,
    DOCUMENT_REF_PROVIDER_SPEC_SCHEMA_VERSION,
    KNOWN_REF_CONFIG_KEYS,
    REF_CONFIG_KEY,
    REF_EXPANSION_FORMAT_CONFIG_KEY,
    REF_FILTERS_CONFIG_KEY,
    REF_INVENTORY_CONFIG_KEY,
    REF_INVENTORY_GLOBS_CONFIG_KEY,
    REF_KIND_CONFIG_KEY,
    REF_PATH_GLOBS_CONFIG_KEY,
    REF_USE_CONFIG_KEY,
    REF_XPROMPT_CONFIG_KEY,
)
from sase._sidecar_ref_policy import (
    SidecarRefPolicy,
    SidecarRefPolicyDiagnostic,
    sidecar_role_ref_kind,
)
from sase.plugins.qualified_id import (
    PluginQualifiedIdError,
    parse_plugin_qualified_id,
    plugin_qualified_id_matches,
)


def policy_for_role(
    role: str,
    entry: Mapping[str, Any],
    *,
    is_document: bool,
    source_path: str | None,
    registry: Any,
    diagnostics: list[SidecarRefPolicyDiagnostic],
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
    diagnostics: list[SidecarRefPolicyDiagnostic],
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
            raw_use_value = raw_use.strip()
            try:
                plugin, provider_id = parse_plugin_qualified_id(raw_use_value)
            except PluginQualifiedIdError:
                diagnostics.append(
                    _diagnostic(
                        role,
                        "ref.use",
                        _missing_use_prefix_message(raw_use_value, registry),
                        code="missing_use_prefix",
                    )
                )
                return None
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
            if not plugin_qualified_id_matches(
                plugin,
                builtin=provider.provenance.builtin,
                package=provider.provenance.package,
            ):
                diagnostics.append(
                    _diagnostic(
                        role,
                        "ref.use",
                        _mismatched_use_prefix_message(plugin, provider_id, provider),
                        code="mismatched_use_prefix",
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
    diagnostics: list[SidecarRefPolicyDiagnostic],
) -> tuple[dict[str, Any], bool] | None:
    unknown = sorted(
        str(key) for key in ref_config if str(key) not in KNOWN_REF_CONFIG_KEYS
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
    diagnostics: list[SidecarRefPolicyDiagnostic],
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


def entry_role(entry: Mapping[str, Any]) -> str | None:
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


def _missing_use_prefix_message(value: str, registry: Any) -> str:
    provider = registry.ref_providers_by_id.get(value)
    if provider is not None:
        prefix = (
            "builtin" if provider.provenance.builtin else provider.provenance.package
        )
        return f"{value!r} is missing its plugin prefix; use {f'{prefix}@{value}'!r}"
    return (
        f"{value!r} is missing its required plugin prefix; use "
        "'<plugin>@<id>' where <plugin> is 'builtin' or an installed "
        "distribution name"
    )


def _mismatched_use_prefix_message(plugin: str, provider_id: str, provider: Any) -> str:
    actual = "builtin" if provider.provenance.builtin else provider.provenance.package
    return (
        f"artifact ref provider '{provider_id}' is provided by {actual!r}, not "
        f"{plugin!r}; use {f'{actual}@{provider_id}'!r}"
    )


def _diagnostic(
    role: str,
    suffix: str,
    message: str,
    *,
    code: str = "invalid_sidecar_ref",
    provider: str | None = None,
) -> SidecarRefPolicyDiagnostic:
    return SidecarRefPolicyDiagnostic(
        key=f"repos.sidecar.<bucket>.{role}.{suffix}",
        message=message,
        code=code,
        role=role,
        provider=provider,
    )


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""
