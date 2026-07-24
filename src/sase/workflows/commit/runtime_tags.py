"""Runtime provenance tags for real VCS commits."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from sase.core.commit_footer_facade import (
    CommitTagValue,
    LinkedCommitTagValue,
    parse_commit_footer,
    update_commit_footer,
)

PRODUCED_RUNTIME_COMMIT_TAG_KEYS = frozenset({"AGENT"})
STALE_RUNTIME_COMMIT_TAG_KEYS = frozenset({"AGENT", "MACHINE"})
# Compatibility name for callers that use this set specifically for cleanup.
RUNTIME_COMMIT_TAG_KEYS = STALE_RUNTIME_COMMIT_TAG_KEYS

#: Prefix rendered onto every SASE-authored commit footer tag key. New commit
#: messages write ``SASE_<KEY>=<value>`` while readers still accept the legacy
#: unprefixed spelling (see :func:`_canonicalize_commit_tag_key`).
COMMIT_TAG_PREFIX = "SASE_"


def _canonicalize_commit_tag_key(key: str) -> str:
    """Return *key* without the :data:`COMMIT_TAG_PREFIX`.

    Canonical (unprefixed) keys are the internal form used by helper inputs,
    parsing results, and runtime-owned key comparisons, so callers can keep
    passing ``{"TYPE": ...}`` regardless of how the footer is rendered.
    """
    if key.startswith(COMMIT_TAG_PREFIX):
        return key[len(COMMIT_TAG_PREFIX) :]
    return key


def _resolve_runtime_commit_tags() -> dict[str, CommitTagValue]:
    """Return runtime-owned commit tags for the current process."""
    local_name = resolve_local_agent_name()
    if not local_name:
        return {}
    from sase.agents_sync.links import resolve_agent_commit_tag
    from sase.config import require_agent_owner_identity
    from sase.core.agent_identity_facade import AgentIdentitySnapshot

    identity = AgentIdentitySnapshot(require_agent_owner_identity())
    return {"AGENT": resolve_agent_commit_tag(local_name, identity=identity)}


def resolve_local_agent_name() -> str | None:
    """Resolve the current locally stored SASE agent name, if available."""
    env_name = _sanitize_tag_value(os.environ.get("SASE_AGENT_NAME"))
    if env_name:
        return env_name

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return None

    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(meta, dict):
        return None
    meta_name = _sanitize_tag_value(meta.get("name"))
    return meta_name


def apply_runtime_commit_tags(payload: dict) -> None:
    """Append or update runtime provenance tags in ``payload['message']``."""
    message = str(payload.get("message") or "")
    payload["message"] = update_trailing_commit_tags(
        message,
        _resolve_runtime_commit_tags(),
        remove_keys=STALE_RUNTIME_COMMIT_TAG_KEYS,
    )


def apply_auto_commit_type_tag(message: str, auto_commit_type: str) -> str:
    """Append or update the auto-commit ``TYPE`` tag in *message*."""
    return update_trailing_commit_tags(
        message,
        {"TYPE": auto_commit_type},
        remove_keys={"TYPE"},
    )


def apply_auto_commit_tags_with_runtime(message: str, auto_commit_type: str) -> str:
    """Compose the auto-commit ``TYPE`` tag with runtime provenance tags.

    When a SASE agent identity is available (``SASE_AGENT_NAME`` or an
    ``agent_meta.json`` ``name``), the resulting tag block also carries linked
    ``AGENT=`` provenance so raw SDD auto-commits can be associated with the
    agent that produced them. Legacy ``MACHINE=`` is removed but never
    produced. Without an agent identity the result carries only
    ``TYPE=<kind>`` after stale runtime provenance is removed.
    """
    updates: dict[str, object] = {"TYPE": auto_commit_type}
    remove_keys: set[str] = {"TYPE", *STALE_RUNTIME_COMMIT_TAG_KEYS}

    runtime_tags = _resolve_runtime_commit_tags()
    if runtime_tags:
        updates.update(runtime_tags)

    return update_trailing_commit_tags(message, updates, remove_keys=remove_keys)


def parse_trailing_commit_tags(message: str) -> dict[str, str]:
    """Return the trailing ``KEY=VALUE`` tag block of *message* as a dict.

    Only the contiguous block of ``KEY=VALUE`` lines at the very end of the
    message is parsed. Keys are returned in canonical (unprefixed) form so both
    legacy ``AGENT=`` and new ``SASE_AGENT=`` lines read as ``AGENT``. Later
    duplicate keys win, matching how the block is rendered by
    :func:`update_trailing_commit_tags`.
    """
    return {tag.key: tag.label for tag in parse_commit_footer(message).tags}


def parse_trailing_commit_tag_values(message: str) -> dict[str, CommitTagValue]:
    """Return canonical tag values while retaining optional link targets."""
    return {tag.key: tag.value for tag in parse_commit_footer(message).tags}


def update_trailing_commit_tags(
    message: str,
    updates: Mapping[str, object],
    *,
    remove_keys: frozenset[str] | set[str] = frozenset(),
) -> str:
    """Update the trailing ``KEY=VALUE`` tag block in *message*.

    Input keys (both ``updates`` and ``remove_keys``) are treated as canonical
    and compared without the :data:`COMMIT_TAG_PREFIX`, so an owned key removes
    both its legacy (``TYPE=``) and prefixed (``SASE_TYPE=``) spelling from the
    existing block. Existing non-owned tags are preserved in their original
    order, then sanitized non-empty update values are appended. Every final
    footer key is rendered with the ``SASE_`` prefix.
    """
    return update_commit_footer(message, updates, remove_keys=remove_keys)


def filter_runtime_owned_tags(tags: Mapping[str, object]) -> dict[str, object]:
    """Remove runtime-owned tag keys from inherited/configured PR tag maps.

    Keys are compared in canonical form so ``AGENT``/``MACHINE`` and their
    ``SASE_AGENT``/``SASE_MACHINE`` spellings are all filtered out.
    """
    return {
        key: value
        for key, value in tags.items()
        if _canonicalize_commit_tag_key(key) not in STALE_RUNTIME_COMMIT_TAG_KEYS
    }


def _sanitize_tag_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text or None
