"""Clone paths and sidecar directory naming for linked repositories."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from sase._linked_repo_config import (
    HIDDEN_SIDECAR_ROLES,
    _SIDECAR_ROLE_KEY,
    _SIDECAR_SLUG_KEY,
    RepoConfigCacheKey,
    merged_sidecar_entries_from_config,
    normalize_path,
    repo_config_cache_key,
    resolution_config,
)
from sase.core.paths import sase_projects_dir

# Host-scoped linked and sidecar clones are launch-scoped in numbered
# workspaces. Sidecars created there are cloned from their recorded remotes.
SIDECAR_REPO_CLONES_SUBDIR = ("sase", "repos")
LINKED_REPO_CLONES_SUBDIR = ("sase", "repos", "linked")
EXTERNAL_REPO_CLONES_SUBDIR = ("sase", "repos", "external")


def linked_repo_clone_dir(host_checkout: str | Path, name: str) -> str:
    """Return the canonical host-scoped clone path for linked repo *name*."""

    return normalize_path(
        str(Path(host_checkout).joinpath(*LINKED_REPO_CLONES_SUBDIR, name))
    )


def external_repo_clone_dir(
    host_checkout: str | Path,
    scheme_or_projects: str,
    *parts: str,
) -> str:
    """Return a host-scoped clone path below ``sase/repos/external``."""

    components = (scheme_or_projects, *parts)
    if any(
        not component
        or component in {".", ".."}
        or component != component.strip()
        or "/" in component
        or "\\" in component
        for component in components
    ):
        raise ValueError("external repo clone path components must be safe names")
    return normalize_path(
        str(Path(host_checkout).joinpath(*EXTERNAL_REPO_CLONES_SUBDIR, *components))
    )


def sidecar_repo_clone_dir(host_checkout: str | Path, dirname: str) -> str:
    """Return the durable host-scoped clone path for SDD sidecar *dirname*."""

    return normalize_path(
        str(Path(host_checkout).joinpath(*SIDECAR_REPO_CLONES_SUBDIR, dirname))
    )


def hidden_sidecar_clone_dir(project_key: str, role: str) -> str:
    """Return one project's stable machine-level hidden-sidecar clone path."""

    components = {"project key": project_key, "sidecar role": role}
    for label, component in components.items():
        if (
            not isinstance(component, str)
            or not component
            or component in {".", ".."}
            or component != component.strip()
            or component.startswith(".")
            or "/" in component
            or "\\" in component
            or "\x00" in component
        ):
            raise ValueError(f"{label} must be a safe path component")
    return normalize_path(str(sase_projects_dir() / project_key / "repos" / role))


def _repo_basename(repo: str) -> str:
    return repo.rstrip("/").rsplit("/", 1)[-1]


def _sdd_sidecar_repo_dirnames(
    primary_workspace_dir: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Map configured/store/fallback sidecar names to clone directory names."""

    primary = Path(primary_workspace_dir).expanduser().resolve(strict=False)
    try:
        resolved_config = resolution_config(str(primary), config)
        config_key = repo_config_cache_key(resolved_config)
    except Exception:
        config_key = None
    return dict(_sdd_sidecar_repo_dirnames_cached(str(primary), config_key))


@lru_cache(maxsize=256)
def _sdd_sidecar_repo_dirnames_cached(
    primary_workspace_dir: str,
    config_key: RepoConfigCacheKey | None,
) -> tuple[tuple[str, str], ...]:
    from sase.sdd.store import read_sdd_store_record

    primary = Path(primary_workspace_dir)
    configured: dict[str, str] = {}
    configured_roles: set[str] = set()
    disabled: set[str] = set()
    hidden: set[str] = set()
    try:
        configured_entries = (
            []
            if config_key is None
            else merged_sidecar_entries_from_config(
                config_key.config,
                primary_workspace_dir=str(primary),
            )
        )
    except Exception:
        configured_entries = []
    for entry in configured_entries:
        role = _entry_text(entry, _SIDECAR_ROLE_KEY)
        slug = _entry_text(entry, _SIDECAR_SLUG_KEY)
        tokens = {token for token in (role, slug) if token}
        if role in HIDDEN_SIDECAR_ROLES:
            hidden.update(tokens)
            continue
        if role:
            configured_roles.add(role)
        if entry.get("disabled") is True:
            disabled.update(tokens)
            continue
        if role:
            configured.update(dict.fromkeys(tokens, role))

    record = read_sdd_store_record(primary)
    if record is not None:
        store_mapping = {
            _repo_basename(sidecar.repo): kind
            for kind, sidecar in record.sidecars.items()
            if kind not in configured_roles
            and kind not in disabled
            and kind not in hidden
            and _repo_basename(sidecar.repo) not in disabled
            and _repo_basename(sidecar.repo) not in hidden
        }
        mapping = {
            key: value
            for key, value in {**store_mapping, **configured}.items()
            if key not in hidden and value not in hidden
        }
        return tuple(mapping.items())

    project_name = primary.name
    if not project_name:
        return tuple(configured.items())
    from sase.sdd.store import BEADS_SIDECAR_ROLE, PLANS_SIDECAR_ROLE

    fallbacks = {
        slug: kind
        for kind in (PLANS_SIDECAR_ROLE, BEADS_SIDECAR_ROLE)
        if kind not in configured_roles
        if kind not in disabled
        if kind not in hidden
        if (slug := f"{project_name}--{kind}") not in disabled
        if slug not in hidden
    }
    mapping = {
        key: value
        for key, value in {**fallbacks, **configured}.items()
        if key not in hidden and value not in hidden
    }
    return tuple(mapping.items())


def reset_linked_repo_path_caches() -> None:
    """Clear memoized sidecar path derivations."""

    _sdd_sidecar_repo_dirnames_cached.cache_clear()


def sdd_sidecar_clone_dirname(
    primary_workspace_dir: str | Path,
    name: str,
    *,
    config: Mapping[str, Any] | None = None,
) -> str | None:
    """Return the clone dirname for sidecar entry *name*, if it is one."""

    return _sdd_sidecar_repo_dirnames(
        primary_workspace_dir,
        config=config,
    ).get(name)


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""
