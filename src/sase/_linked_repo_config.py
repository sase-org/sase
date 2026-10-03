"""Configuration merging and defaults for linked repositories.

Thin facade over the split ``_linked_repo_config_*`` modules. Public names
keep their original ``sase._linked_repo_config`` import path; private
(``_``-prefixed) names live in the split modules and must be imported there.
"""

from __future__ import annotations

from sase._linked_repo_config_defaults import (
    inject_default_linked_repos,
    normalize_revision_pin,
    revision_pin_escapes_primary,
    revision_pin_for_entry,
)
from sase._linked_repo_config_entries import (
    configured_sidecar_roles,
    merged_linked_entries_from_config,
    merged_repo_entries_from_config,
    merged_sidecar_entries_from_config,
)
from sase._linked_repo_config_keys import (
    DEFAULT_AGENTS_DESCRIPTION,
    DEFAULT_ATTACHMENTS_DESCRIPTION,
    DEFAULT_ATTACHMENTS_PRIVATE_DESCRIPTION,
    DEFAULT_BEADS_DESCRIPTION,
    DEFAULT_LINKED_REPOS_CONFIG_KEY,
    DEFAULT_PLANS_DESCRIPTION,
    DEFAULT_RESEARCH_DESCRIPTION,
    HIDDEN_SIDECAR_ROLES,
    LINKED_REPOS_CONFIG_KEY,
    REPOS_CONFIG_KEY,
    REPOS_LINKED_CONFIG_KEY,
    REPOS_SIDECAR_CONFIG_KEY,
    REVISION_PIN_CONFIG_KEY,
    SIBLING_REPOS_CONFIG_KEY,
    SIDECAR_BUILTIN_CONFIG_KEY,
    SIDECAR_CUSTOM_CONFIG_KEY,
)
from sase._linked_repo_config_state import (
    RepoConfigCacheKey,
    normalize_path,
    read_project_local_config,
    repo_config_cache_key,
    resolution_config,
    resolve_config_path,
)
from sase.sdd._store_types import (
    AGENTS_SIDECAR_ROLE,
    ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
    ATTACHMENTS_SIDECAR_ROLE,
    BEADS_SIDECAR_ROLE,
    PLANS_SIDECAR_ROLE,
)

__all__ = [
    "AGENTS_SIDECAR_ROLE",
    "ATTACHMENTS_PRIVATE_SIDECAR_ROLE",
    "ATTACHMENTS_SIDECAR_ROLE",
    "BEADS_SIDECAR_ROLE",
    "DEFAULT_AGENTS_DESCRIPTION",
    "DEFAULT_ATTACHMENTS_DESCRIPTION",
    "DEFAULT_ATTACHMENTS_PRIVATE_DESCRIPTION",
    "DEFAULT_BEADS_DESCRIPTION",
    "DEFAULT_LINKED_REPOS_CONFIG_KEY",
    "DEFAULT_PLANS_DESCRIPTION",
    "DEFAULT_RESEARCH_DESCRIPTION",
    "HIDDEN_SIDECAR_ROLES",
    "LINKED_REPOS_CONFIG_KEY",
    "PLANS_SIDECAR_ROLE",
    "REPOS_CONFIG_KEY",
    "REPOS_LINKED_CONFIG_KEY",
    "REPOS_SIDECAR_CONFIG_KEY",
    "REVISION_PIN_CONFIG_KEY",
    "RepoConfigCacheKey",
    "SIBLING_REPOS_CONFIG_KEY",
    "SIDECAR_BUILTIN_CONFIG_KEY",
    "SIDECAR_CUSTOM_CONFIG_KEY",
    "configured_sidecar_roles",
    "inject_default_linked_repos",
    "merged_linked_entries_from_config",
    "merged_repo_entries_from_config",
    "merged_sidecar_entries_from_config",
    "normalize_path",
    "normalize_revision_pin",
    "read_project_local_config",
    "repo_config_cache_key",
    "reset_linked_repo_config_caches",
    "resolution_config",
    "resolve_config_path",
    "revision_pin_escapes_primary",
    "revision_pin_for_entry",
]


def reset_linked_repo_config_caches() -> None:
    """Clear memoized linked-repository config derivations."""

    from sase._linked_repo_config_entries import reset_entries_caches
    from sase._linked_repo_config_state import reset_state_caches

    reset_state_caches()
    reset_entries_caches()
