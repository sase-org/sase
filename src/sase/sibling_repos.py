"""Deprecated compatibility wrapper for configured related repositories.

The canonical implementation now lives in :mod:`sase.linked_repos` under the
public ``linked_repos`` config key. This module re-exports the linked-repo
primitives under their historical ``sibling`` names so existing import sites and
external tooling keep working during the migration window. New code should
import from :mod:`sase.linked_repos` instead.
"""

from __future__ import annotations

from sase.linked_repos import (
    LinkedRepoResolution as SiblingRepoResolution,
    OPENED_SIBLINGS_FILENAME as OPENED_SIBLINGS_FILENAME,
    SIBLING_REPO_ENV_PREFIX as SIBLING_REPO_ENV_PREFIX,
    SIBLING_REPO_ENV_SUFFIXES as SIBLING_REPO_ENV_SUFFIXES,
    SIBLING_REPOS_JSON_ENV as SIBLING_REPOS_JSON_ENV,
    apply_linked_repo_env as apply_sibling_repo_env,
    linked_repo_metadata_from_env as sibling_repo_metadata_from_env,
    opened_linked_repo_names as opened_sibling_names,
    opened_linked_repo_workspace_dirs as opened_sibling_workspace_dirs,
    record_opened_linked_repo as record_opened_sibling,
    resolve_linked_repos_for_project as resolve_sibling_repos_for_project,
    scrub_linked_repo_env as scrub_sibling_repo_env,
)

__all__ = [
    "OPENED_SIBLINGS_FILENAME",
    "SIBLING_REPOS_JSON_ENV",
    "SIBLING_REPO_ENV_PREFIX",
    "SIBLING_REPO_ENV_SUFFIXES",
    "SiblingRepoResolution",
    "apply_sibling_repo_env",
    "opened_sibling_names",
    "opened_sibling_workspace_dirs",
    "record_opened_sibling",
    "resolve_sibling_repos_for_project",
    "scrub_sibling_repo_env",
    "sibling_repo_metadata_from_env",
]
