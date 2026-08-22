"""Public API for effective sidecar document-ref provider policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import logging
from pathlib import Path
from typing import Any

from sase._linked_repo_config import merged_sidecar_entries_from_config
from sase._sidecar_ref_constants import (
    DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT,
    DEFAULT_DOCUMENT_REF_PATH_GLOBS,
    DEFAULT_DOCUMENT_TAB_ICON,
    DOCUMENT_REF_EXPANSION_PLACEHOLDERS,
    DOCUMENT_REF_PATH_PLACEHOLDERS,
    DOCUMENT_REF_PROVIDER_SPEC_SCHEMA_VERSION,
    REF_CAPABILITIES_CONFIG_KEY,
    REF_CONFIG_KEY,
    REF_DETAIL_CONFIG_KEY,
    REF_EXPANSION_FORMAT_CONFIG_KEY,
    REF_FILTERS_CONFIG_KEY,
    REF_GROUPING_CONFIG_KEY,
    REF_ICON_CONFIG_KEY,
    REF_IDENTITY_CONFIG_KEY,
    REF_INVENTORY_CONFIG_KEY,
    REF_INVENTORY_GLOBS_CONFIG_KEY,
    REF_KIND_CONFIG_KEY,
    REF_PANE_CONFIG_KEY,
    REF_PATH_GLOBS_CONFIG_KEY,
    REF_PROPERTIES_CONFIG_KEY,
    REF_PUBLICATION_CONFIG_KEY,
    REF_RELATIONS_CONFIG_KEY,
    REF_USE_CONFIG_KEY,
    REF_XPROMPT_CONFIG_KEY,
    SIDECAR_REF_CONFIG_SOURCE_PREFIX,
)
from sase._sidecar_ref_normalization import entry_role, policy_for_role
from sase._sidecar_ref_policy import (
    SidecarRefPolicy,
    SidecarRefPolicyDiagnostic,
    SidecarRefPolicyReport,
    sidecar_role_for_ref_kind,
    sidecar_role_ref_kind,
)
from sase.sdd._store_types import document_sidecar_roles

log = logging.getLogger(__name__)


def sidecar_ref_policy_report(
    config: Mapping[str, Any],
    *,
    primary_workspace_dir: str | Path,
    roles: Iterable[str] = (),
    source_path: str | Path | None = None,
) -> SidecarRefPolicyReport:
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
    by repository resolution. Extra *roles* cover implicit/materialized store
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
) -> SidecarRefPolicyReport:
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
        role = entry_role(entry)
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
    diagnostics: list[SidecarRefPolicyDiagnostic] = []
    policies: dict[str, SidecarRefPolicy] = {}
    for role in unique_roles:
        policy = policy_for_role(
            role,
            raw_by_role.get(role, {}),
            is_document=role in document_roles,
            source_path=location,
            registry=registry,
            diagnostics=diagnostics,
        )
        if policy is not None:
            policies[role] = policy
    return SidecarRefPolicyReport(policies, tuple(diagnostics))


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
    "REF_PANE_CONFIG_KEY",
    "REF_PROPERTIES_CONFIG_KEY",
    "REF_PUBLICATION_CONFIG_KEY",
    "REF_USE_CONFIG_KEY",
    "REF_XPROMPT_CONFIG_KEY",
    "SIDECAR_REF_CONFIG_SOURCE_PREFIX",
    "SidecarRefPolicy",
    "effective_sidecar_ref_policies",
    "sidecar_ref_policy_report",
    "sidecar_role_for_ref_kind",
    "sidecar_role_ref_kind",
]
