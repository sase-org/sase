"""Linked and sidecar entry merging for repository configuration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from sase._linked_repo_config_keys import (
    DEFAULT_LINKED_REPO_MARKER,
    HIDDEN_SIDECAR_ROLES,
    LINKED_REPOS_CONFIG_KEY,
    REPOS_CONFIG_KEY,
    REPOS_LINKED_CONFIG_KEY,
    REPOS_SIDECAR_CONFIG_KEY,
    REVISION_PIN_CONFIG_KEY,
    SIBLING_REPOS_CONFIG_KEY,
    SIDECAR_BUILTIN_CONFIG_KEY,
    SIDECAR_CUSTOM_CONFIG_KEY,
    SIDECAR_REMOTE_URL_KEY,
    SIDECAR_REPO_MARKER,
    SIDECAR_REPO_REF_KEY,
    SIDECAR_ROLE_KEY,
    SIDECAR_SLUG_KEY,
    optional_entry_text,
)
from sase._linked_repo_config_state import (
    RepoConfigCacheKey,
    repo_config_cache_key,
)
from sase._linked_repo_identity import resolve_sidecar_repo_identity
from sase.sdd._store_types import (
    AGENTS_SIDECAR_ROLE,
    ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
    ATTACHMENTS_SIDECAR_ROLE,
    BEADS_SIDECAR_ROLE,
    PLANS_SIDECAR_ROLE,
)

#: Canonical emission order for ``repos.sidecar.builtin`` roles. Sidecar order
#: is user-visible (repo inventory rows, generated agent instructions), so the
#: reserved bucket is emitted in this fixed order rather than authoring order.
_BUILTIN_SIDECAR_ROLE_ORDER: tuple[str, ...] = (
    PLANS_SIDECAR_ROLE,
    BEADS_SIDECAR_ROLE,
    AGENTS_SIDECAR_ROLE,
    ATTACHMENTS_SIDECAR_ROLE,
    ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
)


def merged_linked_entries_from_config(
    config: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], list[str]]:
    """Merge ``repos.linked`` with its deprecated top-level aliases.

    Within a single key, exact duplicates are deduped but distinct same-name
    entries remain. Across keys, the precedence chain is ``repos.linked``,
    ``linked_repos``, then ``sibling_repos``. Divergent lower-precedence
    entries with the same name produce a non-fatal warning.
    """

    sources = (
        (
            "repos.linked",
            _dedupe_entries(_entries_for_repos_key(config, REPOS_LINKED_CONFIG_KEY)),
        ),
        (
            LINKED_REPOS_CONFIG_KEY,
            _dedupe_entries(_entries_for_key(config, LINKED_REPOS_CONFIG_KEY)),
        ),
        (
            SIBLING_REPOS_CONFIG_KEY,
            _dedupe_entries(_entries_for_key(config, SIBLING_REPOS_CONFIG_KEY)),
        ),
    )
    merged: list[Mapping[str, Any]] = []
    selected_by_name: dict[str, tuple[str, Mapping[str, Any]]] = {}
    warnings: list[str] = []
    for source_name, entries in sources:
        for entry in entries:
            name = entry.get("name")
            key_name = name.strip() if isinstance(name, str) else ""
            selected = selected_by_name.get(key_name) if key_name else None
            if selected is not None:
                selected_source, selected_entry = selected
                if not _entries_equivalent(selected_entry, entry):
                    warnings.append(
                        f"Linked repo {key_name!r} is defined in both "
                        f"{selected_source} and {source_name} with different "
                        f"settings; using the {selected_source} definition and "
                        f"ignoring the {source_name} one"
                    )
                continue
            merged.append(entry)
            if key_name:
                selected_by_name[key_name] = (source_name, entry)

    return merged, warnings


def merged_sidecar_entries_from_config(
    config: Mapping[str, Any],
    *,
    primary_workspace_dir: str,
) -> list[Mapping[str, Any]]:
    """Return normalized ``repos.sidecar`` entries.

    ``repos.sidecar`` is a mapping keyed by role, so config layers already
    merged per key before this point and no entry-level merging is needed here.
    A disabled entry deliberately remains in the result so it can suppress
    implicit or store-record fallbacks.
    """

    primary = str(Path(primary_workspace_dir).expanduser().resolve(strict=False))
    cached = _merged_sidecar_entries_cached(primary, repo_config_cache_key(config))
    return [dict(entry) for entry in cached]


@lru_cache(maxsize=256)
def _merged_sidecar_entries_cached(
    primary_workspace_dir: str,
    config_key: RepoConfigCacheKey,
) -> tuple[Mapping[str, Any], ...]:
    config = config_key.config
    normalized: list[Mapping[str, Any]] = []
    primary = Path(primary_workspace_dir)
    for raw_entry in _sidecar_config_entries(config):
        entry = dict(raw_entry)
        identity = resolve_sidecar_repo_identity(
            entry,
            primary_workspace_dir=str(primary),
            default_entry=entry.get(DEFAULT_LINKED_REPO_MARKER) is True,
            config=config,
        )
        normalized_entry = dict(entry)
        normalized_entry.setdefault("auto_clone", False)
        normalized_entry.setdefault("auto_sync", False)
        normalized_entry.setdefault("visibility", "public")
        if normalized_entry.get("name") == ATTACHMENTS_PRIVATE_SIDECAR_ROLE:
            # The private attachment store is private-only: an explicit
            # ``visibility: public`` is a config error surfaced by preflight
            # ("config requires private"), never a public create.
            normalized_entry["visibility"] = "private"
        if normalized_entry.get("name") == ATTACHMENTS_SIDECAR_ROLE:
            normalized_entry["visibility"] = "public"
        normalized_entry.setdefault("disabled", False)
        normalized_entry[SIDECAR_REPO_MARKER] = True
        if identity is not None:
            normalized_entry["name"] = identity.role
            normalized_entry.setdefault(
                "path", str(primary / "sase" / "repos" / identity.role)
            )
            normalized_entry[SIDECAR_ROLE_KEY] = identity.role
            normalized_entry[SIDECAR_SLUG_KEY] = identity.slug
            normalized_entry[SIDECAR_REPO_REF_KEY] = identity.repo
            normalized_entry[SIDECAR_REMOTE_URL_KEY] = identity.remote_url
        normalized.append(normalized_entry)
    return tuple(normalized)


def reset_entries_caches() -> None:
    """Clear memoized sidecar entry derivations owned by this module."""

    _merged_sidecar_entries_cached.cache_clear()


def configured_sidecar_roles(
    config: Mapping[str, Any],
    *,
    primary_workspace_dir: str,
    include_hidden: bool = False,
) -> tuple[str, ...]:
    """Return enabled configured sidecar roles in declaration order."""

    roles: list[str] = []
    for entry in merged_sidecar_entries_from_config(
        config,
        primary_workspace_dir=primary_workspace_dir,
    ):
        if entry.get("disabled") is True:
            continue
        role = optional_entry_text(entry, SIDECAR_ROLE_KEY)
        if role is None or (not include_hidden and role in HIDDEN_SIDECAR_ROLES):
            continue
        roles.append(role)
    return tuple(dict.fromkeys(roles))


def merged_repo_entries_from_config(
    config: Mapping[str, Any],
    *,
    primary_workspace_dir: str,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    """Return canonical linked entries followed by configured sidecars."""

    linked, warnings = merged_linked_entries_from_config(config)
    sidecars = merged_sidecar_entries_from_config(
        config,
        primary_workspace_dir=primary_workspace_dir,
    )
    return [*linked, *sidecars], warnings


def _entries_for_key(config: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    raw = config.get(key, [])
    if not isinstance(raw, list):
        return []
    entries: list[Mapping[str, Any]] = []
    for item in raw:
        if isinstance(item, Mapping):
            entries.append({str(name): value for name, value in item.items()})
    return entries


def _sidecar_config_entries(config: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return raw ``repos.sidecar`` entries with the role in ``name``.

    ``repos.sidecar`` is a ``{builtin: {...}, custom: {...}}`` mapping keyed by
    role. The reserved builtin roles are emitted in canonical
    ``plans, beads, agents, attachments, attachments-private`` order followed by custom
    roles in configured order; a role declared in both buckets resolves to
    the ``custom`` entry, matching how custom model aliases win over builtin
    ones.
    """

    repos = config.get(REPOS_CONFIG_KEY)
    raw = repos.get(REPOS_SIDECAR_CONFIG_KEY) if isinstance(repos, Mapping) else None
    if not isinstance(raw, Mapping):
        return []

    builtin = _sidecar_bucket_entries(raw, SIDECAR_BUILTIN_CONFIG_KEY)
    custom = _sidecar_bucket_entries(raw, SIDECAR_CUSTOM_CONFIG_KEY)
    ordered_roles = dict.fromkeys(
        [role for role in _BUILTIN_SIDECAR_ROLE_ORDER if role in builtin]
        + [role for role in builtin if role not in _BUILTIN_SIDECAR_ROLE_ORDER]
        + list(custom)
    )
    merged = {**builtin, **custom}
    return [{**merged[role], "name": role} for role in ordered_roles]


def _sidecar_bucket_entries(
    raw: Mapping[str, Any], bucket: str
) -> dict[str, Mapping[str, Any]]:
    """Return one bucket's role-to-entry mapping, skipping unusable values."""

    values = raw.get(bucket)
    if not isinstance(values, Mapping):
        return {}
    entries: dict[str, Mapping[str, Any]] = {}
    for raw_role, entry in values.items():
        if not isinstance(raw_role, str) or not isinstance(entry, Mapping):
            continue
        role = raw_role.strip()
        if not role:
            continue
        entries[role] = {str(key): value for key, value in entry.items()}
    return entries


def _entries_for_repos_key(
    config: Mapping[str, Any], key: str
) -> list[Mapping[str, Any]]:
    repos = config.get(REPOS_CONFIG_KEY)
    if not isinstance(repos, Mapping):
        return []
    return _entries_for_key(repos, key)


def _dedupe_entries(
    entries: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    seen: set[str] = set()
    deduped: list[Mapping[str, Any]] = []
    for entry in entries:
        key = json.dumps(_json_safe_entry(entry), sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _entries_equivalent(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return _json_safe_entry(left) == _json_safe_entry(right)


def _json_safe_entry(entry: Mapping[str, Any]) -> dict[str, object]:
    name = entry.get("name")
    path = entry.get("path")
    revision_pin = entry.get(REVISION_PIN_CONFIG_KEY)
    return {
        "name": name if isinstance(name, str) else "",
        "path": path if isinstance(path, str) else "",
        "description": (
            entry.get("description")
            if isinstance(entry.get("description"), str)
            else ""
        ),
        "auto_clone": entry.get("auto_clone") is True,
        "revision_pin": revision_pin if isinstance(revision_pin, str) else "",
    }
