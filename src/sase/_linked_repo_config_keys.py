"""Shared config keys, descriptions, and sidecar markers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.sdd._store_types import (
    AGENTS_SIDECAR_ROLE,
    ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
    ATTACHMENTS_SIDECAR_ROLE,
)

REPOS_CONFIG_KEY = "repos"
REPOS_LINKED_CONFIG_KEY = "linked"
REVISION_PIN_CONFIG_KEY = "revision_pin"
REPOS_SIDECAR_CONFIG_KEY = "sidecar"
LINKED_REPOS_CONFIG_KEY = "linked_repos"
SIBLING_REPOS_CONFIG_KEY = "sibling_repos"
DEFAULT_LINKED_REPOS_CONFIG_KEY = "default_linked_repos"

DEFAULT_AGENTS_DESCRIPTION = (
    "Hidden sidecar that stores commit-associated sase agent data, prompts, "
    "and prompt-linked artifacts for this project."
)
DEFAULT_BEADS_DESCRIPTION = (
    "Durable SASE bead state: the append-only event store and its projections."
)
DEFAULT_PLANS_DESCRIPTION = "Durable SASE plans and plan-side generated docs."
DEFAULT_RESEARCH_DESCRIPTION = "Durable SASE research reports and generated media."
DEFAULT_ATTACHMENTS_PRIVATE_DESCRIPTION = (
    "Hidden sidecar that stores private bead attachment bytes for this project."
)
DEFAULT_ATTACHMENTS_DESCRIPTION = (
    "Hidden sidecar that stores public bead attachment bytes for this project."
)
HIDDEN_SIDECAR_ROLES = frozenset(
    {
        AGENTS_SIDECAR_ROLE,
        ATTACHMENTS_SIDECAR_ROLE,
        ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
    }
)

SIDECAR_BUILTIN_CONFIG_KEY = "builtin"
SIDECAR_CUSTOM_CONFIG_KEY = "custom"

DEFAULT_LINKED_REPO_MARKER = "_sase_default_linked_repo"
SIDECAR_REPO_MARKER = "_sase_sidecar_repo"
SIDECAR_ROLE_KEY = "_sase_sidecar_role"
SIDECAR_SLUG_KEY = "_sase_sidecar_slug"
SIDECAR_REMOTE_URL_KEY = "_sase_sidecar_remote_url"
SIDECAR_REPO_REF_KEY = "_sase_sidecar_repo_ref"


def optional_entry_text(entry: Mapping[str, Any], key: str) -> str:
    """Return ``entry[key]`` stripped, or ``""`` when absent or non-text."""

    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""
