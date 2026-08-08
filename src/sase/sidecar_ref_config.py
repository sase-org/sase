"""Effective sidecar ref renderer and document-filter policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase._linked_repo_config import (
    _SIDECAR_ROLE_KEY,
    merged_sidecar_entries_from_config,
)
from sase.sdd._store_types import (
    AGENTS_SIDECAR_ROLE,
    BEADS_SIDECAR_ROLE,
    document_sidecar_roles,
)

REF_CONFIG_KEY = "ref"
REF_XPROMPT_CONFIG_KEY = "xprompt"
REF_FILTERS_CONFIG_KEY = "filters"
REF_PATH_GLOBS_CONFIG_KEY = "path_globs"

DEFAULT_DOCUMENT_REF_PATH_GLOBS: tuple[str, ...] = ("**/*.md",)
DEFAULT_DOCUMENT_REF_RENDERER = (
    "the {{ file_path }} file in the {{ sidecar }} sidecar repo"
)
SIDECAR_REF_CONFIG_SOURCE_PREFIX = "sidecar_ref_config:"

BUILTIN_REF_INPUTS: dict[str, str] = {
    "commit": "commit",
    "chat": "file_path",
    "bug": "bug",
    "file": "artifact_id",
    "bead": "bead_id",
    "agent": "agent_name",
}

_BUILTIN_SIDECAR_REF_KIND = {
    BEADS_SIDECAR_ROLE: "bead",
    AGENTS_SIDECAR_ROLE: "agent",
}


@dataclass(frozen=True, slots=True)
class SidecarRefPolicy:
    """One enabled sidecar role's effective contextual ref policy."""

    role: str
    ref_kind: str
    is_document: bool
    xprompt: str | None = None
    path_globs: tuple[str, ...] | None = None
    path_globs_configured: bool = False
    source_path: str | None = None

    @property
    def source_id(self) -> str:
        return f"{SIDECAR_REF_CONFIG_SOURCE_PREFIX}{self.role}"


def _sidecar_role_ref_kind(role: str) -> str:
    """Return the contextual ref kind for one sidecar role."""
    return _BUILTIN_SIDECAR_REF_KIND.get(role, role)


def canonical_ref_input(ref_kind: str) -> str:
    """Return the registry-owned single input name for a ref kind."""
    return BUILTIN_REF_INPUTS.get(ref_kind, "file_path")


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
    return {
        role: _policy_for_role(
            role,
            raw_by_role.get(role, {}),
            is_document=role in document_roles,
            source_path=location,
        )
        for role in unique_roles
    }


def _policy_for_role(
    role: str,
    entry: Mapping[str, Any],
    *,
    is_document: bool,
    source_path: str | None,
) -> SidecarRefPolicy:
    ref_config = entry.get(REF_CONFIG_KEY)
    ref_mapping = ref_config if isinstance(ref_config, Mapping) else {}
    filters = ref_mapping.get(REF_FILTERS_CONFIG_KEY)
    filter_mapping = filters if isinstance(filters, Mapping) else {}
    path_globs_configured = REF_PATH_GLOBS_CONFIG_KEY in filter_mapping
    configured_globs = _path_globs(filter_mapping.get(REF_PATH_GLOBS_CONFIG_KEY))
    path_globs = None
    if is_document:
        path_globs = (
            configured_globs
            if path_globs_configured
            else DEFAULT_DOCUMENT_REF_PATH_GLOBS
        )
    xprompt = ref_mapping.get(REF_XPROMPT_CONFIG_KEY)
    return SidecarRefPolicy(
        role=role,
        ref_kind=_sidecar_role_ref_kind(role),
        is_document=is_document,
        xprompt=xprompt.strip()
        if isinstance(xprompt, str) and xprompt.strip()
        else None,
        path_globs=path_globs,
        path_globs_configured=path_globs_configured,
        source_path=source_path,
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


__all__ = [
    "BUILTIN_REF_INPUTS",
    "DEFAULT_DOCUMENT_REF_PATH_GLOBS",
    "DEFAULT_DOCUMENT_REF_RENDERER",
    "REF_CONFIG_KEY",
    "REF_FILTERS_CONFIG_KEY",
    "REF_PATH_GLOBS_CONFIG_KEY",
    "REF_XPROMPT_CONFIG_KEY",
    "SIDECAR_REF_CONFIG_SOURCE_PREFIX",
    "SidecarRefPolicy",
    "canonical_ref_input",
    "effective_sidecar_ref_policies",
]
